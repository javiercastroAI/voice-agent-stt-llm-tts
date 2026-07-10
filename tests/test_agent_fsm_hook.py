from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, PropertyMock, patch

from livekit.agents.llm import StopResponse

from voice_agent.agent import AssistantAgent
from voice_agent.conversation_fsm import (
    ConversationFSM,
    TurnIntent,
    create_initial_state,
    make_turn_event,
)


def verification_state():
    case = {
        "case_id": "case-001",
        "creditor_name": "Northwind Services",
        "customer_name": "Private Customer Ltd",
        "locale": "en-GB",
        "disclosure_summary": "an outstanding charge",
        "available_resolution_types": ["payment"],
    }
    fsm = ConversationFSM()
    return fsm.advance(
        create_initial_state(case),
        make_turn_event(TurnIntent.CALL_STARTED, source="system"),
    )


class FakeController:
    def __init__(self, state=None) -> None:
        self.calls = []
        self._state = state or verification_state()

    @property
    def state(self):
        return self._state

    @property
    def last_event(self):
        return self._state["event"]

    async def process_user_turn(self, transcript):
        self.calls.append(transcript)
        return self._state


class FakeTurnContext:
    def __init__(self) -> None:
        self.messages = []

    def add_message(self, **kwargs):
        self.messages.append(kwargs)


class AssistantAgentFSMHookTests(unittest.IsolatedAsyncioTestCase):
    def make_agent(self, controller, *, auto_opening=True) -> AssistantAgent:
        agent = AssistantAgent.__new__(AssistantAgent)
        agent._conversation_controller = controller
        agent._fsm_trace_recorder = None
        agent._auto_opening_enabled = auto_opening
        agent._opening_started = False
        agent._terminal_shutdown_requested = False
        agent._terminal_farewell_started = False
        agent._hang_up_tool_called = False
        return agent

    async def test_on_enter_schedules_one_interruptible_safe_opening(self) -> None:
        agent = self.make_agent(FakeController())
        session = SimpleNamespace(generate_reply=Mock())

        with patch.object(
            AssistantAgent,
            "session",
            new_callable=PropertyMock,
            return_value=session,
        ):
            await agent.on_enter()
            await agent.on_enter()

        session.generate_reply.assert_called_once()
        kwargs = session.generate_reply.call_args.kwargs
        self.assertTrue(kwargs["allow_interruptions"])
        self.assertIn("open_and_verify_identity", kwargs["instructions"])
        self.assertNotIn("Private Customer Ltd", kwargs["instructions"])

    async def test_on_enter_can_be_disabled(self) -> None:
        agent = self.make_agent(FakeController(), auto_opening=False)

        await agent.on_enter()

        self.assertFalse(agent._opening_started)

    async def test_opening_schedule_failure_allows_retry(self) -> None:
        agent = self.make_agent(FakeController())
        session = SimpleNamespace(
            generate_reply=Mock(side_effect=[RuntimeError("not ready"), None])
        )

        with patch.object(
            AssistantAgent,
            "session",
            new_callable=PropertyMock,
            return_value=session,
        ):
            with self.assertRaisesRegex(RuntimeError, "not ready"):
                await agent.on_enter()
            self.assertFalse(agent._opening_started)
            await agent.on_enter()

        self.assertEqual(session.generate_reply.call_count, 2)
        self.assertTrue(agent._opening_started)

    async def test_hook_advances_fsm_and_injects_ephemeral_system_control(self) -> None:
        controller = FakeController()
        agent = self.make_agent(controller)
        turn_ctx = FakeTurnContext()

        await agent.on_user_turn_completed(
            turn_ctx,
            SimpleNamespace(text_content="  Yes, speaking.  "),
        )

        self.assertEqual(controller.calls, ["Yes, speaking."])
        self.assertEqual(len(turn_ctx.messages), 1)
        self.assertEqual(turn_ctx.messages[0]["role"], "system")
        self.assertIn("RUNTIME FSM CONTROL", turn_ctx.messages[0]["content"])
        self.assertNotIn("Private Customer Ltd", turn_ctx.messages[0]["content"])

    async def test_runtime_hooks_emit_fsm_trace_evidence(self) -> None:
        controller = FakeController()
        agent = self.make_agent(controller)
        trace = Mock()
        agent._fsm_trace_recorder = trace
        session = SimpleNamespace(generate_reply=Mock())

        with patch.object(
            AssistantAgent,
            "session",
            new_callable=PropertyMock,
            return_value=session,
        ):
            await agent.on_enter()
        await agent.on_user_turn_completed(
            FakeTurnContext(),
            SimpleNamespace(text_content="Yes, speaking."),
        )

        trace.record_opening.assert_called_once_with(controller.state)
        trace.record_transition.assert_called_once()
        self.assertEqual(
            trace.record_transition.call_args.kwargs["user_transcript"],
            "Yes, speaking.",
        )

    async def test_empty_turn_stops_response(self) -> None:
        agent = self.make_agent(FakeController())

        with self.assertRaises(StopResponse):
            await agent.on_user_turn_completed(
                FakeTurnContext(),
                SimpleNamespace(text_content="   "),
            )

    async def test_disabled_controller_keeps_existing_agent_behavior(self) -> None:
        agent = self.make_agent(None)
        turn_ctx = FakeTurnContext()

        await agent.on_user_turn_completed(
            turn_ctx,
            SimpleNamespace(text_content="Hello"),
        )

        self.assertEqual(turn_ctx.messages, [])

    def test_terminal_shutdown_is_consumed_once_after_speech(self) -> None:
        state = verification_state()
        state["should_end"] = True
        agent = self.make_agent(FakeController(state))

        self.assertFalse(
            agent.consume_terminal_shutdown(old_state="thinking", new_state="speaking")
        )
        self.assertFalse(
            agent.consume_terminal_shutdown(old_state="listening", new_state="speaking")
        )
        self.assertTrue(
            agent.consume_terminal_shutdown(old_state="speaking", new_state="listening")
        )
        self.assertFalse(
            agent.consume_terminal_shutdown(old_state="speaking", new_state="idle")
        )

    def test_non_terminal_speech_does_not_request_shutdown(self) -> None:
        agent = self.make_agent(FakeController())

        self.assertFalse(
            agent.consume_terminal_shutdown(old_state="speaking", new_state="listening")
        )

    def test_preexisting_speech_finish_does_not_skip_terminal_farewell(self) -> None:
        state = verification_state()
        state["should_end"] = True
        agent = self.make_agent(FakeController(state))

        self.assertFalse(
            agent.consume_terminal_shutdown(old_state="speaking", new_state="listening")
        )
        self.assertFalse(
            agent.consume_terminal_shutdown(old_state="thinking", new_state="speaking")
        )
        self.assertTrue(
            agent.consume_terminal_shutdown(old_state="speaking", new_state="idle")
        )

    def test_end_call_tool_owns_shutdown_without_fallback_duplication(self) -> None:
        state = verification_state()
        state["should_end"] = True
        agent = self.make_agent(FakeController(state))
        agent._hang_up_tool_called = True

        self.assertFalse(
            agent.consume_terminal_shutdown(old_state="listening", new_state="speaking")
        )
        self.assertFalse(
            agent.consume_terminal_shutdown(old_state="speaking", new_state="idle")
        )
        self.assertFalse(agent._terminal_shutdown_requested)


if __name__ == "__main__":
    unittest.main()
