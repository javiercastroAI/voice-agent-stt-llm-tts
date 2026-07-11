"""Local transcript web UI for console mode."""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Lock, Thread

from .call_assessment import assess_call
from .conversation_fsm import (
    CaseContext,
    dashboard_graph_spec,
    evaluate_transition_structure,
)
from .diarized_stt import DiarizedTranscript
from .response_compliance import evaluate_spoken_response

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
            "transition_id": None,
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
        self._fsm_adherence: dict[str, object] = {
            "status": "pending",
            "reason": "Awaiting the first FSM transition.",
            "evaluated": 0,
        }
        self._spoken_compliance: dict[str, object] = {
            "status": "pending",
            "reason": "Awaiting the first assistant response.",
            "evaluated": 0,
            "required": 0,
        }
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
                structural = evaluate_transition_structure(
                    transition_id=str(event.get("transitionId", "") or ""),
                    from_phase=str(event.get("fromPhase", "")),
                    to_phase=str(event.get("toPhase", "")),
                    should_end=bool(event.get("shouldEnd", False)),
                )
                transition = {
                    "turn_id": turn_id,
                    "transition_id": str(event.get("transitionId", "") or ""),
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
                    "assistant_text": "",
                    "fsm_status": structural["status"],
                    "fsm_reason": structural["reason"],
                    "spoken_status": "pending",
                    "spoken_reason": "Awaiting assistant response.",
                }
                self._fsm_transitions.append(transition)
                self._fsm_transitions = self._fsm_transitions[-100:]
                self._fsm_state = {
                    "phase": transition["to_phase"],
                    "transition_id": transition["transition_id"],
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
                        assistant_text = str(event.get("assistantText", "") or "").strip()
                        spoken = evaluate_spoken_response(
                            transition,
                            assistant_text,
                            case=self._adherence_case,
                        )
                        transition["response_recorded"] = True
                        transition["response_disposition"] = "recorded"
                        transition["assistant_text"] = assistant_text
                        transition["spoken_status"] = spoken["status"]
                        transition["spoken_reason"] = spoken["reason"]
                        break
            elif event_type == "turn_superseded" and turn_id:
                for transition in reversed(self._fsm_transitions):
                    if transition["turn_id"] == turn_id:
                        transition["response_disposition"] = "coalesced"
                        transition["spoken_status"] = "coalesced"
                        transition["spoken_reason"] = (
                            "Turn was coalesced before a response was required."
                        )
                        break
            self._refresh_compliance_locked()
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
                "fsm_graph": dashboard_graph_spec(),
                "fsm_adherence": dict(self._fsm_adherence),
                "spoken_compliance": dict(self._spoken_compliance),
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

    def _refresh_compliance_locked(self) -> None:
        structural_failures = [
            item for item in self._fsm_transitions if item.get("fsm_status") == "fail"
        ]
        if structural_failures:
            structural = structural_failures[-1]
            self._fsm_adherence = {
                "status": "fail",
                "reason": str(structural.get("fsm_reason") or "FSM route mismatch."),
                "evaluated": len(self._fsm_transitions),
            }
        elif self._fsm_transitions:
            self._fsm_adherence = {
                "status": "pass",
                "reason": "Every observed transition matches the executable FSM registry.",
                "evaluated": len(self._fsm_transitions),
            }

        required = [
            item
            for item in self._fsm_transitions
            if item.get("response_disposition") != "coalesced"
        ]
        failures = [item for item in required if item.get("spoken_status") == "fail"]
        evaluated = sum(
            item.get("spoken_status") in {"pass", "fail"} for item in required
        )
        if failures:
            latest = failures[-1]
            status = "fail"
            reason = str(latest.get("spoken_reason") or "Spoken response mismatch.")
        elif required and evaluated == len(required):
            status = "pass"
            reason = "Every recorded response complies with its FSM directive."
        else:
            status = "pending"
            reason = "One or more responses are pending or incomplete."
        self._spoken_compliance = {
            "status": status,
            "reason": reason,
            "evaluated": evaluated,
            "required": len(required),
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
  <title>Externally Orchestrated Voice Agent · Live Console</title>
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

    .fsm-graph-panel {
      margin: 22px 0 18px;
      padding: 18px 0;
      border-top: 1px solid rgba(248, 250, 252, 0.12);
      border-bottom: 1px solid rgba(248, 250, 252, 0.12);
    }

    .fsm-graph-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 10px;
    }

    .fsm-graph-status {
      margin: 0;
      color: #8fa09d;
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 11px;
      line-height: 1.45;
    }

    .fsm-verdicts {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 8px;
    }

    .fsm-verdict {
      padding: 5px 8px;
      border: 1px solid rgba(192, 211, 206, 0.32);
      border-radius: 999px;
      color: #cddbd7;
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    .fsm-verdict.is-pass {
      border-color: rgba(74, 222, 128, 0.56);
      color: #8ce7ae;
    }

    .fsm-verdict.is-fail {
      border-color: rgba(248, 113, 113, 0.68);
      color: #fca5a5;
    }

    .fsm-verdict.is-pending { color: #a9b8b5; }

    .fsm-graph-status {
      max-width: 56ch;
    }

    .fsm-graph {
      display: block;
      width: 100%;
      height: auto;
    }

    .fsm-graph-edge {
      fill: none;
      stroke: rgba(192, 211, 206, 0.34);
      stroke-width: 1.6;
    }

    .fsm-graph-edge.is-global { stroke-dasharray: 4 4; }

    .fsm-graph-edge.is-active {
      stroke: var(--fsm-accent);
      stroke-width: 3;
      stroke-dasharray: none;
    }

    .fsm-graph-edge.is-runtime {
      stroke: var(--fsm-accent);
      stroke-width: 3;
      stroke-dasharray: 6 4;
    }

    .fsm-graph-edge.is-structural-fail { stroke: #f87171; }

    .fsm-graph-speech rect {
      fill: #2a3533;
      stroke: rgba(192, 211, 206, 0.48);
    }

    .fsm-graph-speech text {
      fill: #cddbd7;
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 10px;
      font-weight: 700;
      text-anchor: middle;
    }

    .fsm-graph-speech.is-pass rect { stroke: rgba(74, 222, 128, 0.72); }
    .fsm-graph-speech.is-pass text { fill: #8ce7ae; }
    .fsm-graph-speech.is-fail rect { stroke: rgba(248, 113, 113, 0.82); }
    .fsm-graph-speech.is-fail text { fill: #fca5a5; }

    .fsm-graph-node rect {
      fill: rgba(248, 250, 252, 0.04);
      stroke: rgba(192, 211, 206, 0.38);
      stroke-width: 1.2;
    }

    .fsm-graph-node text {
      fill: #cddbd7;
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 11px;
      font-weight: 700;
      text-anchor: middle;
    }

    .fsm-graph-node.is-traversed rect {
      fill: rgba(86, 214, 200, 0.12);
      stroke: rgba(86, 214, 200, 0.66);
    }

    .fsm-graph-node.is-current rect {
      fill: var(--fsm-accent);
      stroke: var(--fsm-accent);
      stroke-width: 2;
    }

    .fsm-graph-node.is-current text { fill: #17201f; }

    .fsm-graph-node.is-terminal rect {
      stroke: rgba(117, 223, 163, 0.8);
      stroke-width: 1.5;
    }

    .fsm-graph-node.is-global rect {
      fill: rgba(251, 191, 36, 0.08);
      stroke: rgba(251, 191, 36, 0.58);
      stroke-dasharray: 4 3;
    }

    .fsm-graph-node.is-global text {
      fill: #f7cf70;
      font-size: 10px;
    }

    .fsm-timeline {
      display: grid;
      max-height: 260px;
      overflow: auto;
      scrollbar-color: rgba(255, 255, 255, 0.22) transparent;
    }

    .fsm-transition {
      display: grid;
      grid-template-columns: minmax(180px, 0.85fr) minmax(140px, 0.7fr) minmax(220px, 1.45fr) minmax(92px, auto);
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

    .fsm-transition-status {
      display: grid;
      justify-items: end;
      gap: 5px;
    }

    .fsm-spoken-badge {
      color: #a9b8b5;
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
    }

    .fsm-spoken-badge.is-pass { color: #8ce7ae; }
    .fsm-spoken-badge.is-fail { color: #fca5a5; }

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

    /* Refined light operational-console visual system. Presentation only. */
    :root {
      color-scheme: light;
      --bg: #f3f1eb;
      --panel: #faf9f5;
      --panel-raised: #ffffff;
      --line: rgba(37, 43, 39, 0.11);
      --line-strong: rgba(37, 43, 39, 0.18);
      --ink: #202521;
      --muted: #737c75;
      --accent: #176b5b;
      --accent-soft: rgba(23, 107, 91, 0.09);
      --user: #416b9d;
      --user-soft: rgba(65, 107, 157, 0.08);
      --agent: #176b5b;
      --agent-soft: rgba(23, 107, 91, 0.07);
      --shadow: 0 24px 68px rgba(47, 52, 45, 0.09);
      --radius: 14px;
    }

    html { background: var(--bg); }

    body {
      font-family: Inter, "SF Pro Display", "Segoe UI", sans-serif;
      letter-spacing: -0.01em;
      background:
        linear-gradient(rgba(32, 37, 33, 0.018) 1px, transparent 1px),
        linear-gradient(90deg, rgba(32, 37, 33, 0.018) 1px, transparent 1px),
        radial-gradient(circle at 88% -8%, rgba(23, 107, 91, 0.10), transparent 31rem),
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
      box-shadow: 0 0 14px rgba(23, 107, 91, 0.30);
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
      color: #626c65;
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
      color: #535d56;
      background: rgba(255, 255, 255, 0.42);
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 11px;
      font-weight: 600;
    }

    .hero-pill-list { align-items: center; }

    .hero-pill:first-child {
      flex-basis: 100%;
      padding: 0 0 10px;
      border: 0;
      color: var(--ink);
      background: transparent;
      font-family: Inter, "SF Pro Display", "Segoe UI", sans-serif;
      font-size: clamp(27px, 3vw, 38px);
      font-weight: 650;
      line-height: 1;
      letter-spacing: -.045em;
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
      color: #38413a;
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

    .assessment-summary { color: #687169; font-size: 14px; }
    .assessment-evidence { gap: 0; }

    .assessment-check {
      padding: 5px 16px;
      border: 0;
      border-left: 1px solid var(--line);
      border-radius: 0;
    }

    .assessment-check:first-child { border-left: 0; padding-left: 0; }
    .assessment-check-label { font-size: 9px; }
    .assessment-check-value { color: #343c36; font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; }

    .fsm-monitor {
      --fsm-accent: #176b5b;
      margin-bottom: 28px;
      padding: 30px;
      border: 1px solid rgba(23, 107, 91, 0.18);
      border-radius: 12px;
      color: var(--ink);
      background: #e9efea;
      box-shadow: 0 22px 60px rgba(55, 67, 58, 0.10), inset 0 1px 0 rgba(255,255,255,.70);
    }

    .fsm-monitor::before { width: 2px; }
    .fsm-monitor.has-guard { --fsm-accent: #9b6a20; }
    .fsm-monitor.is-terminal { --fsm-accent: #237a4b; }
    .fsm-head { align-items: start; }
    .fsm-phase { font-weight: 600; }
    .fsm-kicker,
    .fsm-count,
    .fsm-fact-label,
    .fsm-route-from,
    .fsm-transition-secondary,
    .fsm-empty { color: #68756b; }
    .fsm-fact-value, .fsm-route, .fsm-transition-primary, .fsm-route-to { color: #26332b; }
    .fsm-head,
    .fsm-transition { border-color: rgba(38, 51, 43, 0.12); }
    .fsm-transition { transition: background-color 160ms ease; }
    .fsm-transition:hover { background: rgba(255, 255, 255, 0.34); }
    .fsm-graph-panel { border-color: rgba(38, 51, 43, 0.12); }
    .fsm-graph-status { color: #68756b; }
    .fsm-verdict { border-color: rgba(38, 51, 43, 0.20); color: #526158; }
    .fsm-verdict.is-pass { border-color: rgba(35, 122, 75, 0.42); color: #237a4b; }
    .fsm-verdict.is-fail { border-color: rgba(176, 55, 55, 0.46); color: #a33535; }
    .fsm-graph-edge { stroke: rgba(38, 51, 43, 0.28); }
    .fsm-graph-node rect { fill: rgba(255, 255, 255, 0.38); stroke: rgba(38, 51, 43, 0.28); }
    .fsm-graph-node text { fill: #435048; }
    .fsm-graph-node.is-current text { fill: #f7fbf8; }
    .fsm-graph-node.is-global rect { fill: rgba(155, 106, 32, 0.08); stroke: rgba(155, 106, 32, 0.48); }
    .fsm-graph-node.is-global text { fill: #82591e; }
    .fsm-graph-speech rect { fill: #f7faf7; stroke: rgba(38, 51, 43, 0.28); }
    .fsm-graph-speech text { fill: #526158; }
    .fsm-graph-speech.is-pass rect { stroke: rgba(35, 122, 75, 0.58); }
    .fsm-graph-speech.is-pass text { fill: #237a4b; }
    .fsm-graph-speech.is-fail rect { stroke: rgba(176, 55, 55, 0.62); }
    .fsm-graph-speech.is-fail text,
    .fsm-spoken-badge.is-fail { color: #a33535; fill: #a33535; }
    .fsm-spoken-badge.is-pass { color: #237a4b; }

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

    .detail-title {
      color: #454f47;
      font-size: 13px;
      font-weight: 750;
      letter-spacing: .105em;
    }

    .assessment-kicker,
    .fsm-kicker {
      font-size: 12px;
      font-weight: 750;
      letter-spacing: .13em;
    }

    .metrics-section {
      gap: 9px;
      margin-bottom: 32px;
    }

    .metrics-section > .detail-title {
      display: flex;
      align-items: center;
      gap: 10px;
      margin: 0;
      color: #283029;
      font-size: 16px;
      letter-spacing: .09em;
    }

    .metrics-section > .detail-title::after {
      content: "continuous telemetry";
      padding-left: 10px;
      border-left: 1px solid var(--line-strong);
      color: #919991;
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 9px;
      font-weight: 500;
      letter-spacing: .04em;
      text-transform: lowercase;
    }

    .metrics-grid {
      grid-template-columns: 1fr;
      gap: 1px;
      padding: 1px;
      border: 0;
      background: var(--line);
    }

    .metric-card {
      min-width: 0;
      padding: 13px 16px;
      border: 0;
      border-radius: 0;
      background: var(--panel);
    }

    .metric-title {
      display: flex;
      align-items: center;
      gap: 7px;
      margin-bottom: 9px;
      color: #354038;
      font-size: 12px;
      font-weight: 800;
      letter-spacing: .105em;
      line-height: 1.2;
    }

    .metric-title::before {
      content: "";
      width: 5px;
      height: 5px;
      flex: 0 0 auto;
      border-radius: 50%;
      background: var(--accent);
      opacity: .72;
    }

    .metric-card--pipeline {
      display: grid;
      grid-template-columns: minmax(128px, .55fr) minmax(0, 3.45fr);
      gap: 18px;
      align-items: stretch;
    }

    .metric-card--pipeline .metric-title {
      align-self: center;
      margin: 0;
    }

    .metric-card--pipeline .metric-list {
      display: grid;
      grid-template-columns: repeat(var(--metric-count), minmax(0, 1fr));
      gap: 0;
      min-width: 0;
    }

    .metric-card--pipeline .metric-row {
      display: grid;
      grid-template-columns: 1fr;
      align-content: center;
      justify-items: start;
      gap: 9px;
      min-height: 62px;
      padding: 5px 16px;
      border-top: 0;
      border-left: 1px solid var(--line);
    }

    .metric-card--pipeline .metric-label {
      color: #677168;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: .065em;
      line-height: 1.2;
      text-transform: uppercase;
    }

    .metric-card--pipeline .metric-value {
      color: #202923;
      font-size: clamp(17px, 1.5vw, 21px);
      font-weight: 700;
      line-height: 1;
    }

    .metric-card--barge-in {
      padding: 17px 18px 16px;
      background: #f6f7f3;
    }

    .metric-card--barge-in .metric-title {
      margin: 0 0 14px;
      padding-bottom: 13px;
      border-bottom: 1px solid var(--line);
      font-size: 14px;
    }

    .metric-card--barge-in .metric-list {
      display: block;
      column-count: 4;
      column-gap: 32px;
      column-rule: 1px solid var(--line);
    }

    .metric-row {
      min-height: 27px;
      gap: 8px;
      padding: 6px 0 5px;
      border-color: var(--line);
      transition: color 140ms ease, background-color 140ms ease;
    }

    .metric-row:hover {
      background: rgba(23, 107, 91, .045);
    }

    .metric-card--barge-in .metric-row {
      break-inside: avoid;
      margin: 0 9px;
      min-height: 34px;
      padding: 8px 5px 7px;
    }

    .metric-card--barge-in .metric-row:first-child {
      padding-top: 6px;
      border-top: 1px solid var(--line);
    }

    .metric-label {
      min-width: 0;
      color: #717a73;
      font-size: 12px;
      font-weight: 600;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }

    .metric-value {
      flex: 0 0 auto;
      color: #303832;
      font-family: "SFMono-Regular", Consolas, monospace;
      font-size: 14px;
      font-weight: 700;
      line-height: 1.25;
      white-space: nowrap;
    }

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

    .message:hover { background: rgba(255, 255, 255, .30) !important; }

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
    .speaker { color: #667168; font-weight: 700; }
    .badge { padding: 4px 7px; border: 1px solid var(--line); border-radius: 4px; background: transparent; font-size: 10px; }
    .body { max-width: 86ch; color: #2d342f; font-size: 16px; line-height: 1.65; }
    .empty { border-color: var(--line); border-radius: 8px; background: rgba(255,255,255,.24); }

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
      .metric-card { border: 0; }
      .metric-card--pipeline {
        grid-template-columns: 112px minmax(0, 1fr);
        gap: 10px;
      }
      .metric-card--pipeline .metric-list {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .metric-card--pipeline .metric-row:nth-child(odd) { border-left: 1px solid var(--line); }
      .metric-card--pipeline .metric-row:nth-child(n+3) { border-top: 1px solid var(--line); }
      .metric-card--barge-in .metric-list { column-count: 2; }
    }

    @media (min-width: 881px) and (max-width: 1160px) {
      .metric-card--barge-in .metric-list { column-count: 3; }
    }

    @media (max-width: 560px) {
      .fsm-graph-head { align-items: flex-start; flex-direction: column; }
      .fsm-verdicts { justify-content: flex-start; }
      .metrics-section > .detail-title::after { display: none; }
      .metric-card--pipeline {
        grid-template-columns: 1fr;
        gap: 7px;
      }
      .metric-card--pipeline .metric-title { padding: 2px 4px 7px; }
      .metric-card--pipeline .metric-row:first-child { border-left: 0; }
      .metric-card--barge-in .metric-list { column-count: 1; }
      .metric-card--barge-in .metric-row { margin-inline: 0; }
    }

    @media (prefers-reduced-motion: reduce) {
      .shell { animation: none; }
      *, *::before, *::after { scroll-behavior: auto !important; transition-duration: 0.01ms !important; }
    }

    /* 0063 · Conversation control room. Final visual layer. */
    :root {
      color-scheme: dark;
      --bg: #0b0f0d;
      --panel: #101512;
      --panel-raised: #151b17;
      --line: rgba(239, 235, 222, 0.11);
      --line-strong: rgba(239, 235, 222, 0.19);
      --ink: #f1eee5;
      --muted: #929b94;
      --accent: #57e8cb;
      --accent-soft: rgba(87, 232, 203, 0.10);
      --warning: #e4b765;
      --danger: #ff7777;
      --user: #b7c9ff;
      --agent: #57e8cb;
      --radius: 10px;
      --mono: "SFMono-Regular", "Cascadia Code", Consolas, monospace;
      --sans: Inter, "SF Pro Display", "Avenir Next", "Segoe UI", sans-serif;
    }

    html {
      background: var(--bg);
      scroll-behavior: smooth;
    }

    body {
      min-width: 0;
      color: var(--ink);
      background-color: var(--bg);
      background-image:
        linear-gradient(rgba(239, 235, 222, 0.018) 1px, transparent 1px),
        linear-gradient(90deg, rgba(239, 235, 222, 0.018) 1px, transparent 1px);
      background-size: 40px 40px;
      font-family: var(--sans);
    }

    .skip-link {
      position: fixed;
      z-index: 100;
      top: 10px;
      left: 10px;
      padding: 10px 14px;
      color: #07100d;
      background: var(--accent);
      transform: translateY(-160%);
    }

    .skip-link:focus { transform: translateY(0); }

    .command-header {
      --command-header-height: 84px;
      position: sticky;
      z-index: 20;
      top: 0;
      display: grid;
      grid-template-columns: minmax(280px, 1fr) auto auto auto;
      align-items: center;
      min-height: var(--command-header-height);
      padding: 12px clamp(18px, 2vw, 34px);
      border-bottom: 1px solid var(--line-strong);
      background: rgba(11, 15, 13, 0.96);
    }

    .brand-lockup {
      display: flex;
      align-items: center;
      gap: 13px;
      min-width: 0;
    }

    .brand-signal {
      position: relative;
      width: 28px;
      height: 28px;
      flex: 0 0 auto;
      border: 1px solid rgba(87, 232, 203, 0.44);
      border-radius: 50%;
    }

    .brand-signal::before,
    .brand-signal::after {
      content: "";
      position: absolute;
      top: 50%;
      background: var(--accent);
      transform: translateY(-50%);
    }

    .brand-signal::before { left: 6px; width: 14px; height: 1px; }
    .brand-signal::after { left: 12px; width: 3px; height: 3px; border-radius: 50%; }

    .product-kicker,
    .panel-kicker,
    .evidence-kicker {
      margin: 0 0 4px;
      color: var(--muted);
      font-family: var(--mono);
      font-size: 9px;
      font-weight: 650;
      letter-spacing: 0.16em;
      line-height: 1;
      text-transform: uppercase;
    }

    .product-name {
      margin: 0;
      overflow: hidden;
      color: var(--ink);
      font-size: clamp(14px, 1.45vw, 19px);
      font-weight: 610;
      letter-spacing: -0.025em;
      line-height: 1.15;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .header-provenance {
      justify-self: end;
      min-width: 124px;
      padding-left: 22px;
      border-left: 1px solid var(--line);
      text-align: right;
    }

    .header-provenance .hero-card-title { display: none !important; }

    .header-provenance .hero-pill-list {
      display: grid;
      gap: 1px;
    }

    .header-provenance .hero-pill {
      display: block;
      padding: 0;
      border: 0;
      border-radius: 0;
      color: #9da69f;
      background: transparent;
      font-family: var(--mono);
      font-size: 9px;
      font-weight: 650;
      letter-spacing: 0.04em;
      line-height: 1.25;
    }

    .header-provenance .hero-pill:first-child {
      color: var(--ink);
      font-family: var(--sans);
      font-size: 11px;
      font-weight: 720;
      letter-spacing: -0.01em;
    }

    .connection-block {
      display: flex;
      align-items: center;
      gap: 16px;
      margin-right: 24px;
      padding-right: 24px;
      border-right: 1px solid var(--line);
      font-family: var(--mono);
      font-size: 10px;
      color: var(--muted);
    }

    .connection-state {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      color: var(--accent);
      text-transform: uppercase;
    }

    .connection-state::before {
      content: "";
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: currentColor;
      box-shadow: 0 0 0 4px rgba(87, 232, 203, 0.08);
    }

    .connection-state.is-offline { color: var(--danger); }

    .status-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(100px, auto));
      gap: 0;
      margin: 0;
      border: 0;
    }

    .status-card {
      min-width: 0;
      padding: 2px 18px;
      border: 0;
      border-left: 1px solid var(--line);
      background: transparent;
    }

    .status-card:last-child { border-right: 0; }
    .status-label { margin-bottom: 6px; font-size: 8px; }

    .status-value {
      gap: 7px;
      padding: 0;
      color: #c4cbc5;
      background: transparent !important;
      font-family: var(--mono);
      font-size: 10px;
      font-weight: 650;
      line-height: 1.2;
      text-transform: uppercase;
    }

    .status-value::before {
      width: 5px;
      height: 5px;
      background: #68716b;
    }

    .status-value.is-speaking { color: var(--accent); }
    .status-value.is-thinking { color: var(--warning); }
    .status-value.is-speaking::before { animation: presence-pulse 1.2s ease-out infinite; }
    .status-value.is-thinking::before { animation: thinking-pulse 1.4s ease-in-out infinite; }

    .shell {
      width: 100%;
      margin: 0;
      padding: 0;
      border: 0;
      background: transparent;
      box-shadow: none;
      animation: console-enter 420ms cubic-bezier(.2,.8,.2,1) both;
    }

    .workspace {
      display: grid;
      grid-template-columns: minmax(310px, 0.72fr) minmax(620px, 1.28fr);
      gap: 1px;
      height: calc(100svh - var(--command-header-height));
      min-height: calc(100svh - var(--command-header-height));
      padding: clamp(14px, 1.5vw, 24px);
      background: var(--line);
      background-clip: content-box;
    }

    .transcript-panel,
    .fsm-monitor {
      min-width: 0;
      height: 100%;
      min-height: 0;
      max-height: none;
    }

    .transcript-panel {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      overflow: hidden;
      padding: 24px 22px 18px;
      background: var(--panel);
    }

    .panel-head {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 16px;
      padding: 0 4px 19px;
      border-bottom: 1px solid var(--line);
    }

    .panel-title {
      margin: 0;
      color: var(--ink);
      font-size: clamp(22px, 2.6vw, 34px);
      font-weight: 570;
      letter-spacing: -0.045em;
      line-height: 1;
    }

    .panel-mode {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      color: var(--muted);
      font-family: var(--mono);
      font-size: 9px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .panel-mode::before {
      content: "";
      width: 5px;
      height: 5px;
      border-radius: 50%;
      background: var(--accent);
    }

    .board {
      min-height: 0;
      overflow: hidden;
      padding: 0;
      border: 0;
    }

    .board::before { display: none; }

    .feed {
      height: 100%;
      max-height: none;
      gap: 0;
      overflow-y: auto;
      padding: 7px 8px 16px 0;
    }

    .message {
      position: relative;
      padding: 20px 12px 22px 28px;
      border: 0;
      border-bottom: 1px solid var(--line);
      border-radius: 0;
      color: var(--ink);
      background: transparent !important;
      transition: background-color 180ms ease, border-color 180ms ease;
    }

    .message::before {
      left: 5px;
      top: 25px;
      width: 7px;
      height: 1px;
      border-radius: 0;
      background: var(--agent);
    }

    .message.user::before { background: var(--user); }
    .message:hover { background: rgba(239, 235, 222, 0.025) !important; }
    .message.live { border-style: solid; animation: none; }

    .message.live::after {
      content: "";
      display: inline-block;
      width: 6px;
      height: 1em;
      margin-left: 5px;
      vertical-align: -0.13em;
      background: var(--accent);
      animation: live-cursor 900ms steps(1, end) infinite;
    }

    .meta { margin-bottom: 9px; }
    .speaker { color: #aab2ac; font-family: var(--mono); font-size: 9px; font-weight: 700; }
    .badge { padding: 0; border: 0; color: #666f69; background: none; font-family: var(--mono); font-size: 8px; }
    .body { max-width: 64ch; color: #e6e3da; font-size: 15px; line-height: 1.62; }
    .message.user .body { color: #e0e5ef; }

    .segments {
      gap: 7px;
      margin-top: 13px;
      padding-top: 12px;
      border-color: var(--line);
    }

    .segment { border-left: 1px solid rgba(183, 201, 255, 0.34); color: #c4cbc6; font-size: 12px; }
    .segment-meta { color: #77817a; font-family: var(--mono); font-size: 9px; }

    .fsm-monitor {
      --fsm-accent: var(--accent);
      display: grid;
      grid-template-rows: auto minmax(250px, 1fr) auto minmax(120px, 0.42fr);
      gap: 0;
      overflow: hidden;
      margin: 0;
      padding: 24px 28px 18px;
      border: 0;
      border-radius: 0;
      color: var(--ink);
      background: var(--panel-raised);
      box-shadow: none;
    }

    .fsm-monitor::before { display: none; }
    .fsm-monitor.has-guard { --fsm-accent: var(--warning); }
    .fsm-monitor.is-terminal { --fsm-accent: var(--accent); }

    .fsm-head {
      display: block;
      padding-bottom: 18px;
      border-color: var(--line);
    }

    .fsm-phase-line {
      display: flex;
      align-items: flex-end;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 18px;
    }

    .fsm-phase {
      color: var(--fsm-accent);
      font-size: clamp(29px, 3.5vw, 48px);
      font-weight: 560;
      letter-spacing: -0.05em;
      line-height: 0.95;
    }

    .fsm-outcome {
      max-width: 38ch;
      color: var(--muted);
      font-family: var(--mono);
      font-size: 9px;
      line-height: 1.5;
      text-align: right;
    }

    .causal-chain {
      display: grid;
      grid-template-columns: 0.9fr 0.75fr 1fr 1.65fr;
      border-block: 1px solid var(--line);
    }

    .causal-link {
      min-width: 0;
      padding: 11px 13px 12px;
      border-left: 1px solid var(--line);
    }

    .causal-link:first-child { padding-left: 0; border-left: 0; }
    .causal-link:last-child { padding-right: 0; }

    .fsm-fact-label {
      margin-bottom: 5px;
      color: #6f7972;
      font-family: var(--mono);
      font-size: 8px;
    }

    .fsm-fact-value {
      overflow: hidden;
      color: #d9ddd7;
      font-family: var(--mono);
      font-size: 10px;
      line-height: 1.35;
      text-overflow: ellipsis;
    }

    .fsm-monitor.has-guard #fsm-guard { color: var(--warning); }
    .fsm-graph-panel {
      display: flex;
      min-height: 0;
      flex-direction: column;
      justify-content: center;
      overflow: hidden;
      margin: 0;
      padding: 12px 0 8px;
      border-color: var(--line);
    }

    .fsm-graph-head { margin-bottom: 0; }
    .fsm-kicker { color: #818a83; font-family: var(--mono); font-size: 9px; }
    .fsm-graph-status { color: #6f7872; font-size: 9px; }
    .fsm-verdicts { gap: 5px; }

    .fsm-verdict {
      padding: 4px 7px;
      border-color: var(--line-strong);
      border-radius: 3px;
      color: #8e9790;
      font-family: var(--mono);
      font-size: 8px;
    }

    .fsm-verdict.is-pass { border-color: rgba(87, 232, 203, 0.38); color: var(--accent); }
    .fsm-verdict.is-fail { border-color: rgba(255, 119, 119, 0.44); color: var(--danger); }

    .fsm-graph { width: 100%; max-height: 100%; }
    .fsm-graph-edge { stroke: rgba(218, 225, 218, 0.20); stroke-width: 1.25; }
    .fsm-graph-edge.is-global { stroke: rgba(228, 183, 101, 0.38); }
    .fsm-graph-edge.is-active,
    .fsm-graph-edge.is-runtime {
      stroke: var(--fsm-accent);
      stroke-width: 2.6;
      stroke-dasharray: 9 7;
      animation: signal-flow 880ms linear infinite;
    }

    .fsm-graph-edge.is-structural-fail { stroke: var(--danger); }
    .fsm-graph-node rect { fill: #121814; stroke: rgba(218, 225, 218, 0.24); rx: 4px; }
    .fsm-graph-node text { fill: #9ca69f; font-size: 10px; }
    .fsm-graph-node.is-traversed rect { fill: rgba(87, 232, 203, 0.055); stroke: rgba(87, 232, 203, 0.42); }
    .fsm-graph-node.is-current rect { fill: var(--fsm-accent); stroke: var(--fsm-accent); }
    .fsm-graph-node.is-current text { fill: #07100d; }
    .fsm-graph-node.is-terminal rect { stroke: rgba(87, 232, 203, 0.55); }
    .fsm-graph-node.is-global rect { fill: rgba(228, 183, 101, 0.05); stroke: rgba(228, 183, 101, 0.46); }
    .fsm-graph-node.is-global text { fill: var(--warning); }
    .fsm-graph-speech rect { fill: #111713; stroke: var(--line-strong); rx: 3px; }
    .fsm-graph-speech text { fill: #aeb6b0; font-size: 9px; }
    .fsm-graph-speech.is-pass rect { stroke: rgba(87, 232, 203, 0.55); }
    .fsm-graph-speech.is-pass text { fill: var(--accent); }
    .fsm-graph-speech.is-fail rect { stroke: rgba(255, 119, 119, 0.66); }
    .fsm-graph-speech.is-fail text { fill: var(--danger); }
    .fsm-mobile-map { display: none; }

    .fsm-trail-head { margin: 14px 0 5px; }
    .fsm-count { color: #68716b; font-family: var(--mono); font-size: 9px; }
    .fsm-timeline { min-height: 0; max-height: none; overflow-y: auto; }

    .fsm-transition {
      grid-template-columns: minmax(155px, .8fr) minmax(120px, .65fr) minmax(210px, 1.45fr) auto;
      gap: 14px;
      padding: 9px 4px;
      border-color: var(--line);
    }

    .fsm-transition:last-child { background: rgba(87, 232, 203, 0.035); }
    .fsm-route { color: #aab2ac; font-size: 9px; }
    .fsm-route-from { color: #707a73; }
    .fsm-route-arrow { color: var(--fsm-accent); }
    .fsm-route-to { color: #cbd1cc; }
    .fsm-transition-primary { color: #cbd1cc; font-family: var(--mono); font-size: 9px; }
    .fsm-transition-secondary { color: #68716b; font-family: var(--mono); font-size: 8px; }
    .fsm-spoken-badge { color: #727c75; font-size: 8px; }
    .fsm-spoken-badge.is-pass { color: var(--accent); }
    .fsm-spoken-badge.is-fail { color: var(--danger); }
    .fsm-evidence { width: 5px; height: 5px; box-shadow: none; }
    .fsm-evidence.is-recorded { background: var(--accent); box-shadow: none; }
    .fsm-empty { padding: 16px 0; color: #68716b; font-family: var(--mono); font-size: 10px; }

    .secondary-workspace {
      padding: clamp(26px, 4vw, 56px) clamp(18px, 3vw, 48px) 70px;
      border-top: 1px solid var(--line-strong);
      background: #0d110f;
    }

    .secondary-head {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 20px;
      margin-bottom: 28px;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--line);
    }

    .secondary-title { margin: 0; font-size: clamp(25px, 3vw, 38px); font-weight: 560; letter-spacing: -0.045em; }
    .secondary-copy { max-width: 48ch; margin: 0; color: var(--muted); font-size: 12px; line-height: 1.55; text-align: right; }

    .call-assessment {
      grid-template-columns: minmax(230px, .75fr) minmax(0, 1.25fr);
      gap: 34px;
      margin: 0 0 30px;
      padding: 21px 22px;
      border: 1px solid var(--line);
      border-left: 2px solid var(--assessment-accent);
      border-radius: var(--radius);
      color: var(--ink);
      background: var(--panel);
      box-shadow: none;
      transition: padding 260ms ease, border-color 260ms ease, background-color 260ms ease;
    }

    .call-assessment:not(.is-in_progress) { animation: terminal-settle 440ms cubic-bezier(.2,.8,.2,1) both; }
    .call-assessment.is-pass {
      --assessment-accent: var(--accent);
      --assessment-soft: rgba(87, 232, 203, 0.06);
    }
    .call-assessment.is-warn,
    .call-assessment.is-finalizing {
      --assessment-accent: var(--warning);
      --assessment-soft: rgba(228, 183, 101, 0.06);
    }
    .call-assessment.is-fail {
      --assessment-accent: var(--danger);
      --assessment-soft: rgba(255, 119, 119, 0.06);
    }
    .assessment-kicker { color: var(--muted); font-size: 9px; }
    .assessment-verdict { color: var(--assessment-accent); font-size: clamp(24px, 3vw, 36px); font-weight: 580; }
    .assessment-summary { color: #8f9891; font-size: 12px; }
    .assessment-evidence { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .assessment-check { padding: 3px 13px; border-color: var(--line); background: transparent; }
    .assessment-check-label { color: #717a73; font-size: 8px; }
    .assessment-check-value { color: #cbd1cc; font-family: var(--mono); font-size: 9px; }
    .assessment-dot { width: 5px; height: 5px; }
    .assessment-dot.is-pass { background: var(--accent); }
    .assessment-dot.is-warn,
    .assessment-dot.is-pending { background: var(--warning); }
    .assessment-dot.is-fail { background: var(--danger); }

    .metrics-section { gap: 12px; margin-bottom: 30px; }
    .metrics-section > .detail-title { color: var(--ink); font-size: 12px; }
    .metrics-section > .detail-title::after { color: #616a64; border-color: var(--line); }
    .metrics-grid { gap: 1px; padding: 1px; background: var(--line); }
    .metric-card { background: var(--panel); }
    .metric-title { color: #c8cec9; }
    .metric-title::before { background: var(--accent); }
    .metric-card--pipeline .metric-row { border-color: var(--line); }
    .metric-card--pipeline .metric-label,
    .metric-label { color: #778079; }
    .metric-card--pipeline .metric-value,
    .metric-value { color: #d8dcd7; font-family: var(--mono); }
    .metric-card--barge-in { background: #111612; }
    .metric-card--barge-in .metric-title,
    .metric-card--barge-in .metric-list { border-color: var(--line); column-rule-color: var(--line); }
    .metric-row:hover { background: rgba(87, 232, 203, 0.035); }

    .overview-grid {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 0;
      margin: 0;
      border-color: var(--line);
    }

    .overview-grid .detail-card,
    .overview-grid .detail-card + .detail-card {
      padding: 24px 28px;
      border: 0;
      border-left: 1px solid var(--line);
      border-radius: 0;
      color: var(--ink);
      background: transparent;
    }

    .overview-grid .detail-card:first-child { padding-left: 0; border-left: 0; }
    .detail-title { color: #9fa7a1; font-family: var(--mono); font-size: 9px; }
    .model-row { border-color: var(--line); background: transparent; }
    .model-name { color: #707a73; font-size: 9px; }
    .model-value { color: #cbd1cc; font-family: var(--mono); font-size: 10px; }
    .tech-pill,
    .hero-pill {
      padding: 5px 7px;
      border-color: var(--line);
      border-radius: 3px;
      color: #939c95;
      background: transparent;
      font-size: 9px;
    }

    .research-meta .hero-pill:first-child {
      flex-basis: 100%;
      padding: 0 0 7px;
      color: #d7dbd6;
      font-family: var(--sans);
      font-size: 15px;
      font-weight: 560;
      letter-spacing: -0.02em;
    }

    .empty {
      border-color: var(--line);
      border-radius: 5px;
      color: #68716b;
      background: rgba(239, 235, 222, 0.012);
      font-family: var(--mono);
      font-size: 10px;
    }

    .workspace.is-synchronized .causal-chain {
      animation: causal-flash 640ms ease-out both;
    }

    .workspace.is-synchronized .message.user:not(.live):last-of-type {
      background: rgba(183, 201, 255, 0.045) !important;
      border-color: rgba(183, 201, 255, 0.25);
    }

    :focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }

    @keyframes signal-flow { to { stroke-dashoffset: -32; } }
    @keyframes live-cursor { 0%, 48% { opacity: 1; } 49%, 100% { opacity: 0; } }
    @keyframes presence-pulse {
      0% { box-shadow: 0 0 0 0 rgba(87, 232, 203, .32); }
      100% { box-shadow: 0 0 0 6px rgba(87, 232, 203, 0); }
    }
    @keyframes thinking-pulse { 0%, 100% { opacity: .45; } 50% { opacity: 1; } }
    @keyframes causal-flash {
      0% { background: rgba(87, 232, 203, .09); }
      100% { background: transparent; }
    }
    @keyframes terminal-settle {
      from { opacity: .45; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }

    @media (max-width: 1100px) {
      .command-header { grid-template-columns: minmax(240px, 1fr) auto auto; }
      .connection-block { margin-right: 0; padding-right: 0; border-right: 0; }
      .status-grid { grid-column: 1 / -1; margin-top: 12px; border-top: 1px solid var(--line); }
      .status-card { padding-top: 10px; }
      .workspace { grid-template-columns: 1fr; height: auto; background: transparent; }
      .fsm-monitor { order: 1; }
      .transcript-panel { order: 2; }
      .transcript-panel,
      .fsm-monitor { height: auto; min-height: 640px; max-height: none; border: 1px solid var(--line); }
      .transcript-panel { min-height: 560px; }
      .overview-grid { grid-template-columns: 1fr 1fr; }
    }

    @media (max-width: 700px) {
      .command-header { position: relative; min-height: auto; padding: 14px; }
      .brand-signal { width: 24px; height: 24px; }
      .product-name { white-space: normal; }
      .header-provenance { min-width: 108px; padding-left: 12px; }
      .connection-block { grid-column: 1 / -1; align-self: start; margin-top: 10px; gap: 8px; font-size: 8px; }
      .refresh-label { display: none; }
      .status-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .status-card { padding: 10px 8px 2px; }
      .status-card:first-child { padding-left: 0; border-left: 0; }
      .status-label { font-size: 7px; }
      .status-value { font-size: 8px; }
      .workspace { gap: 12px; height: auto; min-height: 0; padding: 10px; }
      .transcript-panel,
      .fsm-monitor { min-height: 0; }
      .transcript-panel { height: 68svh; padding: 19px 15px 12px; }
      .fsm-monitor {
        display: block;
        height: auto;
        padding: 20px 15px;
      }
      .panel-head { padding-bottom: 15px; }
      .panel-title { font-size: 25px; }
      .panel-mode { font-size: 7px; }
      .fsm-phase-line { display: block; }
      .fsm-phase { margin-bottom: 10px; font-size: 34px; }
      .fsm-outcome { text-align: left; }
      .causal-chain { grid-template-columns: 1fr 1fr; }
      .causal-link { padding: 10px 9px; }
      .causal-link:nth-child(odd) { padding-left: 0; border-left: 0; }
      .causal-link:nth-child(n+3) { border-top: 1px solid var(--line); }
      .fsm-graph-panel { display: block; margin-top: 16px; padding: 14px 0; }
      .fsm-graph-head { display: block; }
      .fsm-verdicts { justify-content: flex-start; margin-top: 10px; }
      .fsm-graph { display: none; }
      .fsm-mobile-map {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 1px;
        margin: 16px 0 0;
        padding: 1px;
        list-style: none;
        background: var(--line);
      }
      .fsm-mobile-state {
        position: relative;
        min-width: 0;
        padding: 10px 9px 10px 21px;
        color: #8f9992;
        background: #111612;
        font-family: var(--mono);
        font-size: 8px;
        line-height: 1.3;
        overflow-wrap: anywhere;
      }
      .fsm-mobile-state::before {
        content: "";
        position: absolute;
        top: 13px;
        left: 9px;
        width: 4px;
        height: 4px;
        border-radius: 50%;
        background: #59625c;
      }
      .fsm-mobile-state.is-traversed { color: #b9c1bb; }
      .fsm-mobile-state.is-traversed::before { background: rgba(87, 232, 203, .55); }
      .fsm-mobile-state.is-current { color: #07100d; background: var(--fsm-accent); }
      .fsm-mobile-state.is-current::before { background: #07100d; }
      .fsm-trail-head { margin-top: 16px; }
      .fsm-timeline { max-height: 220px; }
      .fsm-transition { grid-template-columns: 1fr auto; gap: 5px 10px; padding: 10px 2px; }
      .fsm-transition-copy { grid-column: 1 / -1; }
      .fsm-transition-status { grid-column: 2; grid-row: 1; }
      .secondary-workspace { padding: 34px 14px 52px; }
      .secondary-head { display: block; }
      .secondary-copy { margin-top: 10px; text-align: left; }
      .call-assessment { grid-template-columns: 1fr; gap: 20px; padding: 18px; }
      .assessment-evidence { grid-template-columns: 1fr 1fr; }
      .assessment-check { padding: 8px 8px; border-top: 1px solid var(--line); border-left: 0; }
      .metric-card--pipeline { grid-template-columns: 1fr; }
      .metric-card--pipeline .metric-list { grid-template-columns: 1fr 1fr; }
      .metric-card--pipeline .metric-row { min-height: 56px; }
      .metric-card--barge-in .metric-list { column-count: 1; }
      .overview-grid { grid-template-columns: 1fr; }
      .overview-grid .detail-card,
      .overview-grid .detail-card + .detail-card {
        grid-column: auto;
        padding: 22px 0;
        border-left: 0;
        border-top: 1px solid var(--line);
      }
      .overview-grid .detail-card:first-child { border-top: 0; }
    }

    @media (prefers-reduced-motion: reduce) {
      html { scroll-behavior: auto; }
      .shell,
      .status-value::before,
      .message.live::after,
      .fsm-graph-edge,
      .call-assessment,
      .workspace.is-synchronized .causal-chain { animation: none !important; }
    }
  </style>
</head>
<body>
  <a class="skip-link" href="#live-workspace">Skip to live workspace</a>
  <header class="command-header">
    <div class="brand-lockup">
      <span class="brand-signal" aria-hidden="true"></span>
      <div>
        <p class="product-kicker">Deterministic conversation control</p>
        <h1 class="product-name">Externally Orchestrated Voice Agent</h1>
      </div>
    </div>

    <div class="connection-block" aria-label="Console connection">
      <span id="connection-state" class="connection-state">Live link</span>
      <span class="refresh-label">Refresh&nbsp; 350 ms</span>
    </div>

    <section class="status-grid" aria-label="Live session states">
      <article class="status-card">
        <span class="status-label">Caller</span>
        <span id="user-state" class="status-value">listening</span>
      </article>
      <article class="status-card">
        <span class="status-label">Agent</span>
        <span id="agent-state" class="status-value">initializing</span>
      </article>
      <article class="status-card">
        <span class="status-label">Barge-in</span>
        <span id="barge-in-state" class="status-value">monitoring</span>
      </article>
    </section>

    <aside class="header-provenance" aria-label="Research provenance">
      <p class="product-kicker">Research provenance</p>
      <span id="hero-card-title" class="hero-card-title" hidden></span>
      <div id="hero-pill-list" class="hero-pill-list">
        <span class="hero-pill">Javier Castro</span>
        <span class="hero-pill">DNAI</span>
        <span class="hero-pill">2026</span>
      </div>
    </aside>
  </header>

  <main class="shell">
    <section id="live-workspace" class="workspace" aria-label="Synchronized conversation and finite state machine">
      <section class="transcript-panel" aria-labelledby="transcript-title">
        <div class="panel-head">
          <div>
            <p class="panel-kicker">Probabilistic channel</p>
            <h2 id="transcript-title" class="panel-title">Conversation</h2>
          </div>
          <span class="panel-mode">Streaming evidence</span>
        </div>

        <section class="board" aria-label="Live transcript">
          <div id="feed" class="feed">
            <div class="empty">The transcript will appear here once the session starts.</div>
          </div>
        </section>
      </section>

      <section id="fsm-monitor" class="fsm-monitor" aria-live="polite" aria-labelledby="fsm-phase">
        <div class="fsm-head">
          <div class="fsm-phase-line">
            <div>
              <p class="fsm-kicker">Deterministic authority · current phase</p>
              <h2 id="fsm-phase" class="fsm-phase">awaiting start</h2>
            </div>
            <span id="fsm-outcome" class="fsm-outcome">identity pending · active</span>
          </div>

          <div class="causal-chain" aria-label="Latest deterministic causal chain">
            <div class="causal-link">
              <span class="fsm-fact-label">01 · Intent</span>
              <span id="fsm-intent" class="fsm-fact-value">none</span>
            </div>
            <div class="causal-link">
              <span class="fsm-fact-label">02 · Guard</span>
              <span id="fsm-guard" class="fsm-fact-value">clear</span>
            </div>
            <div class="causal-link">
              <span class="fsm-fact-label">03 · Transition</span>
              <span id="fsm-transition-id" class="fsm-fact-value">awaiting_transition</span>
            </div>
            <div class="causal-link">
              <span class="fsm-fact-label">04 · Directive</span>
              <span id="fsm-directive" class="fsm-fact-value">waiting_for_fsm</span>
            </div>
          </div>
        </div>

        <figure class="fsm-graph-panel" aria-labelledby="fsm-graph-label">
          <div class="fsm-graph-head">
            <div>
              <p id="fsm-graph-label" class="fsm-kicker">Canonical graph · live position</p>
              <p id="fsm-graph-status" class="fsm-graph-status">Awaiting the first FSM transition</p>
            </div>
            <div class="fsm-verdicts" aria-label="Live compliance verdicts">
              <span id="fsm-structural-status" class="fsm-verdict is-pending">FSM …</span>
              <span id="fsm-spoken-status" class="fsm-verdict is-pending">Speech …</span>
            </div>
          </div>
          <svg id="fsm-graph" class="fsm-graph" viewBox="0 0 1000 470" role="img" aria-labelledby="fsm-graph-label fsm-graph-status"></svg>
          <ol id="fsm-mobile-map" class="fsm-mobile-map" aria-label="Compact finite state machine phases"></ol>
        </figure>

        <div class="fsm-trail-head">
          <p class="fsm-kicker">Transition evidence</p>
          <span id="fsm-count" class="fsm-count">0 transitions</span>
        </div>
        <div id="fsm-timeline" class="fsm-timeline">
          <div class="fsm-empty">The first FSM transition will appear when the call starts.</div>
        </div>
      </section>
    </section>

    <section class="secondary-workspace" aria-labelledby="evidence-title">
      <div class="secondary-head">
        <div>
          <p class="evidence-kicker">Continuous evidence</p>
          <h2 id="evidence-title" class="secondary-title">Runtime instrumentation</h2>
        </div>
        <p class="secondary-copy">Latency, model configuration, response evidence, and terminal assessment remain observational; the FSM retains business authority.</p>
      </div>

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

      <section class="metrics-section" aria-labelledby="metrics-title">
        <p id="metrics-title" class="detail-title">Live metrics</p>
        <div id="metrics-grid" class="metrics-grid">
          <div class="empty">Latency and timing metrics will appear here once the session starts.</div>
        </div>
      </section>

      <section class="overview-grid" aria-label="Runtime configuration and provenance">
        <article id="models-card" class="detail-card">
          <p class="detail-title">Current models</p>
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
    </section>
  </main>

  <script>
    const feed = document.getElementById("feed");
    let lastFingerprint = "";
    let lastFsmFingerprint = "";
    let lastFsmGraphFingerprint = "";
    let lastAssessmentFingerprint = "";
    let lastTransitionCount = -1;

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

      metricsGrid.innerHTML = metrics.map((panel) => {
        const items = Array.isArray(panel.items) ? panel.items : [];
        const panelClass = panel.id === "barge_in"
          ? "metric-card metric-card--barge-in"
          : "metric-card metric-card--pipeline";
        return `
        <article class="${panelClass}" style="--metric-count: ${Math.max(items.length, 1)}">
          <p class="metric-title">${escapeHtml(panel.title || panel.id || "Metrics")}</p>
          <div class="metric-list">${items.map((item) => `
            <div class="metric-row">
              <span class="metric-label">${escapeHtml(item.label || "")}</span>
              <span class="metric-value">${escapeHtml(item.value || "")}</span>
            </div>
          `).join("")}</div>
        </article>
      `;
      }).join("");
    }

    function displayToken(value, fallback = "—") {
      const token = String(value ?? "").trim();
      return token || fallback;
    }

    function displayPhase(value) {
      return displayToken(value, "awaiting start").replaceAll("_", " ");
    }

    const fsmGraphLayout = {
      opening: { x: 78, y: 220 },
      identity_verification: { x: 208, y: 220 },
      case_disclosure: { x: 354, y: 104 },
      recognition: { x: 506, y: 104 },
      objection_handling: { x: 506, y: 336 },
      resolution: { x: 654, y: 220 },
      confirmation: { x: 802, y: 220 },
      escalation: { x: 802, y: 390 },
      ended: { x: 932, y: 220 },
      any_active_phase: { x: 380, y: 410 },
    };

    function graphNodeLines(label) {
      const words = displayPhase(label).split(" ");
      if (words.length < 2) return [words.join(" ")];
      const midpoint = Math.ceil(words.length / 2);
      return [words.slice(0, midpoint).join(" "), words.slice(midpoint).join(" ")];
    }

    function graphPath(source, target, routeIndex) {
      const origin = fsmGraphLayout[source];
      const destination = fsmGraphLayout[target];
      if (!origin || !destination) return "";
      const offset = ((routeIndex % 3) - 1) * 10;
      const direction = destination.x >= origin.x ? 1 : -1;
      const startX = origin.x + direction * 58;
      const endX = destination.x - direction * 58;
      const controlX = Math.max(36, Math.abs(endX - startX) * 0.42);
      return `M ${startX} ${origin.y + offset} C ${startX + direction * controlX} ${origin.y + offset}, ${endX - direction * controlX} ${destination.y + offset}, ${endX} ${destination.y + offset}`;
    }

    function runtimeGraphPath(source, target) {
      const origin = fsmGraphLayout[source];
      const destination = fsmGraphLayout[target];
      if (!origin || !destination) return "";
      if (source === target) {
        return `M ${origin.x - 28} ${origin.y - 20} C ${origin.x - 54} ${origin.y - 68}, ${origin.x + 54} ${origin.y - 68}, ${origin.x + 28} ${origin.y - 20}`;
      }
      return graphPath(source, target, 1);
    }

    function complianceMarkerPosition(source, target) {
      const origin = fsmGraphLayout[source];
      const destination = fsmGraphLayout[target];
      if (!origin || !destination) return null;
      if (source === target) return { x: origin.x, y: origin.y - 58 };
      return {
        x: (origin.x + destination.x) / 2,
        y: (origin.y + destination.y) / 2 - 16,
      };
    }

    function verdictSymbol(status) {
      if (status === "pass") return "✓";
      if (status === "fail") return "✕";
      return "…";
    }

    function renderVerdict(targetId, label, value) {
      const status = displayToken(value && value.status, "pending");
      const node = document.getElementById(targetId);
      node.className = `fsm-verdict is-${status === "pass" || status === "fail" ? status : "pending"}`;
      node.textContent = `${label} ${verdictSymbol(status)}`;
      node.setAttribute("title", displayToken(value && value.reason, `${label} evaluation pending`));
    }

    function renderFSMGraph(graph, fsmState, transitions, fsmAdherence, spokenCompliance) {
      const graphData = graph || {};
      const nodes = Array.isArray(graphData.nodes) ? graphData.nodes : [];
      const edges = Array.isArray(graphData.edges) ? graphData.edges : [];
      const state = fsmState || {};
      const trail = Array.isArray(transitions) ? transitions : [];
      const latest = trail.length ? trail[trail.length - 1] : {};
      const activeTransitionId = displayToken(state.transition_id || latest.transition_id, "");
      const currentPhase = displayToken(state.phase, "awaiting_start");
      const visitedPhases = new Set([currentPhase]);
      trail.forEach((item) => {
        if (item.from_phase) visitedPhases.add(item.from_phase);
        if (item.to_phase) visitedPhases.add(item.to_phase);
      });
      const graphFingerprint = JSON.stringify(graphData) + JSON.stringify({
        currentPhase,
        activeTransitionId,
        from: latest.from_phase,
        to: latest.to_phase,
        latestFsm: latest.fsm_status,
        latestSpeech: latest.spoken_status,
        fsmAdherence,
        spokenCompliance,
      });
      if (graphFingerprint === lastFsmGraphFingerprint) return;
      lastFsmGraphFingerprint = graphFingerprint;

      const graphNode = document.getElementById("fsm-graph");
      const statusNode = document.getElementById("fsm-graph-status");
      const activeFrom = displayToken(latest.from_phase, "");
      const activeTo = displayToken(latest.to_phase, "");
      const activeLabel = activeTransitionId
        ? `Latest transition: ${activeTransitionId.replaceAll("_", " ")}`
        : "Awaiting the first FSM transition";
      statusNode.textContent = currentPhase === "awaiting_start"
        ? activeLabel
        : `Current: ${displayPhase(currentPhase)} · ${activeLabel}`;
      renderVerdict("fsm-structural-status", "FSM", fsmAdherence);
      renderVerdict("fsm-spoken-status", "Speech", spokenCompliance);

      let activeEdgeRendered = false;
      let markerSource = activeFrom;
      let markerTarget = activeTo;
      const edgeMarkup = edges.map((edge, index) => {
        const transitionIds = Array.isArray(edge.transition_ids) ? edge.transition_ids : [];
        const isActive = transitionIds.includes(activeTransitionId)
          || (!activeTransitionId && edge.source === activeFrom && edge.target === activeTo);
        if (isActive) {
          activeEdgeRendered = true;
          markerSource = edge.source;
          markerTarget = edge.target;
        }
        const label = transitionIds.join(", ").replaceAll("_", " ");
        const structuralFailure = isActive && latest.fsm_status === "fail";
        return `<path class="fsm-graph-edge${edge.global ? " is-global" : ""}${isActive ? " is-active" : ""}${structuralFailure ? " is-structural-fail" : ""}" d="${graphPath(edge.source, edge.target, index)}" marker-end="url(#fsm-arrow)"><title>${escapeHtml(label)}</title></path>`;
      }).join("");

      const runtimePath = !activeEdgeRendered && activeFrom && activeTo
        ? runtimeGraphPath(activeFrom, activeTo)
        : "";
      const runtimeEdge = runtimePath
        ? `<path class="fsm-graph-edge is-runtime${latest.fsm_status === "fail" ? " is-structural-fail" : ""}" d="${runtimePath}" marker-end="url(#fsm-arrow)"><title>${escapeHtml(activeLabel)}</title></path>`
        : "";

      const marker = complianceMarkerPosition(markerSource, markerTarget);
      const spokenStatus = displayToken(latest.spoken_status, "pending");
      const spokenClass = spokenStatus === "pass" || spokenStatus === "fail"
        ? spokenStatus
        : "pending";
      const spokenReason = displayToken(latest.spoken_reason, "Spoken response pending");
      const spokenMarker = marker && activeTransitionId
        ? `<g class="fsm-graph-speech is-${spokenClass}" transform="translate(${marker.x} ${marker.y})"><title>${escapeHtml(spokenReason)}</title><rect x="-38" y="-11" width="76" height="22" rx="11"></rect><text y="4">Speech ${verdictSymbol(spokenStatus)}</text></g>`
        : "";

      const globalNode = `<g class="fsm-graph-node is-global"><rect x="322" y="390" width="116" height="40" rx="7"></rect><text x="380" y="407"><tspan x="380" dy="0">global</tspan><tspan x="380" dy="13">guards</tspan></text></g>`;
      const nodeMarkup = nodes.map((node) => {
        const position = fsmGraphLayout[node.id];
        if (!position) return "";
        const lines = graphNodeLines(node.label);
        const isCurrent = node.id === currentPhase;
        const isTraversed = visitedPhases.has(node.id);
        const lineOffset = lines.length === 1 ? 4 : -3;
        const text = lines.map((line, lineIndex) => `<tspan x="${position.x}" dy="${lineIndex === 0 ? lineOffset : 13}">${escapeHtml(line)}</tspan>`).join("");
        return `<g class="fsm-graph-node${node.terminal ? " is-terminal" : ""}${isTraversed ? " is-traversed" : ""}${isCurrent ? " is-current" : ""}"><rect x="${position.x - 58}" y="${position.y - 20}" width="116" height="40" rx="7"></rect><text x="${position.x}" y="${position.y}">${text}</text></g>`;
      }).join("");

      graphNode.innerHTML = `<title>Live finite state machine graph</title><desc>The current phase and latest executed transition are highlighted. A separate marker reports spoken-response compliance.</desc><defs><marker id="fsm-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M 0 0 L 8 4 L 0 8 z" fill="context-stroke"></path></marker></defs>${edgeMarkup}${runtimeEdge}${globalNode}${nodeMarkup}${spokenMarker}`;
      document.getElementById("fsm-mobile-map").innerHTML = nodes.map((node) => {
        const isCurrent = node.id === currentPhase;
        const isTraversed = visitedPhases.has(node.id);
        return `<li class="fsm-mobile-state${isTraversed ? " is-traversed" : ""}${isCurrent ? " is-current" : ""}${node.terminal ? " is-terminal" : ""}">${escapeHtml(displayPhase(node.label))}</li>`;
      }).join("");
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

    function renderFSM(fsmState, transitions, graph, fsmAdherence, spokenCompliance) {
      const state = fsmState || {};
      const trail = Array.isArray(transitions) ? transitions : [];
      const fsmFingerprint = JSON.stringify(state) + JSON.stringify(trail) + JSON.stringify(fsmAdherence) + JSON.stringify(spokenCompliance);
      if (fsmFingerprint === lastFsmFingerprint) return;
      lastFsmFingerprint = fsmFingerprint;

      const monitor = document.getElementById("fsm-monitor");
      const guard = displayToken(state.guard_reason, "clear");
      const terminal = Boolean(state.should_end);

      monitor.className = `fsm-monitor${guard !== "clear" ? " has-guard" : ""}${terminal ? " is-terminal" : ""}`;
      document.body.classList.toggle("is-terminal", terminal);

      document.getElementById("fsm-phase").textContent = displayPhase(state.phase);
      document.getElementById("fsm-intent").textContent = displayToken(state.intent, "none");
      document.getElementById("fsm-transition-id").textContent = displayToken(state.transition_id, "awaiting_transition");
      document.getElementById("fsm-directive").textContent = displayToken(state.directive, "waiting_for_fsm");
      document.getElementById("fsm-guard").textContent = guard;

      const identity = state.identity_verified ? "identity verified" : "identity pending";
      const resolution = state.resolution_type ? ` · ${displayToken(state.resolution_type)}` : "";
      const refusals = Number(state.refusal_count || 0) ? ` · refusals ${Number(state.refusal_count)}` : "";
      document.getElementById("fsm-outcome").textContent = `${identity}${resolution}${refusals} · ${terminal ? "terminal" : "active"}`;
      document.getElementById("fsm-count").textContent = `${trail.length} transition${trail.length === 1 ? "" : "s"}`;
      renderFSMGraph(graph, state, trail, fsmAdherence, spokenCompliance);

      if (lastTransitionCount >= 0 && trail.length > lastTransitionCount) {
        const workspace = document.getElementById("live-workspace");
        workspace.classList.remove("is-synchronized");
        void workspace.offsetWidth;
        workspace.classList.add("is-synchronized");
        setTimeout(() => workspace.classList.remove("is-synchronized"), 720);
      }
      lastTransitionCount = trail.length;

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
          <div class="fsm-transition-status" title="${escapeHtml(displayToken(item.spoken_reason, "Spoken response pending"))}">
            <span class="fsm-spoken-badge is-${item.spoken_status === "pass" || item.spoken_status === "fail" ? item.spoken_status : "pending"}">Speech ${verdictSymbol(item.spoken_status)}</span>
            <span class="fsm-evidence${item.response_recorded || item.response_disposition === "coalesced" ? " is-recorded" : ""}"></span>
          </div>
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
      renderFSM(
        state.fsm_state,
        state.fsm_transitions,
        state.fsm_graph,
        state.fsm_adherence,
        state.spoken_compliance,
      );

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
        const connectionNode = document.getElementById("connection-state");
        connectionNode.className = "connection-state";
        connectionNode.textContent = "Live link";
        render(await response.json());
      } catch (error) {
        const connectionNode = document.getElementById("connection-state");
        connectionNode.className = "connection-state is-offline";
        connectionNode.textContent = "Link unavailable";
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
