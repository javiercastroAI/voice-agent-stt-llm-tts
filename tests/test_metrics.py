from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from livekit.agents.metrics import EOUMetrics, LLMMetrics, STTMetrics, TTSMetrics, VADMetrics
from livekit.agents.voice.events import MetricsCollectedEvent, UserInputTranscribedEvent

from voice_agent.metrics import (
    VoiceTelemetryRecorder,
    build_metric_panel,
    format_metrics_block,
    log_metrics_event,
    metric_to_event,
    sync_metric_panel,
)


class _FakeMetricStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def set_metric_panel(
        self,
        *,
        panel_id: str,
        title: str,
        items: list[dict[str, str]],
    ) -> None:
        self.calls.append(
            {
                "panel_id": panel_id,
                "title": title,
                "items": items,
            }
        )


class MetricsFormattingTests(unittest.TestCase):
    def test_builds_llm_metric_panel(self) -> None:
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

        panel = build_metric_panel(metric)

        assert panel is not None
        self.assertEqual(panel["id"], "llm")
        self.assertEqual(panel["title"], "LLM Metrics")
        self.assertEqual(panel["items"][0]["label"], "Prompt Tokens")
        self.assertEqual(panel["items"][0]["value"], "32")

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
        self.assertIn("Speech End to Final Transcript: 0.2000s", block)
        self.assertIn("Final Transcript to Turn Completed: 0.1000s", block)

    def test_formats_vad_metrics(self) -> None:
        metric = VADMetrics(
            label="silero.vad",
            timestamp=1.0,
            idle_time=0.3,
            inference_duration_total=0.1,
            inference_count=4,
        )

        block = format_metrics_block(metric)
        assert block is not None
        self.assertIn("--- VAD Metrics ---", block)
        self.assertIn("Avg Inference: 0.0250s", block)

    def test_syncs_metric_panel_to_store(self) -> None:
        metric = EOUMetrics(
            timestamp=1.0,
            end_of_utterance_delay=0.3,
            transcription_delay=0.2,
            on_user_turn_completed_delay=0.1,
        )
        store = _FakeMetricStore()

        sync_metric_panel(metric, store=store)

        self.assertEqual(len(store.calls), 1)
        self.assertEqual(store.calls[0]["panel_id"], "eou")
        self.assertEqual(store.calls[0]["items"][0]["label"], "End of Utterance Delay")

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

    def test_metric_to_event_serializes_panel_metrics(self) -> None:
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

        event = metric_to_event(metric)

        assert event is not None
        self.assertEqual(event["type"], "tts_metrics")
        self.assertEqual(event["ttfb_seconds"], 0.18)
        self.assertTrue(event["streamed"])

    def test_metric_to_event_serializes_eou_split_fields(self) -> None:
        metric = EOUMetrics(
            timestamp=1.0,
            end_of_utterance_delay=0.45,
            transcription_delay=0.35,
            on_user_turn_completed_delay=0.1,
        )

        event = metric_to_event(metric)

        assert event is not None
        self.assertEqual(event["type"], "eou_metrics")
        self.assertEqual(event["observed_speech_end_to_turn_completed_seconds"], 0.45)
        self.assertEqual(event["observed_speech_end_to_final_transcript_seconds"], 0.35)
        self.assertEqual(event["observed_final_transcript_to_turn_completed_seconds"], 0.1)
        self.assertEqual(event["eou_split_source"], "livekit_eou_metrics")

    def test_metric_to_event_serializes_vad_average_inference(self) -> None:
        metric = VADMetrics(
            label="silero.vad",
            timestamp=1.0,
            idle_time=0.3,
            inference_duration_total=0.1,
            inference_count=4,
        )

        event = metric_to_event(metric)

        assert event is not None
        self.assertEqual(event["type"], "vad_metrics")
        self.assertEqual(event["vad_average_inference_duration_seconds"], 0.025)

    def test_voice_telemetry_recorder_writes_metrics_and_transcript_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            jsonl_path = str(Path(tmp_dir) / "voice.jsonl")
            sqlite_path = str(Path(tmp_dir) / "voice.sqlite3")
            recorder = VoiceTelemetryRecorder(
                jsonl_path=jsonl_path,
                sqlite_path=sqlite_path,
            )

            recorder.record_metric(
                STTMetrics(
                    label="openai.stt",
                    request_id="req-2",
                    timestamp=1.0,
                    duration=0.4,
                    audio_duration=1.2,
                    streamed=True,
                )
            )
            recorder.record_metric(
                EOUMetrics(
                    timestamp=1.5,
                    end_of_utterance_delay=0.45,
                    transcription_delay=0.35,
                    on_user_turn_completed_delay=0.1,
                )
            )
            recorder.record_metric(
                VADMetrics(
                    label="silero.vad",
                    timestamp=1.75,
                    idle_time=0.3,
                    inference_duration_total=0.1,
                    inference_count=4,
                )
            )
            recorder.record_user_transcript(
                UserInputTranscribedEvent(
                    transcript="Ново",
                    is_final=True,
                    language="es",
                    created_at=2.0,
                )
            )

            lines = [json.loads(line) for line in Path(jsonl_path).read_text().splitlines()]
            with sqlite3.connect(sqlite_path) as conn:
                rows = conn.execute(
                    """
                    SELECT
                        type,
                        streamed,
                        observed_speech_end_to_final_transcript_seconds,
                        eou_split_source,
                        vad_average_inference_duration_seconds,
                        transcript,
                        stt_fragmented_turn,
                        stt_non_latin_text
                    FROM voice_metric_events
                    ORDER BY id
                    """
                ).fetchall()

        self.assertEqual(lines[0]["type"], "stt_metrics")
        self.assertEqual(lines[1]["type"], "eou_metrics")
        self.assertEqual(lines[1]["observed_speech_end_to_final_transcript_seconds"], 0.35)
        self.assertEqual(lines[2]["type"], "vad_metrics")
        self.assertEqual(lines[2]["vad_average_inference_duration_seconds"], 0.025)
        self.assertEqual(lines[3]["type"], "user_transcript")
        self.assertTrue(lines[3]["stt_fragmented_turn"])
        self.assertEqual(rows[0], ("stt_metrics", 1, None, None, None, None, None, None))
        self.assertEqual(rows[1], ("eou_metrics", None, 0.35, "livekit_eou_metrics", None, None, None, None))
        self.assertEqual(rows[2], ("vad_metrics", None, None, None, 0.025, None, None, None))
        self.assertEqual(rows[3], ("user_transcript", None, None, None, None, "Ново", 1, 1))

    def test_final_transcript_is_not_fragmented_only_because_interim_was_recent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            jsonl_path = str(Path(tmp_dir) / "voice.jsonl")
            recorder = VoiceTelemetryRecorder(jsonl_path=jsonl_path)

            recorder.record_user_transcript(
                UserInputTranscribedEvent(
                    transcript="No",
                    is_final=False,
                    language="es",
                    created_at=1.0,
                )
            )
            recorder.record_user_transcript(
                UserInputTranscribedEvent(
                    transcript="No me parece mala oferta.",
                    is_final=True,
                    language="es",
                    created_at=1.2,
                )
            )

            lines = [json.loads(line) for line in Path(jsonl_path).read_text().splitlines()]

        self.assertTrue(lines[0]["stt_fragmented_turn"])
        self.assertTrue(lines[1]["stt_rapid_partial_update"])
        self.assertFalse(lines[1]["stt_fragmented_turn"])
