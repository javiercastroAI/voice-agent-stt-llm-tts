from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from livekit.agents.voice.events import (
    AgentFalseInterruptionEvent,
    AgentStateChangedEvent,
    UserInputTranscribedEvent,
    UserStateChangedEvent,
)

from voice_agent.barge_in import BargeInController, BargeInPolicy
from voice_agent.config import AgentConfig
from voice_agent.web import TranscriptStore


class BargeInPolicyTests(unittest.TestCase):
    def test_session_options_map_contact_center_defaults(self) -> None:
        policy = BargeInPolicy.from_config(AgentConfig.from_env({}))

        self.assertEqual(
            policy.session_options(),
            {
                "turn_handling": {
                    "endpointing": {
                        "mode": "dynamic",
                        "min_delay": 0.20,
                        "max_delay": 0.55,
                    },
                    "interruption": {
                        "enabled": True,
                        "mode": "vad",
                        "discard_audio_if_uninterruptible": True,
                        "min_duration": 0.20,
                        "min_words": 2,
                        "false_interruption_timeout": 1.2,
                        "resume_false_interruption": True,
                    },
                },
                "min_consecutive_speech_delay": 0.10,
                "preemptive_generation": False,
                "user_away_timeout": 30.0,
            },
        )


class BargeInControllerTests(unittest.TestCase):
    def test_confirms_candidate_after_qualified_transcript(self) -> None:
        store = TranscriptStore()
        controller = BargeInController(BargeInPolicy.from_config(AgentConfig.from_env({})), store=store)

        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="thinking", new_state="speaking")
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking")
        )
        controller.on_user_input_transcribed(
            UserInputTranscribedEvent(transcript="wait please", is_final=False)
        )

        snapshot = store.snapshot()
        self.assertEqual(snapshot["barge_in_state"]["state"], "interrupted")
        self.assertEqual(snapshot["barge_in_state"]["detected"], 1)
        self.assertEqual(snapshot["barge_in_state"]["confirmed"], 1)
        self.assertEqual(snapshot["metrics"][0]["id"], "barge_in")
        self.assertEqual(snapshot["barge_in_events"][-1]["type"], "candidate_confirmed")

    def test_confirms_candidate_after_user_stops_speaking_when_stt_is_delayed(self) -> None:
        store = TranscriptStore()
        controller = BargeInController(BargeInPolicy.from_config(AgentConfig.from_env({})), store=store)

        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="thinking", new_state="speaking", created_at=1.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking", created_at=2.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="speaking", new_state="listening", created_at=2.5)
        )
        controller.on_user_input_transcribed(
            UserInputTranscribedEvent(
                transcript="wait please",
                is_final=True,
                created_at=4.0,
            )
        )

        snapshot = store.snapshot()
        self.assertEqual(snapshot["barge_in_state"]["state"], "interrupted")
        self.assertEqual(snapshot["barge_in_state"]["detected"], 1)
        self.assertEqual(snapshot["barge_in_state"]["confirmed"], 1)
        self.assertEqual(snapshot["barge_in_state"]["ignored"], 0)
        self.assertEqual(snapshot["barge_in_kpis"]["confirmation_rate"], 1.0)
        self.assertEqual(snapshot["barge_in_kpis"]["average_confirmation_delay_seconds"], 2.0)
        self.assertEqual(snapshot["barge_in_kpis"]["average_pending_transcript_seconds"], 1.5)

    def test_ignores_candidate_without_transcript(self) -> None:
        store = TranscriptStore()
        controller = BargeInController(BargeInPolicy.from_config(AgentConfig.from_env({})), store=store)

        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="thinking", new_state="speaking", created_at=1.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking", created_at=2.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="speaking", new_state="listening", created_at=2.5)
        )

        snapshot = store.snapshot()
        self.assertEqual(snapshot["barge_in_state"]["state"], "pending_transcript")
        self.assertEqual(snapshot["barge_in_state"]["ignored"], 0)

        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="speaking", new_state="listening", created_at=9.0)
        )

        snapshot = store.snapshot()
        self.assertEqual(snapshot["barge_in_state"]["state"], "monitoring")
        self.assertEqual(snapshot["barge_in_state"]["detected"], 1)
        self.assertEqual(snapshot["barge_in_state"]["ignored"], 1)
        self.assertEqual(snapshot["barge_in_state"]["confirmed"], 0)
        self.assertEqual(snapshot["barge_in_kpis"]["false_candidate_rate"], 1.0)

    def test_tracks_late_transcript_after_candidate_expiry(self) -> None:
        store = TranscriptStore()
        controller = BargeInController(BargeInPolicy.from_config(AgentConfig.from_env({})), store=store)

        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="thinking", new_state="speaking", created_at=1.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking", created_at=2.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="speaking", new_state="listening", created_at=2.5)
        )
        controller.on_user_input_transcribed(
            UserInputTranscribedEvent(
                transcript="espera por favor",
                is_final=True,
                language="es",
                created_at=9.0,
            )
        )

        snapshot = store.snapshot()
        self.assertEqual(snapshot["barge_in_state"]["ignored"], 1)
        self.assertEqual(snapshot["barge_in_state"]["late_transcripts_after_ignored"], 1)
        self.assertEqual(
            snapshot["barge_in_events"][-1]["type"],
            "late_transcript_after_ignored_candidate",
        )
        self.assertEqual(snapshot["barge_in_kpis"]["late_transcript_after_ignored_rate"], 1.0)

    def test_tracks_false_interruption_resume(self) -> None:
        store = TranscriptStore()
        controller = BargeInController(BargeInPolicy.from_config(AgentConfig.from_env({})), store=store)

        controller.on_agent_false_interruption(AgentFalseInterruptionEvent(resumed=True))

        snapshot = store.snapshot()
        self.assertEqual(snapshot["barge_in_state"]["state"], "false_interruption_resumed")
        self.assertEqual(snapshot["barge_in_state"]["false_interruptions"], 1)
        self.assertEqual(snapshot["barge_in_state"]["resumed_false_interruptions"], 1)

    def test_tracks_overtalk_recovery_language_and_transcript_classification(self) -> None:
        store = TranscriptStore()
        controller = BargeInController(BargeInPolicy.from_config(AgentConfig.from_env({})), store=store)

        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="thinking", new_state="speaking", created_at=1.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking", created_at=2.0)
        )
        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="speaking", new_state="listening", created_at=2.4)
        )
        controller.on_user_input_transcribed(
            UserInputTranscribedEvent(
                transcript="espera por favor",
                is_final=True,
                language="en",
                created_at=3.0,
            )
        )
        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="thinking", new_state="speaking", created_at=4.5)
        )

        snapshot = store.snapshot()
        self.assertEqual(snapshot["barge_in_state"]["command_confirmed"], 1)
        self.assertEqual(snapshot["barge_in_state"]["stt_language_mismatches"], 1)
        self.assertAlmostEqual(snapshot["barge_in_kpis"]["average_overtalk_seconds"], 0.4)
        self.assertAlmostEqual(snapshot["barge_in_kpis"]["average_recovery_seconds"], 1.5)
        self.assertEqual(snapshot["barge_in_kpis"]["language_mismatch_rate"], 1.0)

    def test_confirmed_candidate_does_not_inflate_later_overtalk(self) -> None:
        store = TranscriptStore()
        controller = BargeInController(BargeInPolicy.from_config(AgentConfig.from_env({})), store=store)

        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="thinking", new_state="speaking", created_at=1.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking", created_at=2.0)
        )
        controller.on_user_input_transcribed(
            UserInputTranscribedEvent(
                transcript="para por favor",
                is_final=True,
                language="es",
                created_at=2.4,
            )
        )
        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="speaking", new_state="listening", created_at=20.0)
        )

        snapshot = store.snapshot()
        self.assertAlmostEqual(snapshot["barge_in_kpis"]["average_overtalk_seconds"], 0.4)
        self.assertAlmostEqual(snapshot["barge_in_kpis"]["max_overtalk_seconds"], 0.4)

    def test_immediate_mute_success_truncates_overtalk_and_tracks_success(self) -> None:
        store = TranscriptStore()
        calls: list[float] = []

        def immediate_mute(created_at: float) -> tuple[bool, str | None]:
            calls.append(created_at)
            return True, "test.interrupt(force=True)"

        controller = BargeInController(
            BargeInPolicy.from_config(AgentConfig.from_env({})),
            store=store,
            on_immediate_mute=immediate_mute,
        )

        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="thinking", new_state="speaking", created_at=1.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking", created_at=2.0)
        )
        controller.on_user_input_transcribed(
            UserInputTranscribedEvent(
                transcript="para por favor",
                is_final=True,
                language="es",
                created_at=2.5,
            )
        )

        snapshot = store.snapshot()
        self.assertEqual(calls, [2.0])
        self.assertEqual(snapshot["barge_in_state"]["immediate_mute_attempts"], 1)
        self.assertEqual(snapshot["barge_in_state"]["immediate_mute_successes"], 1)
        self.assertEqual(snapshot["barge_in_state"]["immediate_mute_failures"], 0)
        self.assertEqual(snapshot["barge_in_kpis"]["immediate_mute_success_rate"], 1.0)
        self.assertEqual(snapshot["barge_in_kpis"]["average_mute_latency_seconds"], 0.0)
        self.assertEqual(snapshot["barge_in_kpis"]["average_overtalk_seconds"], 0.0)
        self.assertTrue(snapshot["barge_in_events"][0]["immediate_mute_success"])
        self.assertEqual(
            snapshot["barge_in_events"][0]["immediate_mute_method"],
            "test.interrupt(force=True)",
        )

    def test_immediate_mute_failure_keeps_existing_overtalk_measurement(self) -> None:
        store = TranscriptStore()

        def immediate_mute(_created_at: float) -> tuple[bool, str | None]:
            return False, "RuntimeError: AgentSession isn't running"

        controller = BargeInController(
            BargeInPolicy.from_config(AgentConfig.from_env({})),
            store=store,
            on_immediate_mute=immediate_mute,
        )

        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="thinking", new_state="speaking", created_at=1.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking", created_at=2.0)
        )
        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="speaking", new_state="listening", created_at=2.4)
        )
        controller.on_user_input_transcribed(
            UserInputTranscribedEvent(
                transcript="para por favor",
                is_final=True,
                language="es",
                created_at=2.5,
            )
        )

        snapshot = store.snapshot()
        self.assertEqual(snapshot["barge_in_state"]["immediate_mute_attempts"], 1)
        self.assertEqual(snapshot["barge_in_state"]["immediate_mute_successes"], 0)
        self.assertEqual(snapshot["barge_in_state"]["immediate_mute_failures"], 1)
        self.assertEqual(snapshot["barge_in_kpis"]["immediate_mute_success_rate"], 0.0)
        self.assertAlmostEqual(snapshot["barge_in_kpis"]["average_mute_latency_seconds"], 0.4)
        self.assertAlmostEqual(snapshot["barge_in_kpis"]["average_overtalk_seconds"], 0.4)
        self.assertFalse(snapshot["barge_in_events"][0]["immediate_mute_success"])
        self.assertEqual(
            snapshot["barge_in_events"][0]["immediate_mute_error"],
            "RuntimeError: AgentSession isn't running",
        )

    def test_tracks_backchannel_rate(self) -> None:
        store = TranscriptStore()
        controller = BargeInController(BargeInPolicy.from_config(AgentConfig.from_env({})), store=store)

        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="thinking", new_state="speaking", created_at=1.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking", created_at=2.0)
        )
        controller.on_user_input_transcribed(
            UserInputTranscribedEvent(transcript="sí sí", is_final=True, language="es", created_at=2.6)
        )

        snapshot = store.snapshot()
        self.assertEqual(snapshot["barge_in_state"]["backchannel_confirmed"], 1)
        self.assertEqual(snapshot["barge_in_kpis"]["backchannel_rate"], 1.0)

    def test_turn_confirmation_rate_deduplicates_multiple_candidates_in_one_turn(self) -> None:
        store = TranscriptStore()
        controller = BargeInController(BargeInPolicy.from_config(AgentConfig.from_env({})), store=store)

        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="thinking", new_state="speaking", created_at=1.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking", created_at=2.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="speaking", new_state="listening", created_at=2.6)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking", created_at=3.0)
        )
        controller.on_user_input_transcribed(
            UserInputTranscribedEvent(
                transcript="para por favor",
                is_final=True,
                language="es",
                created_at=3.3,
            )
        )

        snapshot = store.snapshot()
        self.assertEqual(snapshot["barge_in_state"]["detected"], 2)
        self.assertEqual(snapshot["barge_in_state"]["confirmed"], 1)
        self.assertEqual(snapshot["barge_in_state"]["detected_turns"], 1)
        self.assertEqual(snapshot["barge_in_state"]["confirmed_turns"], 1)
        self.assertEqual(snapshot["barge_in_kpis"]["confirmation_rate"], 0.5)
        self.assertEqual(snapshot["barge_in_kpis"]["turn_confirmation_rate"], 1.0)

    def test_writes_sqlite_telemetry_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            sqlite_path = str(Path(tmp_dir) / "barge-in.sqlite3")
            store = TranscriptStore()
            policy = BargeInPolicy.from_config(
                AgentConfig.from_env({"BARGE_IN_SQLITE_PATH": sqlite_path})
            )
            controller = BargeInController(policy, store=store)

            controller.on_agent_state_changed(
                AgentStateChangedEvent(old_state="thinking", new_state="speaking", created_at=1.0)
            )
            controller.on_user_state_changed(
                UserStateChangedEvent(old_state="listening", new_state="speaking", created_at=2.0)
            )
            controller.on_user_input_transcribed(
                UserInputTranscribedEvent(
                    transcript="para por favor",
                    is_final=True,
                    language="es",
                    created_at=2.4,
                )
            )

            with sqlite3.connect(sqlite_path) as conn:
                rows = conn.execute(
                    "SELECT type, confirmed_turns, language FROM barge_in_events ORDER BY id"
                ).fetchall()

        self.assertEqual(rows[-1], ("candidate_confirmed", 1, "es"))

    def test_disabled_policy_publishes_disabled_state(self) -> None:
        store = TranscriptStore()
        policy = BargeInPolicy.from_config(AgentConfig.from_env({"BARGE_IN_ENABLED": "false"}))

        BargeInController(policy, store=store)

        snapshot = store.snapshot()
        self.assertEqual(snapshot["barge_in_state"]["state"], "disabled")
        self.assertFalse(snapshot["barge_in_state"]["enabled"])
