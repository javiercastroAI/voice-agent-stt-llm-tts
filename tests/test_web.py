from __future__ import annotations

import unittest

from livekit.agents.metrics import LLMMetrics

from voice_agent.diarized_stt import DiarizedTranscript, DiarizedTranscriptSegment
from voice_agent.metrics import sync_metric_panel
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
        self.assertEqual(snapshot["barge_in_state"]["state"], "monitoring")
        self.assertEqual(snapshot["live_user_text"], "")
        self.assertEqual(snapshot["live_agent_text"], "")
        self.assertEqual(len(snapshot["messages"]), 2)
        self.assertEqual(snapshot["messages"][0]["role"], "user")
        self.assertEqual(snapshot["messages"][0]["segments"][0]["speaker"], "A")
        self.assertEqual(snapshot["messages"][1]["text"], "Hi back")

    def test_snapshot_includes_live_metric_panels(self) -> None:
        store = TranscriptStore()

        sync_metric_panel(
            LLMMetrics(
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
            ),
            store=store,
        )

        snapshot = store.snapshot()

        self.assertEqual(snapshot["metrics"][0]["id"], "llm")
        self.assertEqual(snapshot["metrics"][0]["title"], "LLM Metrics")
        self.assertEqual(snapshot["metrics"][0]["items"][0]["label"], "Prompt Tokens")
        self.assertEqual(snapshot["metrics"][0]["items"][0]["value"], "32")

    def test_snapshot_includes_identity_models_and_technologies(self) -> None:
        store = TranscriptStore()
        store.set_models(
            [
                {"label": "LLM", "value": "gpt-4o-mini"},
                {"label": "STT", "value": "gpt-4o-transcribe-diarize"},
            ]
        )
        store.set_hero_card(title="", items=["Javier Castro", "DNAI", "2026"])
        store.set_technologies(["OpenAI", "LiveKit Agents", "Silero VAD"])

        snapshot = store.snapshot()

        self.assertEqual(snapshot["hero_card"]["title"], "")
        self.assertEqual(snapshot["hero_card"]["items"], ["Javier Castro", "DNAI", "2026"])
        self.assertEqual(snapshot["models"][0]["value"], "gpt-4o-mini")
        self.assertEqual(snapshot["technologies"][1], "LiveKit Agents")

    def test_snapshot_includes_barge_in_state(self) -> None:
        store = TranscriptStore()

        store.set_barge_in_state(
            {
                "enabled": True,
                "state": "interrupted",
                "last_reason": "Qualified user transcript confirmed the interruption",
                "detected": 1,
                "confirmed": 1,
                "kpis": {"confirmation_rate": 1.0},
            }
        )

        snapshot = store.snapshot()

        self.assertEqual(snapshot["barge_in_state"]["state"], "interrupted")
        self.assertEqual(snapshot["barge_in_state"]["detected"], 1)
        self.assertEqual(snapshot["barge_in_kpis"]["confirmation_rate"], 1.0)

    def test_snapshot_includes_barge_in_events(self) -> None:
        store = TranscriptStore()

        store.add_barge_in_event(
            {
                "type": "candidate_detected",
                "created_at": 1.0,
                "reason": "User speech detected during agent speech",
            }
        )

        snapshot = store.snapshot()

        self.assertEqual(snapshot["barge_in_events"][0]["type"], "candidate_detected")


class TranscriptWebServerTests(unittest.TestCase):
    def test_server_exposes_default_url_and_html_template(self) -> None:
        store = TranscriptStore()
        store.add_agent_text("Test reply")
        server = TranscriptWebServer(store=store)

        self.assertEqual(server.url, "http://127.0.0.1:8765/")
        self.assertIn("Voice Agent Live View", _build_html())
        self.assertIn("Technology", _build_html())
        self.assertIn('id="models-card"', _build_html())
        self.assertIn('id="technology-card"', _build_html())
        self.assertIn("Live Metrics", _build_html())
        self.assertIn('id="metrics-grid"', _build_html())
        self.assertIn('id="barge-in-state"', _build_html())
        self.assertNotIn(">Identity<", _build_html())
        self.assertIn("DNAI", _build_html())
        self.assertEqual(store.snapshot()["messages"][0]["text"], "Test reply")
