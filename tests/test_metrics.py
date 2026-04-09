from __future__ import annotations

import unittest

from livekit.agents.metrics import EOUMetrics, LLMMetrics, STTMetrics, TTSMetrics, VADMetrics
from livekit.agents.voice.events import MetricsCollectedEvent

from voice_agent.metrics import format_metrics_block, log_metrics_event


class MetricsFormattingTests(unittest.TestCase):
    def test_formats_llm_metrics(self) -> None:
        metric = LLMMetrics(
            label="openai.llm",
            request_id="req-1",
            timestamp=1.0,
            duration=0.75,
            ttft=0.25,
            cancelled=False,
            completion_tokens=48,
            prompt_tokens=32,
            prompt_cached_tokens=0,
            total_tokens=80,
            tokens_per_second=64.0,
        )

        block = format_metrics_block(metric)
        assert block is not None
        self.assertIn("--- LLM Metrics ---", block)
        self.assertIn("Prompt Tokens: 32", block)
        self.assertIn("TTFT: 0.2500s", block)

    def test_formats_stt_metrics(self) -> None:
        metric = STTMetrics(
            label="openai.stt",
            request_id="req-2",
            timestamp=1.0,
            duration=0.4,
            audio_duration=1.2,
            streamed=False,
        )

        block = format_metrics_block(metric)
        assert block is not None
        self.assertIn("--- STT Metrics ---", block)
        self.assertIn("Audio Duration: 1.2000s", block)
        self.assertIn("Streamed: No", block)

    def test_formats_tts_metrics(self) -> None:
        metric = TTSMetrics(
            label="openai.tts",
            request_id="req-3",
            timestamp=1.0,
            ttfb=0.18,
            duration=0.52,
            audio_duration=1.8,
            cancelled=False,
            characters_count=12,
            streamed=True,
        )

        block = format_metrics_block(metric)
        assert block is not None
        self.assertIn("--- TTS Metrics ---", block)
        self.assertIn("TTFB: 0.1800s", block)
        self.assertIn("Streamed: Yes", block)

    def test_formats_eou_metrics(self) -> None:
        metric = EOUMetrics(
            timestamp=1.0,
            end_of_utterance_delay=0.3,
            transcription_delay=0.2,
            on_user_turn_completed_delay=0.1,
        )

        block = format_metrics_block(metric)
        assert block is not None
        self.assertIn("--- End of Utterance Metrics ---", block)
        self.assertIn("Transcription Delay: 0.2000s", block)
        self.assertIn("On User Turn Completed Delay: 0.1000s", block)

    def test_ignores_vad_metrics(self) -> None:
        metric = VADMetrics(
            label="silero.vad",
            timestamp=1.0,
            idle_time=0.3,
            inference_duration_total=0.1,
            inference_count=4,
        )

        self.assertIsNone(format_metrics_block(metric))

    def test_logs_metrics_collected_event(self) -> None:
        metric = EOUMetrics(
            timestamp=1.0,
            end_of_utterance_delay=0.3,
            transcription_delay=0.2,
            on_user_turn_completed_delay=0.1,
        )
        event = MetricsCollectedEvent(metrics=metric)
        writes: list[str] = []

        log_metrics_event(event, write=writes.append)

        self.assertEqual(len(writes), 1)
        self.assertIn("End of Utterance Delay: 0.3000s", writes[0])
