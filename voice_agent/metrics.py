"""Metrics formatting and logging helpers."""

from __future__ import annotations

from collections.abc import Callable

from livekit.agents.metrics import EOUMetrics, LLMMetrics, STTMetrics, TTSMetrics, VADMetrics
from livekit.agents.voice.events import MetricsCollectedEvent

Writer = Callable[[str], object]


def format_metrics_block(
    metric: LLMMetrics | STTMetrics | TTSMetrics | EOUMetrics | VADMetrics | object,
) -> str | None:
    if isinstance(metric, LLMMetrics):
        return "\n".join(
            [
                "--- LLM Metrics ---",
                f"Prompt Tokens: {metric.prompt_tokens}",
                f"Completion Tokens: {metric.completion_tokens}",
                f"Tokens per second: {metric.tokens_per_second:.4f}",
                f"TTFT: {metric.ttft:.4f}s",
                "------------------",
            ]
        )

    if isinstance(metric, STTMetrics):
        return "\n".join(
            [
                "--- STT Metrics ---",
                f"Duration: {metric.duration:.4f}s",
                f"Audio Duration: {metric.audio_duration:.4f}s",
                f"Streamed: {'Yes' if metric.streamed else 'No'}",
                "------------------",
            ]
        )

    if isinstance(metric, TTSMetrics):
        return "\n".join(
            [
                "--- TTS Metrics ---",
                f"TTFB: {metric.ttfb:.4f}s",
                f"Duration: {metric.duration:.4f}s",
                f"Audio Duration: {metric.audio_duration:.4f}s",
                f"Streamed: {'Yes' if metric.streamed else 'No'}",
                "------------------",
            ]
        )

    if isinstance(metric, EOUMetrics):
        return "\n".join(
            [
                "--- End of Utterance Metrics ---",
                f"End of Utterance Delay: {metric.end_of_utterance_delay:.4f}s",
                f"Transcription Delay: {metric.transcription_delay:.4f}s",
                f"On User Turn Completed Delay: {metric.on_user_turn_completed_delay:.4f}s",
                "--------------------------------",
            ]
        )

    return None


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
