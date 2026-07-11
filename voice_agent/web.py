"""Local transcript web UI for console mode."""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Lock, Thread

from .call_assessment import assess_call
from .conversation_fsm import CaseContext
from .diarized_stt import DiarizedTranscript

DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8765


@dataclass(frozen=True)
class TranscriptMessage:
    id: int
    role: str
    text: str
    speaker: str | None
    segments: tuple[dict[str, object], ...] = ()


class TranscriptStore:
    """Thread-safe conversation state exposed to the local web page."""

    def __init__(self, *, adherence_case: CaseContext | None = None) -> None:
        self._lock = Lock()
        self._adherence_case = adherence_case
        self._messages: list[TranscriptMessage] = []
        self._next_id = 1
        self._metric_order = ("llm", "stt", "tts", "eou", "barge_in")
        self._metrics: dict[str, dict[str, object]] = {}
        self._user_state = "listening"
        self._agent_state = "initializing"
        self._barge_in_state: dict[str, object] = {
            "enabled": True,
            "state": "monitoring",
            "last_reason": "Waiting for user speech while agent is speaking",
            "detected": 0,
            "confirmed": 0,
            "ignored": 0,
            "false_interruptions": 0,
            "resumed_false_interruptions": 0,
        }
        self._barge_in_events: list[dict[str, object]] = []
        self._fsm_state: dict[str, object] = {
            "phase": "awaiting_start",
            "intent": "none",
            "directive": "waiting_for_fsm",
            "guard_reason": None,
            "identity_verified": False,
            "refusal_count": 0,
            "resolution_type": None,
            "should_end": False,
            "turn_id": None,
        }
        self._fsm_transitions: list[dict[str, object]] = []
        self._fsm_events: list[dict[str, object]] = []
        self._call_assessment = assess_call(
            events=self._fsm_events,
            fsm_state=self._fsm_state,
            transitions=self._fsm_transitions,
            case=self._adherence_case,
        )
        self._live_user_text = ""
        self._live_user_speaker: str | None = None
        self._live_agent_text = ""
        self._last_user_text: str | None = None
        self._last_agent_text: str | None = None
        self._models: tuple[dict[str, str], ...] = ()
        self._technologies: tuple[str, ...] = ()
        self._hero_card = {
            "title": "",
            "items": ["Javier Castro", "DNAI", "2026"],
        }

    def set_models(self, models: list[dict[str, str]]) -> None:
        with self._lock:
            self._models = tuple(
                {"label": model["label"], "value": model["value"]}
                for model in models
            )

    def set_hero_card(self, *, title: str, items: list[str]) -> None:
        with self._lock:
            self._hero_card = {
                "title": title,
                "items": [item for item in items if item],
            }

    def set_technologies(self, technologies: list[str]) -> None:
        with self._lock:
            self._technologies = tuple(technology for technology in technologies if technology)

    def set_metric_panel(
        self,
        *,
        panel_id: str,
        title: str,
        items: list[dict[str, str]],
    ) -> None:
        with self._lock:
            self._metrics[panel_id] = {
                "id": panel_id,
                "title": title,
                "items": [
                    {"label": item["label"], "value": item["value"]}
                    for item in items
                ],
            }

    def set_user_state(self, state: str) -> None:
        with self._lock:
            self._user_state = state
            if state != "speaking" and not self._live_user_text:
                self._live_user_speaker = None

    def set_agent_state(self, state: str) -> None:
        with self._lock:
            self._agent_state = state

    def set_barge_in_state(self, state: dict[str, object]) -> None:
        with self._lock:
            self._barge_in_state = dict(state)

    def add_barge_in_event(self, event: dict[str, object]) -> None:
        with self._lock:
            self._barge_in_events.append(dict(event))
            self._barge_in_events = self._barge_in_events[-200:]

    def add_fsm_event(self, event: dict[str, object]) -> None:
        """Project minimized trace evidence into the live FSM monitor."""

        event_type = str(event.get("type", ""))
        turn_id = str(event.get("turnId", "") or "")
        with self._lock:
            if event_type in {
                "fsm_transition",
                "assistant_response",
                "turn_superseded",
            }:
                self._fsm_events.append(dict(event))
            if event_type == "fsm_transition":
                transition = {
                    "turn_id": turn_id,
                    "recorded_at": str(event.get("recordedAt", "")),
                    "from_phase": str(event.get("fromPhase", "")),
                    "to_phase": str(event.get("toPhase", "")),
                    "intent": str(event.get("interpretedIntent", "")),
                    "directive": str(event.get("directive", "")),
                    "guard_reason": event.get("guardReason"),
                    "identity_verified": bool(event.get("identityVerified", False)),
                    "refusal_count": int(event.get("refusalCount", 0) or 0),
                    "resolution_type": event.get("resolutionType"),
                    "should_end": bool(event.get("shouldEnd", False)),
                    "interpreter": event.get("interpreter"),
                    "response_recorded": False,
                    "response_disposition": "pending",
                }
                self._fsm_transitions.append(transition)
                self._fsm_transitions = self._fsm_transitions[-100:]
                self._fsm_state = {
                    "phase": transition["to_phase"],
                    "intent": transition["intent"],
                    "directive": transition["directive"],
                    "guard_reason": transition["guard_reason"],
                    "identity_verified": transition["identity_verified"],
                    "refusal_count": transition["refusal_count"],
                    "resolution_type": transition["resolution_type"],
                    "should_end": transition["should_end"],
                    "turn_id": transition["turn_id"],
                }
            elif event_type == "assistant_response" and turn_id:
                for transition in reversed(self._fsm_transitions):
                    if transition["turn_id"] == turn_id:
                        transition["response_recorded"] = True
                        transition["response_disposition"] = "recorded"
                        break
            elif event_type == "turn_superseded" and turn_id:
                for transition in reversed(self._fsm_transitions):
                    if transition["turn_id"] == turn_id:
                        transition["response_disposition"] = "coalesced"
                        break
            self._call_assessment = assess_call(
                events=self._fsm_events,
                fsm_state=self._fsm_state,
                transitions=self._fsm_transitions,
                case=self._adherence_case,
            )

    def set_live_user_text(self, text: str, *, speaker: str | None = None) -> None:
        cleaned = text.strip()
        with self._lock:
            self._live_user_text = cleaned
            self._live_user_speaker = speaker

    def clear_live_user_text(self) -> None:
        with self._lock:
            self._live_user_text = ""
            self._live_user_speaker = None

    def add_user_text(self, text: str, *, speaker: str | None = None) -> None:
        cleaned = text.strip()
        if not cleaned:
            return

        normalized = self._normalize(cleaned)
        with self._lock:
            if normalized == self._last_user_text:
                self._live_user_text = ""
                self._live_user_speaker = None
                return

            self._append_message(role="user", text=cleaned, speaker=speaker or "You")
            self._last_user_text = normalized
            self._live_user_text = ""
            self._live_user_speaker = None

    def add_user_diarized(self, transcript: DiarizedTranscript) -> None:
        cleaned = transcript.text.strip()
        if not cleaned:
            return

        segments = tuple(
            {
                "speaker": segment.speaker,
                "text": segment.text,
                "start": segment.start,
                "end": segment.end,
            }
            for segment in transcript.segments
            if segment.text.strip()
        )
        normalized = self._normalize(cleaned)

        with self._lock:
            if normalized == self._last_user_text:
                self._live_user_text = ""
                self._live_user_speaker = None
                return

            speaker = segments[0]["speaker"] if len({seg["speaker"] for seg in segments}) == 1 else "You"
            self._append_message(role="user", text=cleaned, speaker=str(speaker), segments=segments)
            self._last_user_text = normalized
            self._live_user_text = ""
            self._live_user_speaker = None

    def append_agent_delta(self, text: str) -> None:
        if not text:
            return

        with self._lock:
            self._live_agent_text += text

    def finalize_agent_stream(self) -> None:
        with self._lock:
            cleaned = self._live_agent_text.strip()
            if not cleaned:
                self._live_agent_text = ""
                return

            normalized = self._normalize(cleaned)
            if normalized != self._last_agent_text:
                self._append_message(role="agent", text=cleaned, speaker="Agent")
                self._last_agent_text = normalized

            self._live_agent_text = ""

    def add_agent_text(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return

        normalized = self._normalize(cleaned)
        with self._lock:
            if normalized == self._last_agent_text:
                return

            self._append_message(role="agent", text=cleaned, speaker="Agent")
            self._last_agent_text = normalized

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            metric_panels = [
                {
                    "id": str(self._metrics[panel_id]["id"]),
                    "title": str(self._metrics[panel_id]["title"]),
                    "items": [
                        {"label": str(item["label"]), "value": str(item["value"])}
                        for item in self._metrics[panel_id]["items"]
                    ],
                }
                for panel_id in self._metric_order
                if panel_id in self._metrics
            ]
            return {
                "user_state": self._user_state,
                "agent_state": self._agent_state,
                "barge_in_state": dict(self._barge_in_state),
                "barge_in_kpis": dict(self._barge_in_state.get("kpis", {})),
                "barge_in_events": [dict(event) for event in self._barge_in_events],
                "fsm_state": dict(self._fsm_state),
                "fsm_transitions": [
                    dict(transition) for transition in self._fsm_transitions
                ],
                "call_assessment": {
                    **self._call_assessment,
                    "evidence": [
                        dict(item) for item in self._call_assessment["evidence"]
                    ],
                    "improvements": list(self._call_assessment["improvements"]),
                    "findings": [
                        dict(item) for item in self._call_assessment["findings"]
                    ],
                },
                "live_user_text": self._live_user_text,
                "live_user_speaker": self._live_user_speaker,
                "live_agent_text": self._live_agent_text,
                "models": list(self._models),
                "metrics": metric_panels,
                "hero_card": {
                    "title": self._hero_card["title"],
                    "items": list(self._hero_card["items"]),
                },
                "technologies": list(self._technologies),
                "messages": [
                    {
                        "id": message.id,
                        "role": message.role,
                        "text": message.text,
                        "speaker": message.speaker,
                        "segments": list(message.segments),
                    }
                    for message in self._messages
                ],
            }

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.split())

    def _append_message(
        self,
        *,
        role: str,
        text: str,
        speaker: str | None,
        segments: tuple[dict[str, object], ...] = (),
    ) -> None:
        self._messages.append(
            TranscriptMessage(
                id=self._next_id,
                role=role,
                text=text,
                speaker=speaker,
                segments=segments,
            )
        )
        self._next_id += 1


class TranscriptWebServer:
    """Lightweight local HTTP server that renders transcript state."""

    def __init__(
        self,
        *,
        host: str = DEFAULT_WEB_HOST,
        port: int = DEFAULT_WEB_PORT,
        store: TranscriptStore | None = None,
        adherence_case: CaseContext | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self.store = store or TranscriptStore(adherence_case=adherence_case)
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    @property
    def url(self) -> str:
        if self._server is None:
            return f"http://{self._host}:{self._port}/"

        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/"

    def start(self) -> None:
        if self._server is not None:
            return

        handler = self._build_handler(self.store)
        try:
            self._server = ThreadingHTTPServer((self._host, self._port), handler)
        except OSError:
            self._server = ThreadingHTTPServer((self._host, 0), handler)

        self._thread = Thread(target=self._server.serve_forever, name="transcript-web", daemon=True)
        self._thread.start()

    def close(self) -> None:
        if self._server is None:
            return

        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

        self._server = None
        self._thread = None

    @staticmethod
    def _build_handler(store: TranscriptStore) -> type[BaseHTTPRequestHandler]:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path in {"/", "/index.html"}:
                    self._send_html(_build_html())
                    return

                if self.path == "/api/state":
                    self._send_json(store.snapshot())
                    return

                if self.path == "/health":
                    self._send_json({"status": "ok"})
                    return

                self.send_error(HTTPStatus.NOT_FOUND)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

            def _send_html(self, body: str) -> None:
                payload = body.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _send_json(self, body: dict[str, object]) -> None:
                payload = json.dumps(body).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        return Handler


def _build_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>Voice Agent Transcript</title>
  <style>
    :root {
      --bg: #f4efe5;
      --panel: rgba(255, 251, 245, 0.88);
      --line: rgba(64, 44, 27, 0.12);
      --ink: #20150c;
      --muted: #6a5a4a;
      --accent: #0f766e;
      --accent-soft: rgba(15, 118, 110, 0.12);
      --user: #1d4ed8;
      --user-soft: rgba(29, 78, 216, 0.10);
      --agent: #9a3412;
      --agent-soft: rgba(154, 52, 18, 0.10);
      --shadow: 0 18px 42px rgba(34, 20, 8, 0.10);
      --radius: 22px;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(15, 118, 110, 0.16), transparent 28rem),
        radial-gradient(circle at bottom right, rgba(29, 78, 216, 0.14), transparent 24rem),
        linear-gradient(180deg, #f8f4eb 0%, #efe5d7 100%);
    }

    .shell {
      width: min(1100px, calc(100vw - 32px));
      margin: 28px auto;
      padding: 24px;
      border: 1px solid var(--line);
      border-radius: 28px;
      background: var(--panel);
      backdrop-filter: blur(16px);
      box-shadow: var(--shadow);
    }

    .hero {
      display: grid;
      gap: 18px;
      margin-bottom: 22px;
    }

    .hero-layout {
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) minmax(280px, 0.85fr);
      gap: 18px;
      align-items: start;
    }

    .hero-copy {
      display: grid;
      gap: 14px;
    }

    .eyebrow {
      margin: 0;
      text-transform: uppercase;
      letter-spacing: 0.16em;
      font-size: 12px;
      color: var(--muted);
    }

    h1 {
      margin: 0;
      font-size: clamp(32px, 5vw, 54px);
      line-height: 0.95;
      letter-spacing: -0.04em;
      max-width: 10ch;
    }

    .subhead {
      margin: 0;
      color: var(--muted);
      max-width: 58ch;
      line-height: 1.5;
    }

    .status-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin: 22px 0 28px;
    }

    .overview-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
      margin-bottom: 28px;
      align-items: start;
    }

    .status-card {
      padding: 16px 18px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.55);
    }

    .detail-card {
      padding: 20px;
      border-radius: 22px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.62);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.45);
    }

    .detail-title {
      margin: 0 0 14px;
      font-size: 14px;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: var(--muted);
    }

    .model-list {
      display: grid;
      gap: 10px;
    }

    .section-stack {
      display: grid;
      gap: 18px;
    }

    .metrics-section {
      display: grid;
      gap: 12px;
      margin-bottom: 20px;
    }

    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
    }

    .metric-card {
      padding: 18px;
      border-radius: 20px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.62);
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.4);
      display: grid;
      gap: 10px;
    }

    .metric-title {
      margin: 0;
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.14em;
      color: var(--muted);
    }

    .metric-list {
      display: grid;
      gap: 8px;
    }

    .metric-row {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      padding-top: 8px;
      border-top: 1px solid rgba(64, 44, 27, 0.08);
    }

    .metric-row:first-child {
      padding-top: 0;
      border-top: 0;
    }

    .metric-label {
      color: var(--muted);
      font-size: 14px;
    }

    .metric-value {
      color: var(--ink);
      font-size: 15px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
      text-align: right;
    }

    .model-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      padding: 12px 14px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.68);
      border: 1px solid var(--line);
    }

    .model-name {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
    }

    .model-value {
      font-size: 14px;
      font-weight: 700;
      text-align: right;
      word-break: break-word;
    }

    .tech-list {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }

    .tech-pill {
      display: inline-flex;
      align-items: center;
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(15, 118, 110, 0.08);
      border: 1px solid rgba(15, 118, 110, 0.14);
      font-weight: 700;
      color: #0f5c56;
    }

    .hero-card {
      position: relative;
      overflow: hidden;
      background:
        radial-gradient(circle at top right, rgba(15, 118, 110, 0.08), transparent 9rem),
        linear-gradient(135deg, rgba(29, 78, 216, 0.04), rgba(154, 52, 18, 0.05)),
        rgba(255, 255, 255, 0.68);
      border-color: rgba(64, 44, 27, 0.08);
    }

    .hero .hero-card {
      min-height: 100%;
    }

    .hero-card::after {
      content: "";
      position: absolute;
      inset: auto -12% -28% auto;
      width: 132px;
      height: 132px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.22);
      filter: blur(10px);
    }

    .hero-card-title {
      margin: 0 0 18px;
      font-size: clamp(26px, 3vw, 34px);
      line-height: 1;
      letter-spacing: -0.04em;
    }

    .hero-pill-list {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }

    .hero-pill {
      display: inline-flex;
      align-items: center;
      padding: 10px 14px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.7);
      border: 1px solid rgba(32, 21, 12, 0.08);
      font-weight: 700;
    }

    .status-label {
      display: block;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
      margin-bottom: 8px;
    }

    .status-value {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      font-weight: 700;
      background: rgba(32, 21, 12, 0.06);
    }

    .status-value.is-speaking {
      background: var(--accent-soft);
      color: var(--accent);
    }

    .status-value.is-thinking {
      background: rgba(202, 138, 4, 0.12);
      color: #92400e;
    }

    .call-assessment {
      --assessment-accent: #64748b;
      --assessment-soft: rgba(100, 116, 139, 0.10);
      display: grid;
      grid-template-columns: minmax(240px, 0.78fr) minmax(0, 1.22fr);
      gap: 24px;
      margin-bottom: 18px;
      padding: 24px;
      border: 1px solid color-mix(in srgb, var(--assessment-accent) 28%, transparent);
      border-left: 6px solid var(--assessment-accent);
      border-radius: 22px;
      background: linear-gradient(135deg, var(--assessment-soft), rgba(255, 255, 255, 0.72));
    }

    .call-assessment.is-pass {
      --assessment-accent: #15803d;
      --assessment-soft: rgba(21, 128, 61, 0.11);
    }

    .call-assessment.is-warn,
    .call-assessment.is-finalizing {
      --assessment-accent: #b45309;
      --assessment-soft: rgba(180, 83, 9, 0.10);
    }

    .call-assessment.is-fail {
      --assessment-accent: #b91c1c;
      --assessment-soft: rgba(185, 28, 28, 0.10);
    }

    .assessment-kicker {
      margin: 0 0 8px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.15em;
      text-transform: uppercase;
    }

    .assessment-verdict {
      margin: 0;
      color: var(--assessment-accent);
      font-size: clamp(28px, 4vw, 42px);
      line-height: 1;
      letter-spacing: -0.04em;
    }

    .assessment-summary {
      margin: 12px 0 0;
      color: var(--muted);
      line-height: 1.45;
    }

    .assessment-detail {
      display: grid;
      gap: 16px;
    }

    .assessment-evidence {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }

    .assessment-check {
      min-width: 0;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.68);
    }

    .assessment-check-label {
      display: block;
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }

    .assessment-check-value {
      display: flex;
      align-items: center;
      gap: 7px;
      font-size: 14px;
      font-weight: 750;
      overflow-wrap: anywhere;
    }

    .assessment-dot {
      flex: 0 0 auto;
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #94a3b8;
    }

    .assessment-dot.is-pass { background: #16a34a; }
    .assessment-dot.is-warn,
    .assessment-dot.is-pending { background: #d97706; }
    .assessment-dot.is-fail { background: #dc2626; }

    .assessment-improvements {
      padding-top: 14px;
      border-top: 1px solid var(--line);
    }

    .assessment-improvements h3 {
      margin: 0 0 8px;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.11em;
      color: var(--muted);
    }

    .assessment-improvements ul {
      margin: 0;
      padding-left: 18px;
      color: var(--ink);
      line-height: 1.45;
    }

    .fsm-monitor {
      --fsm-accent: #56d6c8;
      position: relative;
      overflow: hidden;
      margin-bottom: 28px;
      padding: 24px;
      border-radius: 24px;
      color: #f8fafc;
      background: #17201f;
      box-shadow: 0 18px 38px rgba(23, 32, 31, 0.18);
    }

    .fsm-monitor::before {
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 4px;
      background: var(--fsm-accent);
    }

    .fsm-monitor.has-guard { --fsm-accent: #fbbf24; }
    .fsm-monitor.is-terminal { --fsm-accent: #4ade80; }

    .fsm-head {
      display: grid;
      grid-template-columns: minmax(220px, 0.72fr) minmax(0, 1.28fr);
      gap: 30px;
      align-items: end;
      padding-bottom: 22px;
      border-bottom: 1px solid rgba(248, 250, 252, 0.12);
    }

    .fsm-kicker {
      margin: 0 0 8px;
      color: #a9b8b5;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }

    .fsm-phase {
      margin: 0;
      color: var(--fsm-accent);
      font-size: clamp(30px, 5vw, 48px);
      font-weight: 750;
      line-height: 0.96;
      letter-spacing: -0.045em;
      overflow-wrap: anywhere;
    }

    .fsm-facts {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px 22px;
    }

    .fsm-fact { min-width: 0; }

    .fsm-fact-label {
      display: block;
      margin-bottom: 5px;
      color: #8fa09d;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.13em;
      text-transform: uppercase;
    }

    .fsm-fact-value {
      display: block;
      color: #f8fafc;
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 13px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }

    .fsm-trail-head {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 16px;
      margin: 20px 0 10px;
    }

    .fsm-count {
      color: #8fa09d;
      font-size: 12px;
      font-variant-numeric: tabular-nums;
    }

    .fsm-timeline {
      display: grid;
      max-height: 260px;
      overflow: auto;
      scrollbar-color: rgba(255, 255, 255, 0.22) transparent;
    }

    .fsm-transition {
      display: grid;
      grid-template-columns: minmax(180px, 0.85fr) minmax(140px, 0.7fr) minmax(220px, 1.45fr) auto;
      gap: 18px;
      align-items: center;
      padding: 13px 0;
      border-top: 1px solid rgba(248, 250, 252, 0.09);
    }

    .fsm-route {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 12px;
    }

    .fsm-route-from { color: #8fa09d; }
    .fsm-route-arrow { color: var(--fsm-accent); }
    .fsm-route-to { color: #f8fafc; font-weight: 700; }

    .fsm-transition-copy { min-width: 0; }

    .fsm-transition-primary {
      color: #e8efed;
      font-size: 13px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }

    .fsm-transition-secondary {
      margin-top: 3px;
      color: #8fa09d;
      font-size: 11px;
      overflow-wrap: anywhere;
    }

    .fsm-evidence {
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: #64736f;
      box-shadow: 0 0 0 4px rgba(100, 115, 111, 0.12);
    }

    .fsm-evidence.is-recorded {
      background: var(--fsm-accent);
      box-shadow: 0 0 0 4px color-mix(in srgb, var(--fsm-accent) 18%, transparent);
    }

    .fsm-empty {
      padding: 24px 0 4px;
      color: #8fa09d;
      font-size: 14px;
    }

    .board {
      display: grid;
      gap: 18px;
    }

    .feed {
      display: grid;
      gap: 14px;
      max-height: 68vh;
      overflow: auto;
      padding-right: 6px;
    }

    .message {
      border-radius: var(--radius);
      border: 1px solid var(--line);
      padding: 16px 18px;
      background: rgba(255, 255, 255, 0.72);
    }

    .message.user {
      background: linear-gradient(180deg, rgba(29, 78, 216, 0.10), rgba(255, 255, 255, 0.78));
      border-color: rgba(29, 78, 216, 0.18);
    }

    .message.agent {
      background: linear-gradient(180deg, rgba(154, 52, 18, 0.10), rgba(255, 255, 255, 0.78));
      border-color: rgba(154, 52, 18, 0.18);
    }

    .message.live {
      border-style: dashed;
      animation: pulse 1.3s ease-in-out infinite;
    }

    .meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
    }

    .speaker {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--muted);
    }

    .badge {
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      background: rgba(32, 21, 12, 0.06);
      color: var(--muted);
    }

    .body {
      margin: 0;
      font-size: 18px;
      line-height: 1.55;
      white-space: pre-wrap;
    }

    .segments {
      display: grid;
      gap: 8px;
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
    }

    .segment {
      display: grid;
      gap: 4px;
      padding-left: 12px;
      border-left: 3px solid rgba(29, 78, 216, 0.22);
    }

    .segment-meta {
      font-size: 12px;
      color: var(--muted);
    }

    .empty {
      padding: 28px;
      border-radius: var(--radius);
      border: 1px dashed var(--line);
      color: var(--muted);
      text-align: center;
    }

    @keyframes pulse {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(-1px); }
    }

    @media (prefers-reduced-motion: reduce) {
      .message.live { animation: none; }
    }

    @media (max-width: 880px) {
      .hero-layout {
        grid-template-columns: 1fr;
      }

      .overview-grid {
        grid-template-columns: 1fr;
      }

      .call-assessment { grid-template-columns: 1fr; }
      .assessment-evidence { grid-template-columns: 1fr; }

      .fsm-head,
      .fsm-transition {
        grid-template-columns: 1fr;
      }

      .fsm-facts { grid-template-columns: 1fr 1fr; }
      .fsm-transition { gap: 7px; }
      .fsm-evidence { display: none; }
    }

    /* 2026 operational-console visual system. Presentation only. */
    :root {
      color-scheme: dark;
      --bg: #070a0d;
      --panel: #0d1116;
      --panel-raised: #11171d;
      --line: rgba(226, 232, 240, 0.10);
      --line-strong: rgba(226, 232, 240, 0.17);
      --ink: #f4f7f9;
      --muted: #8a98a6;
      --accent: #4de2c5;
      --accent-soft: rgba(77, 226, 197, 0.10);
      --user: #79a7ff;
      --user-soft: rgba(121, 167, 255, 0.09);
      --agent: #4de2c5;
      --agent-soft: rgba(77, 226, 197, 0.08);
      --shadow: 0 28px 80px rgba(0, 0, 0, 0.34);
      --radius: 14px;
    }

    html { background: var(--bg); }

    body {
      font-family: Inter, "SF Pro Display", "Segoe UI", sans-serif;
      letter-spacing: -0.01em;
      background:
        linear-gradient(rgba(255, 255, 255, 0.018) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255, 255, 255, 0.018) 1px, transparent 1px),
        radial-gradient(circle at 88% -8%, rgba(77, 226, 197, 0.11), transparent 31rem),
        var(--bg);
      background-size: 32px 32px, 32px 32px, auto, auto;
    }

    .shell {
      width: min(1440px, calc(100vw - 48px));
      margin: 0 auto;
      padding: 38px 0 64px;
      border: 0;
      border-radius: 0;
      background: transparent;
      backdrop-filter: none;
      box-shadow: none;
      animation: console-enter 520ms cubic-bezier(.2,.8,.2,1) both;
    }

    .hero {
      margin-bottom: 28px;
      padding-bottom: 28px;
      border-bottom: 1px solid var(--line);
    }

    .hero-layout {
      grid-template-columns: minmax(0, 1.45fr) minmax(300px, 0.55fr);
      gap: clamp(32px, 6vw, 96px);
      align-items: end;
    }

    .hero-copy { gap: 12px; }

    .eyebrow,
    .detail-title,
    .status-label,
    .assessment-kicker,
    .fsm-kicker,
    .metric-title {
      color: var(--muted);
      font-weight: 700;
      letter-spacing: 0.13em;
    }

    .eyebrow::before {
      content: "";
      display: inline-block;
      width: 7px;
      height: 7px;
      margin-right: 9px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 18px rgba(77, 226, 197, 0.65);
    }

    h1 {
      max-width: none;
      font-size: clamp(42px, 6vw, 78px);
      font-weight: 620;
      line-height: 0.94;
      letter-spacing: -0.065em;
    }

    .subhead {
      max-width: 66ch;
      color: #a9b4be;
      font-size: 15px;
      line-height: 1.6;
    }

    .detail-card,
    .status-card,
    .metric-card,
    .message,
    .assessment-check {
      border-color: var(--line);
      background: transparent;
      box-shadow: none;
    }

    .hero-card {
      min-height: auto !important;
      padding: 0 0 2px 28px;
      border: 0;
      border-left: 1px solid var(--line-strong);
      border-radius: 0;
      background: transparent;
    }

    .hero-card::after { display: none; }

    .hero-card-title {
      margin-bottom: 14px;
      font-size: clamp(22px, 3vw, 32px);
      font-weight: 580;
    }

    .hero-pill-list,
    .tech-list { gap: 7px; }

    .hero-pill,
    .tech-pill {
      padding: 7px 10px;
      border: 1px solid var(--line);
      border-radius: 5px;
      color: #b9c4cd;
      background: rgba(255, 255, 255, 0.025);
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 11px;
      font-weight: 600;
    }

    .status-grid {
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 0;
      margin: 0 0 28px;
      border-block: 1px solid var(--line);
    }

    .status-card {
      min-width: 0;
      padding: 17px 20px;
      border: 0;
      border-right: 1px solid var(--line);
      border-radius: 0;
    }

    .status-card:last-child { border-right: 0; }

    .status-label { margin-bottom: 9px; font-size: 10px; }

    .status-value {
      max-width: 100%;
      padding: 0;
      color: #dce3e8;
      background: none;
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 13px;
      overflow-wrap: anywhere;
    }

    .status-value::before {
      content: "";
      width: 6px;
      height: 6px;
      flex: 0 0 auto;
      border-radius: 50%;
      background: #66727e;
    }

    .status-value.is-speaking,
    .status-value.is-thinking { background: none; }
    .status-value.is-speaking { color: var(--accent); }
    .status-value.is-thinking { color: #f4c86a; }
    .status-value.is-speaking::before { background: var(--accent); box-shadow: 0 0 12px var(--accent); }
    .status-value.is-thinking::before { background: #f4c86a; }

    .call-assessment {
      grid-template-columns: minmax(250px, .72fr) minmax(0, 1.28fr);
      gap: 40px;
      margin-bottom: 28px;
      padding: 28px 30px;
      border: 1px solid var(--line);
      border-left: 2px solid var(--assessment-accent);
      border-radius: 12px;
      background: linear-gradient(90deg, var(--assessment-soft), transparent 42%), var(--panel);
      box-shadow: var(--shadow);
    }

    .assessment-verdict {
      font-size: clamp(30px, 4vw, 46px);
      font-weight: 620;
      letter-spacing: -0.055em;
    }

    .assessment-summary { color: #9eabb6; font-size: 14px; }
    .assessment-evidence { gap: 0; }

    .assessment-check {
      padding: 5px 16px;
      border: 0;
      border-left: 1px solid var(--line);
      border-radius: 0;
    }

    .assessment-check:first-child { border-left: 0; padding-left: 0; }
    .assessment-check-label { font-size: 9px; }
    .assessment-check-value { color: #e5ebef; font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; }

    .fsm-monitor {
      margin-bottom: 28px;
      padding: 30px;
      border: 1px solid rgba(77, 226, 197, 0.16);
      border-radius: 12px;
      color: var(--ink);
      background: #0a1113;
      box-shadow: 0 24px 70px rgba(0, 0, 0, 0.30), inset 0 1px 0 rgba(255,255,255,.025);
    }

    .fsm-monitor::before { width: 2px; }
    .fsm-head { align-items: start; }
    .fsm-phase { font-weight: 600; }
    .fsm-fact-value, .fsm-route, .fsm-transition-primary { color: #dfe8e7; }
    .fsm-transition { transition: background-color 160ms ease; }
    .fsm-transition:hover { background: rgba(255, 255, 255, 0.025); }

    .overview-grid {
      gap: 0;
      margin-bottom: 32px;
      border-block: 1px solid var(--line);
    }

    .overview-grid .detail-card {
      padding: 24px 28px 26px 0;
      border: 0;
      border-radius: 0;
    }

    .overview-grid .detail-card + .detail-card {
      padding-left: 28px;
      border-left: 1px solid var(--line);
    }

    .model-row {
      padding: 10px 0;
      border: 0;
      border-top: 1px solid var(--line);
      border-radius: 0;
      background: transparent;
    }

    .model-row:first-child { border-top: 0; }

    .metrics-section { margin-bottom: 36px; }
    .metrics-grid { gap: 0; border-block: 1px solid var(--line); }

    .metric-card {
      padding: 22px;
      border: 0;
      border-right: 1px solid var(--line);
      border-radius: 0;
    }

    .metric-card:last-child { border-right: 0; }
    .metric-row { border-color: var(--line); }
    .metric-value { color: #e7ecef; font-family: "SFMono-Regular", Consolas, monospace; font-weight: 600; }

    .board {
      padding-top: 2px;
      border-top: 1px solid var(--line);
    }

    .board::before {
      content: "Live transcript";
      padding: 22px 0 4px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .13em;
      text-transform: uppercase;
    }

    .feed { gap: 0; max-height: 72vh; padding-right: 10px; }

    .message {
      position: relative;
      padding: 22px 20px 22px 30px;
      border: 0;
      border-bottom: 1px solid var(--line);
      border-radius: 0;
      background: transparent !important;
      transition: background-color 160ms ease;
    }

    .message:hover { background: rgba(255, 255, 255, .018) !important; }

    .message::before {
      content: "";
      position: absolute;
      left: 5px;
      top: 28px;
      width: 7px;
      height: 7px;
      border-radius: 2px;
      background: var(--agent);
    }

    .message.user::before { background: var(--user); }
    .speaker { color: #aab5be; font-weight: 700; }
    .badge { padding: 4px 7px; border: 1px solid var(--line); border-radius: 4px; background: transparent; font-size: 10px; }
    .body { max-width: 86ch; color: #e4eaee; font-size: 16px; line-height: 1.65; }
    .empty { border-color: var(--line); border-radius: 8px; background: rgba(255,255,255,.012); }

    :focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 3px;
    }

    @keyframes console-enter {
      from { opacity: 0; transform: translateY(10px); }
      to { opacity: 1; transform: translateY(0); }
    }

    @media (max-width: 880px) {
      .shell { width: min(100% - 28px, 1440px); padding-top: 24px; }
      .hero-layout { gap: 28px; }
      .hero-card { padding: 20px 0 0; border-left: 0; border-top: 1px solid var(--line); }
      .status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .status-card:nth-child(2) { border-right: 0; }
      .status-card:nth-child(-n+2) { border-bottom: 1px solid var(--line); }
      .call-assessment { gap: 26px; padding: 24px; }
      .assessment-check { padding: 10px 0; border-left: 0; border-top: 1px solid var(--line); }
      .assessment-check:first-child { border-top: 0; }
      .fsm-monitor { padding: 24px; }
      .overview-grid .detail-card,
      .overview-grid .detail-card + .detail-card { padding: 22px 0; border-left: 0; }
      .overview-grid .detail-card + .detail-card { border-top: 1px solid var(--line); }
      .metrics-grid { grid-template-columns: 1fr; }
      .metric-card { border-right: 0; border-bottom: 1px solid var(--line); }
      .metric-card:last-child { border-bottom: 0; }
    }

    @media (prefers-reduced-motion: reduce) {
      .shell { animation: none; }
      *, *::before, *::after { scroll-behavior: auto !important; transition-duration: 0.01ms !important; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <div class="hero-layout">
        <div class="hero-copy">
          <p class="eyebrow">Console Transcript</p>
          <h1>Voice Agent Live View</h1>
          <p class="subhead">This page mirrors the console conversation so you can follow the exchange outside the terminal. User diarization appears when each utterance finishes; agent text streams while it is generated.</p>
        </div>

        <article class="detail-card hero-card">
          <h2 id="hero-card-title" class="hero-card-title"></h2>
          <div id="hero-pill-list" class="hero-pill-list">
            <span class="hero-pill">Javier Castro</span>
            <span class="hero-pill">DNAI</span>
            <span class="hero-pill">2026</span>
          </div>
        </article>
      </div>
    </section>

    <section id="call-assessment" class="call-assessment is-in_progress" aria-live="polite">
      <div>
        <p class="assessment-kicker">End-of-call assessment</p>
        <h2 id="assessment-verdict" class="assessment-verdict">Call in progress</h2>
        <p id="assessment-summary" class="assessment-summary">The FSM has not reached its terminal state yet.</p>
      </div>
      <div class="assessment-detail">
        <div id="assessment-evidence" class="assessment-evidence">
          <div class="assessment-check">
            <span class="assessment-check-label">FSM terminal</span>
            <span class="assessment-check-value"><span class="assessment-dot is-pending"></span>active</span>
          </div>
          <div class="assessment-check">
            <span class="assessment-check-label">Response evidence</span>
            <span class="assessment-check-value"><span class="assessment-dot is-pending"></span>0/0</span>
          </div>
          <div class="assessment-check">
            <span class="assessment-check-label">FSM adherence</span>
            <span class="assessment-check-value"><span class="assessment-dot is-pending"></span>not evaluated</span>
          </div>
          <div class="assessment-check">
            <span class="assessment-check-label">Conversation quality</span>
            <span class="assessment-check-value"><span class="assessment-dot is-pending"></span>not evaluated</span>
          </div>
        </div>
        <div id="assessment-improvements" class="assessment-improvements" hidden>
          <h3 id="assessment-improvements-title">Improvement opportunities</h3>
          <ul id="assessment-improvement-list"></ul>
        </div>
      </div>
    </section>

    <section class="status-grid">
      <article class="status-card">
        <span class="status-label">User State</span>
        <span id="user-state" class="status-value">listening</span>
      </article>
      <article class="status-card">
        <span class="status-label">Agent State</span>
        <span id="agent-state" class="status-value">initializing</span>
      </article>
      <article class="status-card">
        <span class="status-label">Barge-in</span>
        <span id="barge-in-state" class="status-value">monitoring</span>
      </article>
      <article class="status-card">
        <span class="status-label">Refresh</span>
        <span class="status-value">350 ms</span>
      </article>
    </section>

    <section id="fsm-monitor" class="fsm-monitor" aria-live="polite">
      <div class="fsm-head">
        <div>
          <p class="fsm-kicker">External FSM · current phase</p>
          <h2 id="fsm-phase" class="fsm-phase">awaiting start</h2>
        </div>
        <div class="fsm-facts">
          <div class="fsm-fact">
            <span class="fsm-fact-label">Latest intent</span>
            <span id="fsm-intent" class="fsm-fact-value">none</span>
          </div>
          <div class="fsm-fact">
            <span class="fsm-fact-label">Directive</span>
            <span id="fsm-directive" class="fsm-fact-value">waiting_for_fsm</span>
          </div>
          <div class="fsm-fact">
            <span class="fsm-fact-label">Guard</span>
            <span id="fsm-guard" class="fsm-fact-value">clear</span>
          </div>
          <div class="fsm-fact">
            <span class="fsm-fact-label">Outcome</span>
            <span id="fsm-outcome" class="fsm-fact-value">identity pending · active</span>
          </div>
        </div>
      </div>
      <div class="fsm-trail-head">
        <p class="fsm-kicker">Transition evidence</p>
        <span id="fsm-count" class="fsm-count">0 transitions</span>
      </div>
      <div id="fsm-timeline" class="fsm-timeline">
        <div class="fsm-empty">The first FSM transition will appear when the call starts.</div>
      </div>
    </section>

    <section class="overview-grid">
      <article id="models-card" class="detail-card">
        <p class="detail-title">Current Models</p>
        <div id="model-list" class="model-list">
          <div class="empty">Model metadata will appear here once the session starts.</div>
        </div>
      </article>

      <article id="technology-card" class="detail-card">
        <p class="detail-title">Technology</p>
        <div id="technology-list" class="tech-list">
          <div class="empty">Technology metadata will appear here once the session starts.</div>
        </div>
      </article>
    </section>

    <section class="metrics-section">
      <p class="detail-title">Live Metrics</p>
      <div id="metrics-grid" class="metrics-grid">
        <div class="empty">Latency and timing metrics will appear here once the session starts.</div>
      </div>
    </section>

    <section class="board">
      <div id="feed" class="feed">
        <div class="empty">The transcript will appear here once the session starts.</div>
      </div>
    </section>
  </main>

  <script>
    const feed = document.getElementById("feed");
    let lastFingerprint = "";
    let lastFsmFingerprint = "";
    let lastAssessmentFingerprint = "";

    function escapeHtml(value) {
      return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
    }

    function stateClass(value) {
      if (value === "speaking") return "status-value is-speaking";
      if (value === "thinking") return "status-value is-thinking";
      if (value === "candidate" || value === "interrupted") return "status-value is-speaking";
      if (value === "false_interruption" || value === "false_interruption_resumed") return "status-value is-thinking";
      return "status-value";
    }

    function renderState(targetId, value) {
      const node = document.getElementById(targetId);
      node.className = stateClass(value);
      node.textContent = value;
    }

    function renderModels(models) {
      const modelList = document.getElementById("model-list");
      if (!Array.isArray(models) || !models.length) {
        modelList.innerHTML = '<div class="empty">Model metadata will appear here once the session starts.</div>';
        return;
      }

      modelList.innerHTML = models.map((model) => `
        <div class="model-row">
          <span class="model-name">${escapeHtml(model.label)}</span>
          <span class="model-value">${escapeHtml(model.value)}</span>
        </div>
      `).join("");
    }

    function renderHeroCard(heroCard) {
      const titleNode = document.getElementById("hero-card-title");
      const listNode = document.getElementById("hero-pill-list");
      const title = heroCard && heroCard.title ? heroCard.title : "";
      const items = Array.isArray(heroCard && heroCard.items) && heroCard.items.length
        ? heroCard.items
        : ["Javier Castro", "DNAI", "2026"];

      titleNode.textContent = title;
      titleNode.style.display = title ? "block" : "none";
      listNode.innerHTML = items.map((item) => `
        <span class="hero-pill">${escapeHtml(item)}</span>
      `).join("");
    }

    function renderTechnologies(technologies) {
      const techList = document.getElementById("technology-list");
      if (!Array.isArray(technologies) || !technologies.length) {
        techList.innerHTML = '<div class="empty">Technology metadata will appear here once the session starts.</div>';
        return;
      }

      techList.innerHTML = technologies.map((technology) => `
        <span class="tech-pill">${escapeHtml(technology)}</span>
      `).join("");
    }

    function renderMetrics(metrics) {
      const metricsGrid = document.getElementById("metrics-grid");
      if (!Array.isArray(metrics) || !metrics.length) {
        metricsGrid.innerHTML = '<div class="empty">Latency and timing metrics will appear here once the session starts.</div>';
        return;
      }

      metricsGrid.innerHTML = metrics.map((panel) => `
        <article class="metric-card">
          <p class="metric-title">${escapeHtml(panel.title || panel.id || "Metrics")}</p>
          <div class="metric-list">${(Array.isArray(panel.items) ? panel.items : []).map((item) => `
            <div class="metric-row">
              <span class="metric-label">${escapeHtml(item.label || "")}</span>
              <span class="metric-value">${escapeHtml(item.value || "")}</span>
            </div>
          `).join("")}</div>
        </article>
      `).join("");
    }

    function displayToken(value, fallback = "—") {
      const token = String(value ?? "").trim();
      return token || fallback;
    }

    function displayPhase(value) {
      return displayToken(value, "awaiting start").replaceAll("_", " ");
    }

    function renderAssessment(assessment) {
      const value = assessment || {};
      const fingerprint = JSON.stringify(value);
      if (fingerprint === lastAssessmentFingerprint) return;
      lastAssessmentFingerprint = fingerprint;

      const status = displayToken(value.status, "in_progress");
      document.getElementById("call-assessment").className = `call-assessment is-${status}`;
      document.getElementById("assessment-verdict").textContent = displayToken(value.label, "Call in progress");
      document.getElementById("assessment-summary").textContent = displayToken(
        value.summary,
        "The FSM has not reached its terminal state yet.",
      );

      const evidence = Array.isArray(value.evidence) ? value.evidence : [];
      document.getElementById("assessment-evidence").innerHTML = evidence.map((item) => {
        const itemStatus = displayToken(item.status, "pending");
        return `
          <div class="assessment-check">
            <span class="assessment-check-label">${escapeHtml(displayToken(item.label, "Check"))}</span>
            <span class="assessment-check-value">
              <span class="assessment-dot is-${escapeHtml(itemStatus)}"></span>
              ${escapeHtml(displayToken(item.value))}
            </span>
          </div>
        `;
      }).join("");

      const improvements = Array.isArray(value.improvements) ? value.improvements : [];
      const improvementPanel = document.getElementById("assessment-improvements");
      improvementPanel.hidden = improvements.length === 0;
      document.getElementById("assessment-improvements-title").textContent = (
        status === "pass" ? "Assessment notes" : "Improvement opportunities"
      );
      document.getElementById("assessment-improvement-list").innerHTML = improvements
        .map((item) => `<li>${escapeHtml(displayToken(item))}</li>`)
        .join("");
    }

    function renderFSM(fsmState, transitions) {
      const state = fsmState || {};
      const trail = Array.isArray(transitions) ? transitions : [];
      const fsmFingerprint = JSON.stringify(state) + JSON.stringify(trail);
      if (fsmFingerprint === lastFsmFingerprint) return;
      lastFsmFingerprint = fsmFingerprint;

      const monitor = document.getElementById("fsm-monitor");
      const guard = displayToken(state.guard_reason, "clear");
      const terminal = Boolean(state.should_end);

      monitor.className = `fsm-monitor${guard !== "clear" ? " has-guard" : ""}${terminal ? " is-terminal" : ""}`;

      document.getElementById("fsm-phase").textContent = displayPhase(state.phase);
      document.getElementById("fsm-intent").textContent = displayToken(state.intent, "none");
      document.getElementById("fsm-directive").textContent = displayToken(state.directive, "waiting_for_fsm");
      document.getElementById("fsm-guard").textContent = guard;

      const identity = state.identity_verified ? "identity verified" : "identity pending";
      const resolution = state.resolution_type ? ` · ${displayToken(state.resolution_type)}` : "";
      const refusals = Number(state.refusal_count || 0) ? ` · refusals ${Number(state.refusal_count)}` : "";
      document.getElementById("fsm-outcome").textContent = `${identity}${resolution}${refusals} · ${terminal ? "terminal" : "active"}`;
      document.getElementById("fsm-count").textContent = `${trail.length} transition${trail.length === 1 ? "" : "s"}`;

      const timeline = document.getElementById("fsm-timeline");
      if (!trail.length) {
        timeline.innerHTML = '<div class="fsm-empty">The first FSM transition will appear when the call starts.</div>';
        return;
      }

      const wasAtBottom = timeline.scrollTop + timeline.clientHeight >= timeline.scrollHeight - 32;
      timeline.innerHTML = trail.map((item) => `
        <div class="fsm-transition">
          <div class="fsm-route">
            <span class="fsm-route-from">${escapeHtml(displayPhase(item.from_phase))}</span>
            <span class="fsm-route-arrow">→</span>
            <span class="fsm-route-to">${escapeHtml(displayPhase(item.to_phase))}</span>
          </div>
          <div class="fsm-transition-copy">
            <div class="fsm-transition-primary">${escapeHtml(displayToken(item.intent))}</div>
            <div class="fsm-transition-secondary">${escapeHtml(displayToken(item.interpreter, "deterministic FSM"))}</div>
          </div>
          <div class="fsm-transition-copy">
            <div class="fsm-transition-primary">${escapeHtml(displayToken(item.directive))}</div>
            <div class="fsm-transition-secondary">${escapeHtml(displayToken(item.guard_reason, item.should_end ? "terminal" : "guard clear"))}</div>
          </div>
          <span class="fsm-evidence${item.response_recorded || item.response_disposition === "coalesced" ? " is-recorded" : ""}" title="${item.response_recorded ? "Assistant response recorded" : item.response_disposition === "coalesced" ? "Turn coalesced into the next user turn" : "Awaiting assistant response"}"></span>
        </div>
      `).join("");
      if (wasAtBottom || trail.length <= 4) timeline.scrollTop = timeline.scrollHeight;
    }

    function renderMessage(message, live = false) {
      const segments = Array.isArray(message.segments) && message.segments.length
        ? `<div class="segments">${message.segments.map((segment) => `
            <div class="segment">
              <div class="segment-meta">${escapeHtml(segment.speaker)} · ${Number(segment.start).toFixed(1)}s to ${Number(segment.end).toFixed(1)}s</div>
              <div>${escapeHtml(segment.text)}</div>
            </div>
          `).join("")}</div>`
        : "";

      return `
        <article class="message ${escapeHtml(message.role)} ${live ? "live" : ""}">
          <div class="meta">
            <span class="speaker">${escapeHtml(message.speaker || (message.role === "agent" ? "Agent" : "You"))}</span>
            <span class="badge">${live ? "live" : "final"}</span>
          </div>
          <p class="body">${escapeHtml(message.text)}</p>
          ${segments}
        </article>
      `;
    }

    function buildLiveMessages(state) {
      const items = [];

      const liveUserText = state.live_user_text || (state.user_state === "speaking" ? "[speaking...]" : "");
      if (liveUserText) {
        items.push({
          role: "user",
          speaker: state.live_user_speaker || "You",
          text: liveUserText,
          segments: [],
          live: true,
        });
      }

      const liveAgentText = state.live_agent_text || "";
      if (liveAgentText) {
        items.push({
          role: "agent",
          speaker: "Agent",
          text: liveAgentText,
          segments: [],
          live: true,
        });
      } else if (state.agent_state === "thinking") {
        items.push({
          role: "agent",
          speaker: "Agent",
          text: "[thinking...]",
          segments: [],
          live: true,
        });
      }

      return items;
    }

    function render(state) {
      renderState("user-state", state.user_state);
      renderState("agent-state", state.agent_state);
      renderState("barge-in-state", (state.barge_in_state && state.barge_in_state.state) || "monitoring");
      renderModels(state.models);
      renderMetrics(state.metrics);
      renderHeroCard(state.hero_card);
      renderTechnologies(state.technologies);
      renderAssessment(state.call_assessment);
      renderFSM(state.fsm_state, state.fsm_transitions);

      const messages = [...state.messages, ...buildLiveMessages(state)];
      const fingerprint = JSON.stringify(messages) + state.user_state + state.agent_state + JSON.stringify(state.barge_in_state) + JSON.stringify(state.models) + JSON.stringify(state.metrics) + JSON.stringify(state.hero_card) + JSON.stringify(state.technologies) + JSON.stringify(state.fsm_state) + JSON.stringify(state.fsm_transitions);
      if (fingerprint === lastFingerprint) {
        return;
      }
      lastFingerprint = fingerprint;

      if (!messages.length) {
        feed.innerHTML = '<div class="empty">The transcript will appear here once the session starts.</div>';
        return;
      }

      const stickToBottom = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 40;
      feed.innerHTML = messages.map((message) => renderMessage(message, Boolean(message.live))).join("");
      if (stickToBottom) {
        feed.scrollTop = feed.scrollHeight;
      }
    }

    async function tick() {
      try {
        const response = await fetch("/api/state", { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        render(await response.json());
      } catch (error) {
        feed.innerHTML = `<div class="empty">Live view unavailable: ${escapeHtml(String(error))}</div>`;
      } finally {
        setTimeout(tick, 350);
      }
    }

    tick();
  </script>
</body>
</html>
"""
