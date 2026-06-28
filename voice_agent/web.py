"""Local transcript web UI for console mode."""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Lock, Thread

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

    def __init__(self) -> None:
        self._lock = Lock()
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
    ) -> None:
        self._host = host
        self._port = port
        self.store = store or TranscriptStore()
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

    @media (max-width: 880px) {
      .hero-layout {
        grid-template-columns: 1fr;
      }

      .overview-grid {
        grid-template-columns: 1fr;
      }
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

      const messages = [...state.messages, ...buildLiveMessages(state)];
      const fingerprint = JSON.stringify(messages) + state.user_state + state.agent_state + JSON.stringify(state.barge_in_state) + JSON.stringify(state.models) + JSON.stringify(state.metrics) + JSON.stringify(state.hero_card) + JSON.stringify(state.technologies);
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
