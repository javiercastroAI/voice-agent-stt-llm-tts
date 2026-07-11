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
                        "min_delay": 0.40,
                        "max_delay": 1.20,
                    },
                    "interruption": {
                        "enabled": True,
                        "mode": "vad",
                        "discard_audio_if_uninterruptible": True,
                        "min_duration": 0.50,
                        "min_words": 2,
                        "false_interruption_timeout": 2.0,
                        "resume_false_interruption": True,
                    },
                },
                "min_consecutive_speech_delay": 0.20,
                "preemptive_generation": False,
                "user_away_timeout": 30.0,
            },
        )


class BargeInControllerTests(unittest.TestCase):
    def test_default_noise_candidate_does_not_force_mute_at_vad_edge(self) -> None:
        store = TranscriptStore()
        calls: list[float] = []

        controller = BargeInController(
            BargeInPolicy.from_config(AgentConfig.from_env({})),
            store=store,
            on_immediate_mute=lambda created_at: (
                calls.append(created_at) or True,
                "must not be called",
            ),
        )

        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="thinking", new_state="speaking", created_at=1.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking", created_at=2.0)
        )

        snapshot = store.snapshot()
        self.assertEqual(calls, [])
        self.assertEqual(snapshot["barge_in_state"]["state"], "candidate")
        self.assertEqual(snapshot["barge_in_state"]["immediate_mute_attempts"], 0)
        self.assertFalse(snapshot["barge_in_events"][-1]["immediate_mute_enabled"])

    def test_soft_pause_yields_audio_then_confirmed_stt_cancels(self) -> None:
        store = TranscriptStore()
        pauses: list[float] = []
        cancels: list[float] = []
        controller = BargeInController(
            BargeInPolicy.from_config(AgentConfig.from_env({})),
            store=store,
            on_soft_pause=lambda created_at: (pauses.append(created_at) or True, "audio.pause"),
            on_confirmed_interrupt=lambda created_at: (
                cancels.append(created_at) or True,
                "session.interrupt(force=True)",
            ),
        )

        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="thinking", new_state="speaking", created_at=1.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking", created_at=2.0)
        )
        controller.on_user_input_transcribed(
            UserInputTranscribedEvent(transcript="para", is_final=False, created_at=2.3)
        )

        snapshot = store.snapshot()
        self.assertEqual(pauses, [2.0])
        self.assertEqual(cancels, [2.3])
        self.assertEqual(snapshot["barge_in_state"]["soft_pause_successes"], 1)
        self.assertEqual(snapshot["barge_in_state"]["confirmed_cancel_successes"], 1)
        self.assertTrue(snapshot["barge_in_events"][-1]["confirmed_cancel_success"])

    def test_interim_barge_decision_authorizes_its_final_transcript_for_fsm(self) -> None:
        controller = BargeInController(BargeInPolicy.from_config(AgentConfig.from_env({})))

        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="thinking", new_state="speaking", created_at=1.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking", created_at=2.0)
        )
        controller.on_user_input_transcribed(
            UserInputTranscribedEvent(transcript="para", is_final=False, created_at=2.2)
        )
        controller.on_user_input_transcribed(
            UserInputTranscribedEvent(
                transcript="para un momento", is_final=True, created_at=2.5
            )
        )

        decision = controller.consume_user_turn_decision("para un momento")
        self.assertIsNotNone(decision)
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.reason, "qualified_barge_in")

    def test_ordinary_one_word_fragment_cannot_cancel_agent_speech(self) -> None:
        store = TranscriptStore()
        cancels: list[float] = []
        controller = BargeInController(
            BargeInPolicy.from_config(AgentConfig.from_env({})),
            store=store,
            on_confirmed_interrupt=lambda created_at: (
                cancels.append(created_at) or True,
                "session.interrupt(force=True)",
            ),
        )

        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="thinking", new_state="speaking", created_at=1.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking", created_at=2.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="speaking", new_state="listening", created_at=2.2)
        )
        controller.on_user_input_transcribed(
            UserInputTranscribedEvent(transcript="pero", is_final=True, created_at=2.5)
        )

        self.assertEqual(cancels, [])
        event = store.snapshot()["barge_in_events"][-1]
        self.assertEqual(event["type"], "candidate_ignored")
        self.assertEqual(event["ignore_reason_code"], "below_qualified_word_threshold")

    def test_recent_agent_playback_phrase_cannot_cancel_agent_speech(self) -> None:
        store = TranscriptStore()
        cancels: list[float] = []
        controller = BargeInController(
            BargeInPolicy.from_config(AgentConfig.from_env({})),
            store=store,
            is_playback_echo=lambda transcript: transcript == "cloudx mensualidad",
            on_confirmed_interrupt=lambda created_at: (
                cancels.append(created_at) or True,
                "session.interrupt(force=True)",
            ),
        )

        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="thinking", new_state="speaking", created_at=1.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking", created_at=2.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="speaking", new_state="listening", created_at=2.2)
        )
        controller.on_user_input_transcribed(
            UserInputTranscribedEvent(
                transcript="cloudx mensualidad", is_final=True, created_at=2.5
            )
        )

        self.assertEqual(cancels, [])
        self.assertEqual(
            store.snapshot()["barge_in_events"][-1]["ignore_reason_code"], "playback_echo"
        )

    def test_candidate_without_text_holds_then_recovers_soft_pause(self) -> None:
        store = TranscriptStore()
        resumes: list[float] = []
        controller = BargeInController(
            BargeInPolicy.from_config(AgentConfig.from_env({})),
            store=store,
            on_soft_pause=lambda _created_at: (True, "audio.pause"),
            on_soft_resume=lambda created_at: (resumes.append(created_at) or True, "audio.resume"),
        )

        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="thinking", new_state="speaking", created_at=1.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking", created_at=2.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="speaking", new_state="listening", created_at=2.2)
        )
        self.assertEqual(resumes, [])
        controller._recover_soft_paused_candidate()
        self.assertEqual(len(resumes), 1)
        self.assertEqual(store.snapshot()["barge_in_state"]["soft_resume_successes"], 1)

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
            UserInputTranscribedEvent(transcript="wait please now", is_final=False)
        )

        snapshot = store.snapshot()
        self.assertEqual(snapshot["barge_in_state"]["state"], "interrupted")
        self.assertEqual(snapshot["barge_in_state"]["detected"], 1)
        self.assertEqual(snapshot["barge_in_state"]["confirmed"], 1)
        self.assertEqual(snapshot["metrics"][0]["id"], "barge_in")
        self.assertEqual(snapshot["barge_in_events"][-1]["type"], "candidate_confirmed")

    def test_detects_candidate_when_native_pause_reports_agent_as_listening(self) -> None:
        store = TranscriptStore()
        controller = BargeInController(
            BargeInPolicy.from_config(AgentConfig.from_env({})),
            store=store,
            is_agent_output_active=lambda: True,
        )

        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="thinking", new_state="speaking", created_at=1.0)
        )
        controller.on_agent_state_changed(
            AgentStateChangedEvent(old_state="speaking", new_state="listening", created_at=2.0)
        )
        controller.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking", created_at=2.1)
        )

        snapshot = store.snapshot()
        self.assertEqual(snapshot["barge_in_state"]["state"], "candidate")
        self.assertEqual(snapshot["barge_in_state"]["detected"], 1)

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
                transcript="wait please now",
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
                transcript="espera por favor ahora",
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
                transcript="espera por favor ahora",
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
                transcript="para por favor ahora",
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
            BargeInPolicy.from_config(
                AgentConfig.from_env({"BARGE_IN_IMMEDIATE_MUTE_ENABLED": "true"})
            ),
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
                transcript="para por favor ahora",
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
            BargeInPolicy.from_config(
                AgentConfig.from_env({"BARGE_IN_IMMEDIATE_MUTE_ENABLED": "true"})
            ),
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
            UserInputTranscribedEvent(transcript="sí sí claro", is_final=True, language="es", created_at=2.6)
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
                transcript="para por favor ahora",
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
            controller = BargeInController(policy, store=store, call_id="call-test")

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
        self.assertEqual(store.snapshot()["barge_in_events"][-1]["callId"], "call-test")

    def test_disabled_policy_publishes_disabled_state(self) -> None:
        store = TranscriptStore()
        policy = BargeInPolicy.from_config(AgentConfig.from_env({"BARGE_IN_ENABLED": "false"}))

        BargeInController(policy, store=store)

        snapshot = store.snapshot()
        self.assertEqual(snapshot["barge_in_state"]["state"], "disabled")
        self.assertFalse(snapshot["barge_in_state"]["enabled"])
