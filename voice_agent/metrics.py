"""Metrics formatting, logging, and UI serialization helpers."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Protocol

from livekit.agents.metrics import EOUMetrics, LLMMetrics, STTMetrics, TTSMetrics, VADMetrics
from livekit.agents.voice.events import MetricsCollectedEvent, UserInputTranscribedEvent

Writer = Callable[[str], object]


class MetricStore(Protocol):
    def set_metric_panel(
        self,
        *,
        panel_id: str,
        title: str,
        items: list[dict[str, str]],
    ) -> None: ...


class VoiceTelemetryRecorder:
    """Persists runtime voice metrics and transcript stability signals."""

    def __init__(
        self,
        *,
        jsonl_path: str | None = None,
        sqlite_path: str | None = None,
        call_id: str | None = None,
    ) -> None:
        self._jsonl_path = jsonl_path
        self._sqlite_path = sqlite_path
        self._call_id = call_id
        self._last_transcript_at: float | None = None

    def record_metric(self, metric: object) -> None:
        payload = metric_to_event(metric)
        if payload is None:
            return
        self._write_event(payload)

    def record_user_transcript(self, event: UserInputTranscribedEvent) -> None:
        transcript = event.transcript.strip()
        if not transcript:
            return

        word_count = len([word for word in transcript.split() if word.strip()])
        non_latin = bool(re.search(r"[^\W\d_A-Za-zÁÉÍÓÚÜÑáéíóúüñ¿¡.,;:!?()'\" -]", transcript))
        previous_at = self._last_transcript_at
        gap_seconds = None if previous_at is None else max(0.0, event.created_at - previous_at)
        self._last_transcript_at = event.created_at
        rapid_partial_update = gap_seconds is not None and gap_seconds < 0.75
        fragmented = word_count <= 1 or non_latin
        if not event.is_final:
            fragmented = fragmented or rapid_partial_update

        self._write_event(
            {
                "type": "user_transcript",
                "created_at": event.created_at,
                "recorded_at": time.time(),
                "transcript": transcript,
                "language": event.language,
                "is_final": event.is_final,
                "word_count": word_count,
                "character_count": len(transcript),
                "gap_since_previous_transcript_seconds": gap_seconds,
                "stt_rapid_partial_update": rapid_partial_update,
                "stt_fragmented_turn": fragmented,
                "stt_non_latin_text": non_latin,
            }
        )

    def _write_event(self, event: dict[str, object]) -> None:
        if self._call_id is not None:
            event = {"callId": self._call_id, **event}
        if self._jsonl_path:
            path = Path(self._jsonl_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True) + "\n")

        if self._sqlite_path:
            self._write_sqlite_event(event)

    def _write_sqlite_event(self, event: dict[str, object]) -> None:
        path = Path(self._sqlite_path or "")
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_metric_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    type TEXT NOT NULL,
                    label TEXT,
                    request_id TEXT,
                    duration_seconds REAL,
                    audio_duration_seconds REAL,
                    streamed INTEGER,
                    ttft_seconds REAL,
                    ttfb_seconds REAL,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    total_tokens INTEGER,
                    tokens_per_second REAL,
                    end_of_utterance_delay_seconds REAL,
                    transcription_delay_seconds REAL,
                    on_user_turn_completed_delay_seconds REAL,
                    observed_speech_end_to_turn_completed_seconds REAL,
                    observed_speech_end_to_final_transcript_seconds REAL,
                    observed_final_transcript_to_turn_completed_seconds REAL,
                    eou_split_source TEXT,
                    vad_inference_duration_total_seconds REAL,
                    vad_inference_count INTEGER,
                    vad_average_inference_duration_seconds REAL,
                    transcript TEXT,
                    language TEXT,
                    word_count INTEGER,
                    stt_fragmented_turn INTEGER,
                    stt_non_latin_text INTEGER,
                    payload_json TEXT NOT NULL
                )
                """
            )
            _ensure_sqlite_columns(conn)
            conn.execute(
                """
                INSERT INTO voice_metric_events (
                    recorded_at,
                    created_at,
                    type,
                    label,
                    request_id,
                    duration_seconds,
                    audio_duration_seconds,
                    streamed,
                    ttft_seconds,
                    ttfb_seconds,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    tokens_per_second,
                    end_of_utterance_delay_seconds,
                    transcription_delay_seconds,
                    on_user_turn_completed_delay_seconds,
                    observed_speech_end_to_turn_completed_seconds,
                    observed_speech_end_to_final_transcript_seconds,
                    observed_final_transcript_to_turn_completed_seconds,
                    eou_split_source,
                    vad_inference_duration_total_seconds,
                    vad_inference_count,
                    vad_average_inference_duration_seconds,
                    transcript,
                    language,
                    word_count,
                    stt_fragmented_turn,
                    stt_non_latin_text,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.get("recorded_at"),
                    event.get("created_at"),
                    event.get("type"),
                    event.get("label"),
                    event.get("request_id"),
                    event.get("duration_seconds"),
                    event.get("audio_duration_seconds"),
                    event.get("streamed"),
                    event.get("ttft_seconds"),
                    event.get("ttfb_seconds"),
                    event.get("prompt_tokens"),
                    event.get("completion_tokens"),
                    event.get("total_tokens"),
                    event.get("tokens_per_second"),
                    event.get("end_of_utterance_delay_seconds"),
                    event.get("transcription_delay_seconds"),
                    event.get("on_user_turn_completed_delay_seconds"),
                    event.get("observed_speech_end_to_turn_completed_seconds"),
                    event.get("observed_speech_end_to_final_transcript_seconds"),
                    event.get("observed_final_transcript_to_turn_completed_seconds"),
                    event.get("eou_split_source"),
                    event.get("vad_inference_duration_total_seconds"),
                    event.get("vad_inference_count"),
                    event.get("vad_average_inference_duration_seconds"),
                    event.get("transcript"),
                    event.get("language"),
                    event.get("word_count"),
                    event.get("stt_fragmented_turn"),
                    event.get("stt_non_latin_text"),
                    json.dumps(event, sort_keys=True),
                ),
            )


def _ensure_sqlite_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(voice_metric_events)").fetchall()
    }
    columns = {
        "observed_speech_end_to_turn_completed_seconds": "REAL",
        "observed_speech_end_to_final_transcript_seconds": "REAL",
        "observed_final_transcript_to_turn_completed_seconds": "REAL",
        "eou_split_source": "TEXT",
        "vad_inference_duration_total_seconds": "REAL",
        "vad_inference_count": "INTEGER",
        "vad_average_inference_duration_seconds": "REAL",
    }
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE voice_metric_events ADD COLUMN {name} {definition}")


def metric_to_event(
    metric: LLMMetrics | STTMetrics | TTSMetrics | EOUMetrics | VADMetrics | object,
) -> dict[str, object] | None:
    recorded_at = time.time()

    if isinstance(metric, LLMMetrics):
        return {
            "type": "llm_metrics",
            "created_at": metric.timestamp,
            "recorded_at": recorded_at,
            "label": metric.label,
            "request_id": metric.request_id,
            "duration_seconds": metric.duration,
            "ttft_seconds": metric.ttft,
            "cancelled": metric.cancelled,
            "prompt_tokens": metric.prompt_tokens,
            "completion_tokens": metric.completion_tokens,
            "prompt_cached_tokens": metric.prompt_cached_tokens,
            "total_tokens": metric.total_tokens,
            "tokens_per_second": metric.tokens_per_second,
        }

    if isinstance(metric, STTMetrics):
        return {
            "type": "stt_metrics",
            "created_at": metric.timestamp,
            "recorded_at": recorded_at,
            "label": metric.label,
            "request_id": metric.request_id,
            "duration_seconds": metric.duration,
            "audio_duration_seconds": metric.audio_duration,
            "streamed": metric.streamed,
        }

    if isinstance(metric, TTSMetrics):
        return {
            "type": "tts_metrics",
            "created_at": metric.timestamp,
            "recorded_at": recorded_at,
            "label": metric.label,
            "request_id": metric.request_id,
            "duration_seconds": metric.duration,
            "audio_duration_seconds": metric.audio_duration,
            "ttfb_seconds": metric.ttfb,
            "cancelled": metric.cancelled,
            "characters_count": metric.characters_count,
            "streamed": metric.streamed,
        }

    if isinstance(metric, EOUMetrics):
        total_delay = metric.end_of_utterance_delay
        transcription_delay = metric.transcription_delay
        turn_completed_delay = metric.on_user_turn_completed_delay
        return {
            "type": "eou_metrics",
            "created_at": metric.timestamp,
            "recorded_at": recorded_at,
            "end_of_utterance_delay_seconds": total_delay,
            "transcription_delay_seconds": transcription_delay,
            "on_user_turn_completed_delay_seconds": turn_completed_delay,
            "observed_speech_end_to_turn_completed_seconds": total_delay,
            "observed_speech_end_to_final_transcript_seconds": transcription_delay,
            "observed_final_transcript_to_turn_completed_seconds": turn_completed_delay,
            "eou_split_source": "livekit_eou_metrics",
        }

    if isinstance(metric, VADMetrics):
        average_inference_duration = (
            metric.inference_duration_total / metric.inference_count
            if metric.inference_count > 0
            else None
        )
        return {
            "type": "vad_metrics",
            "created_at": metric.timestamp,
            "recorded_at": recorded_at,
            "label": metric.label,
            "idle_time_seconds": metric.idle_time,
            "inference_duration_total_seconds": metric.inference_duration_total,
            "inference_count": metric.inference_count,
            "vad_inference_duration_total_seconds": metric.inference_duration_total,
            "vad_inference_count": metric.inference_count,
            "vad_average_inference_duration_seconds": average_inference_duration,
        }

    return None


def build_metric_panel(
    metric: LLMMetrics | STTMetrics | TTSMetrics | EOUMetrics | VADMetrics | object,
) -> dict[str, object] | None:
    if isinstance(metric, LLMMetrics):
        return {
            "id": "llm",
            "title": "LLM Metrics",
            "items": [
                {"label": "Prompt Tokens", "value": str(metric.prompt_tokens)},
                {"label": "Completion Tokens", "value": str(metric.completion_tokens)},
                {"label": "Tokens per second", "value": f"{metric.tokens_per_second:.4f}"},
                {"label": "TTFT", "value": f"{metric.ttft:.4f}s"},
            ],
        }

    if isinstance(metric, STTMetrics):
        return {
            "id": "stt",
            "title": "STT Metrics",
            "items": [
                {"label": "Duration", "value": f"{metric.duration:.4f}s"},
                {"label": "Audio Duration", "value": f"{metric.audio_duration:.4f}s"},
                {"label": "Streamed", "value": "Yes" if metric.streamed else "No"},
            ],
        }

    if isinstance(metric, TTSMetrics):
        return {
            "id": "tts",
            "title": "TTS Metrics",
            "items": [
                {"label": "TTFB", "value": f"{metric.ttfb:.4f}s"},
                {"label": "Duration", "value": f"{metric.duration:.4f}s"},
                {"label": "Audio Duration", "value": f"{metric.audio_duration:.4f}s"},
                {"label": "Streamed", "value": "Yes" if metric.streamed else "No"},
            ],
        }

    if isinstance(metric, EOUMetrics):
        return {
            "id": "eou",
            "title": "End of Utterance Metrics",
            "items": [
                {
                    "label": "End of Utterance Delay",
                    "value": f"{metric.end_of_utterance_delay:.4f}s",
                },
                {"label": "Transcription Delay", "value": f"{metric.transcription_delay:.4f}s"},
                {
                    "label": "On User Turn Completed Delay",
                    "value": f"{metric.on_user_turn_completed_delay:.4f}s",
                },
                {
                    "label": "Speech End to Final Transcript",
                    "value": f"{metric.transcription_delay:.4f}s",
                },
                {
                    "label": "Final Transcript to Turn Completed",
                    "value": f"{metric.on_user_turn_completed_delay:.4f}s",
                },
            ],
        }

    if isinstance(metric, VADMetrics):
        average_inference_duration = (
            metric.inference_duration_total / metric.inference_count
            if metric.inference_count > 0
            else 0.0
        )
        return {
            "id": "vad",
            "title": "VAD Metrics",
            "items": [
                {"label": "Idle Time", "value": f"{metric.idle_time:.4f}s"},
                {
                    "label": "Inference Total",
                    "value": f"{metric.inference_duration_total:.4f}s",
                },
                {"label": "Inference Count", "value": str(metric.inference_count)},
                {
                    "label": "Avg Inference",
                    "value": f"{average_inference_duration:.4f}s",
                },
            ],
        }

    return None


def sync_metric_panel(
    metric: LLMMetrics | STTMetrics | TTSMetrics | EOUMetrics | VADMetrics | object,
    *,
    store: MetricStore | None,
) -> None:
    if store is None:
        return

    panel = build_metric_panel(metric)
    if panel is None:
        return

    items = [
        {"label": str(item["label"]), "value": str(item["value"])}
        for item in panel["items"]
    ]
    store.set_metric_panel(
        panel_id=str(panel["id"]),
        title=str(panel["title"]),
        items=items,
    )


def format_metrics_block(
    metric: LLMMetrics | STTMetrics | TTSMetrics | EOUMetrics | VADMetrics | object,
) -> str | None:
    panel = build_metric_panel(metric)
    if panel is None:
        return None

    footer = "--------------------------------" if panel["id"] == "eou" else "------------------"
    lines = [f"--- {panel['title']} ---"]
    lines.extend(
        f"{item['label']}: {item['value']}"
        for item in panel["items"]
    )
    lines.append(footer)
    return "\n".join(lines)


def emit_metrics_block(
    metric: LLMMetrics | STTMetrics | TTSMetrics | EOUMetrics | VADMetrics | object,
    *,
    write: Writer | None = None,
) -> None:
    block = format_metrics_block(metric)
    if block is None:
        return

    if write is None:
        print()
        print(block)
        print()
        return

    write(f"\n{block}\n")


def log_metrics_event(event: MetricsCollectedEvent, *, write: Writer | None = None) -> None:
    emit_metrics_block(event.metrics, write=write)
