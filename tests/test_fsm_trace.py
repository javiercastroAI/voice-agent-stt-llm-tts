from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest

from voice_agent.conversation_fsm import (
    ConversationFSM,
    TurnIntent,
    create_initial_state,
    make_turn_event,
)
from voice_agent.fsm_trace import FSMTraceRecorder


def case_fixture():
    return {
        "case_id": "case-private",
        "creditor_name": "Northwind",
        "customer_name": "Private Customer Ltd",
        "locale": "en-GB",
        "disclosure_summary": "a private charge",
        "amount_minor": 2500,
        "currency": "GBP",
        "metadata": {"internal": "never trace"},
        "available_resolution_types": ["payment"],
    }


def started_state():
    fsm = ConversationFSM()
    return fsm, fsm.advance(
        create_initial_state(case_fixture()),
        make_turn_event(TurnIntent.CALL_STARTED, source="system"),
    )


class FSMTraceRecorderTests(unittest.TestCase):
    def recorder(self, **kwargs):
        ids = iter(["turn-1", "turn-2", "turn-3"])
        return FSMTraceRecorder(
            call_id="call-test",
            id_factory=lambda: next(ids),
            now=lambda: datetime(2026, 7, 10, tzinfo=timezone.utc),
            **kwargs,
        )

    def test_correlates_opening_and_response_without_case_payload(self) -> None:
        _, state = started_state()
        recorder = self.recorder()

        turn_id = recorder.record_opening(state)
        response_turn_id = recorder.record_assistant_response("Hello. Who am I speaking with?")

        self.assertEqual(turn_id, "turn-1")
        self.assertEqual(response_turn_id, turn_id)
        self.assertEqual([event["type"] for event in recorder.events], [
            "fsm_transition",
            "assistant_response",
        ])
        self.assertEqual({event["callId"] for event in recorder.events}, {"call-test"})
        serialized = json.dumps(recorder.events)
        self.assertNotIn("Private Customer Ltd", serialized)
        self.assertNotIn("never trace", serialized)
        self.assertNotIn("2500", serialized)

    def test_records_interpreted_transition_evidence(self) -> None:
        fsm, state = started_state()
        event = make_turn_event(
            TurnIntent.IDENTITY_CONFIRMED,
            verification_fields=["role", "name_and_first_surname"],
            evidence={"interpreter": "openai_structured_output"},
        )
        state = fsm.advance(state, event)
        recorder = self.recorder()

        recorder.record_transition(
            user_transcript="Yes, I am responsible.",
            event=event,
            state=state,
        )

        transition = recorder.events[0]
        self.assertEqual(transition["fromPhase"], "identity_verification")
        self.assertEqual(transition["transitionId"], "identity_complete")
        self.assertEqual(transition["toPhase"], "case_disclosure")
        self.assertTrue(transition["identityVerified"])
        self.assertEqual(
            transition["verifiedFields"],
            ["role", "name_and_first_surname"],
        )
        self.assertEqual(transition["interpreter"], "openai_structured_output")

    def test_deduplicates_conversation_items(self) -> None:
        _, state = started_state()
        recorder = self.recorder()
        recorder.record_opening(state)
        item = SimpleNamespace(
            type="message",
            role="assistant",
            id="message-1",
            text_content="Opening response",
        )
        event = SimpleNamespace(item=item)

        recorder.record_conversation_item(event)
        recorder.record_conversation_item(event)

        self.assertEqual(
            len([entry for entry in recorder.events if entry["type"] == "assistant_response"]),
            1,
        )

    def test_records_streamed_terminal_response_and_deduplicates_late_item(self) -> None:
        fsm, state = started_state()
        terminal_event = make_turn_event(TurnIntent.EXPLICIT_TERMINATION)
        state = fsm.advance(state, terminal_event)
        recorder = self.recorder()
        turn_id = recorder.record_transition(
            user_transcript="Goodbye.",
            event=terminal_event,
            state=state,
        )

        streamed_turn_id = recorder.record_streamed_terminal_response("Thank you. Goodbye.")
        late_item = SimpleNamespace(
            type="message",
            role="assistant",
            id="message-terminal",
            text_content="Thank you. Goodbye.",
        )
        duplicate_result = recorder.record_conversation_item(SimpleNamespace(item=late_item))

        self.assertEqual(streamed_turn_id, turn_id)
        self.assertIsNone(duplicate_result)
        self.assertEqual(
            len([entry for entry in recorder.events if entry["type"] == "assistant_response"]),
            1,
        )

    def test_ignores_streamed_non_terminal_response(self) -> None:
        _, state = started_state()
        recorder = self.recorder()
        recorder.record_opening(state)

        self.assertIsNone(recorder.record_streamed_terminal_response("Opening response"))
        self.assertEqual([event["type"] for event in recorder.events], ["fsm_transition"])

    def test_records_last_assistant_message_from_completed_terminal_speech(self) -> None:
        fsm, state = started_state()
        terminal_event = make_turn_event(TurnIntent.EXPLICIT_TERMINATION)
        state = fsm.advance(state, terminal_event)
        recorder = self.recorder()
        turn_id = recorder.record_transition(
            user_transcript="Goodbye.",
            event=terminal_event,
            state=state,
        )
        speech_handle = SimpleNamespace(
            chat_items=[
                SimpleNamespace(type="function_call", role=None, text_content=""),
                SimpleNamespace(
                    type="message",
                    role="assistant",
                    text_content="Thank you for your time. Goodbye.",
                ),
            ]
        )

        recorded_turn = recorder.record_terminal_speech_handle(speech_handle)

        self.assertEqual(recorded_turn, turn_id)
        self.assertEqual(recorder.events[-1]["assistantText"], "Thank you for your time. Goodbye.")

    def test_new_turn_coalesces_older_unreplied_transition(self) -> None:
        fsm, state = started_state()
        recorder = self.recorder()
        opening_turn = recorder.record_opening(state)
        event = make_turn_event(TurnIntent.IDENTITY_CONFIRMED)
        state = fsm.advance(state, event)

        latest_turn = recorder.record_transition(
            user_transcript="Javier, director.",
            event=event,
            state=state,
        )
        response_turn = recorder.record_assistant_response("Thank you, Javier.")

        superseded = next(
            item for item in recorder.events if item["type"] == "turn_superseded"
        )
        self.assertEqual(superseded["turnId"], opening_turn)
        self.assertEqual(response_turn, latest_turn)

    def test_writes_jsonl(self) -> None:
        _, state = started_state()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            recorder = self.recorder(jsonl_path=str(path))
            recorder.record_opening(state)
            recorder.record_assistant_response("Opening")
            lines = path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["turnId"], "turn-1")


if __name__ == "__main__":
    unittest.main()
