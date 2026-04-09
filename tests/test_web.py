from __future__ import annotations

import unittest

from voice_agent.diarized_stt import DiarizedTranscript, DiarizedTranscriptSegment
from voice_agent.web import TranscriptStore, TranscriptWebServer, _build_html


class TranscriptStoreTests(unittest.TestCase):
    def test_snapshot_contains_live_and_final_messages(self) -> None:
        store = TranscriptStore()

        store.set_user_state("speaking")
        store.set_live_user_text("hello there", speaker="A")
        store.add_user_diarized(
            DiarizedTranscript(
                text="hello there",
                segments=(
                    DiarizedTranscriptSegment(
                        speaker="A",
                        text="hello there",
                        start=0.0,
                        end=1.4,
                    ),
                ),
            )
        )
        store.set_agent_state("speaking")
        store.append_agent_delta("Hi")
        store.append_agent_delta(" back")
        store.finalize_agent_stream()

        snapshot = store.snapshot()

        self.assertEqual(snapshot["user_state"], "speaking")
        self.assertEqual(snapshot["agent_state"], "speaking")
        self.assertEqual(snapshot["live_user_text"], "")
        self.assertEqual(snapshot["live_agent_text"], "")
        self.assertEqual(len(snapshot["messages"]), 2)
        self.assertEqual(snapshot["messages"][0]["role"], "user")
        self.assertEqual(snapshot["messages"][0]["segments"][0]["speaker"], "A")
        self.assertEqual(snapshot["messages"][1]["text"], "Hi back")

    def test_snapshot_includes_identity_models_and_technologies(self) -> None:
        store = TranscriptStore()
        store.set_models(
            [
                {"label": "LLM", "value": "gpt-4o"},
                {"label": "STT", "value": "gpt-4o-transcribe-diarize"},
            ]
        )
        store.set_hero_card(title="", items=["Javier Castro", "DNAI", "2026"])
        store.set_technologies(["OpenAI", "LiveKit Agents", "Silero VAD"])

        snapshot = store.snapshot()

        self.assertEqual(snapshot["hero_card"]["title"], "")
        self.assertEqual(snapshot["hero_card"]["items"], ["Javier Castro", "DNAI", "2026"])
        self.assertEqual(snapshot["models"][0]["value"], "gpt-4o")
        self.assertEqual(snapshot["technologies"][1], "LiveKit Agents")


class TranscriptWebServerTests(unittest.TestCase):
    def test_server_exposes_default_url_and_html_template(self) -> None:
        store = TranscriptStore()
        store.add_agent_text("Test reply")
        server = TranscriptWebServer(store=store)

        self.assertEqual(server.url, "http://127.0.0.1:8765/")
        self.assertIn("Voice Agent Live View", _build_html())
        self.assertIn("Technology", _build_html())
        self.assertIn("DNAI", _build_html())
        self.assertEqual(store.snapshot()["messages"][0]["text"], "Test reply")
