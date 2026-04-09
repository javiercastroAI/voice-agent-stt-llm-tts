from __future__ import annotations

from types import SimpleNamespace
import unittest

from livekit import rtc
from livekit.agents import APIConnectOptions, stt
from livekit.agents.types import NOT_GIVEN
from openai.types.audio import TranscriptionDiarized

from voice_agent.diarized_stt import (
    DIARIZED_STT_MODEL,
    DiarizedTranscript,
    OpenAIDiarizedSTT,
)


class OpenAIDiarizedSTTTests(unittest.IsolatedAsyncioTestCase):
    async def test_recognize_impl_returns_final_transcript_and_callback(self) -> None:
        diarized_calls: list[DiarizedTranscript] = []
        recognizer = OpenAIDiarizedSTT(
            api_key="test-key",
            on_diarization=diarized_calls.append,
        )

        async def create(**kwargs):
            self.assertEqual(kwargs["model"], DIARIZED_STT_MODEL)
            self.assertEqual(kwargs["response_format"], "diarized_json")
            self.assertEqual(kwargs["language"], "en")
            return TranscriptionDiarized.model_validate(
                {
                    "duration": 2.5,
                    "task": "transcribe",
                    "text": "hello world",
                    "segments": [
                        {
                            "id": "seg_1",
                            "type": "transcript.text.segment",
                            "speaker": "A",
                            "start": 0.0,
                            "end": 2.5,
                            "text": "hello world",
                        }
                    ],
                }
            )

        recognizer._client = SimpleNamespace(
            audio=SimpleNamespace(
                transcriptions=SimpleNamespace(create=create),
            )
        )

        event = await recognizer._recognize_impl(
            [rtc.AudioFrame.create(sample_rate=24000, num_channels=1, samples_per_channel=2400)],
            conn_options=APIConnectOptions(),
            language=NOT_GIVEN,
        )

        self.assertEqual(event.type, stt.SpeechEventType.FINAL_TRANSCRIPT)
        self.assertEqual(event.alternatives[0].text, "hello world")
        self.assertEqual(event.alternatives[0].speaker_id, "A")
        self.assertEqual(len(diarized_calls), 1)
        self.assertEqual(diarized_calls[0].segments[0].speaker, "A")

    async def test_recognize_impl_updates_language_when_explicitly_provided(self) -> None:
        recognizer = OpenAIDiarizedSTT(api_key="test-key")

        async def create(**kwargs):
            self.assertEqual(kwargs["language"], "es")
            return TranscriptionDiarized.model_validate(
                {
                    "duration": 1.0,
                    "task": "transcribe",
                    "text": "hola",
                    "segments": [
                        {
                            "id": "seg_1",
                            "type": "transcript.text.segment",
                            "speaker": "A",
                            "start": 0.0,
                            "end": 1.0,
                            "text": "hola",
                        }
                    ],
                }
            )

        recognizer._client = SimpleNamespace(
            audio=SimpleNamespace(
                transcriptions=SimpleNamespace(create=create),
            )
        )

        event = await recognizer._recognize_impl(
            [rtc.AudioFrame.create(sample_rate=24000, num_channels=1, samples_per_channel=2400)],
            conn_options=APIConnectOptions(),
            language="es",
        )

        self.assertEqual(event.alternatives[0].language.language, "es")
