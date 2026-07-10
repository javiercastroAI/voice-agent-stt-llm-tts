from __future__ import annotations

import unittest

from voice_agent.conversation_controller import (
    ConversationAlreadyEnded,
    ConversationController,
    build_runtime_control_message,
)
from voice_agent.conversation_fsm import CallPhase, TurnIntent, make_turn_event


def case_fixture():
    return {
        "case_id": "case-001",
        "creditor_name": "Northwind Services",
        "customer_name": "Private Customer Ltd",
        "locale": "en-GB",
        "disclosure_summary": "an outstanding service charge",
        "amount_minor": 2500,
        "currency": "GBP",
        "available_resolution_types": ["payment", "case_review"],
        "metadata": {"internal_note": "never expose this value"},
    }


class QueueInterpreter:
    def __init__(self, *intents: TurnIntent) -> None:
        self.intents = list(intents)
        self.calls = []

    async def interpret(self, transcript, state):
        self.calls.append((transcript, state["phase"]))
        intent = self.intents.pop(0)
        if intent is TurnIntent.RESOLUTION_SELECTED:
            return make_turn_event(intent, resolution_type="payment")
        return make_turn_event(intent)


class ConversationControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_initializes_after_call_started_event(self) -> None:
        controller = ConversationController(
            case=case_fixture(),
            interpreter=QueueInterpreter(TurnIntent.UNKNOWN),
        )

        self.assertEqual(controller.state["phase"], CallPhase.IDENTITY_VERIFICATION.value)
        self.assertEqual(len(controller.state["transition_history"]), 1)

    async def test_interprets_then_advances_fsm(self) -> None:
        interpreter = QueueInterpreter(TurnIntent.IDENTITY_CONFIRMED)
        controller = ConversationController(case=case_fixture(), interpreter=interpreter)

        state = await controller.process_user_turn("Yes, that is me.")

        self.assertEqual(interpreter.calls[0][1], CallPhase.IDENTITY_VERIFICATION.value)
        self.assertEqual(state["phase"], CallPhase.CASE_DISCLOSURE.value)
        self.assertTrue(state["identity_verified"])

    async def test_runtime_message_is_disclosure_safe(self) -> None:
        controller = ConversationController(
            case=case_fixture(),
            interpreter=QueueInterpreter(TurnIntent.IDENTITY_CONFIRMED),
        )
        before_verification = build_runtime_control_message(controller.state)
        self.assertNotIn("Private Customer Ltd", before_verification)
        self.assertNotIn("2500", before_verification)

        verified = await controller.process_user_turn("Yes, that is me.")
        after_verification = build_runtime_control_message(verified)
        self.assertIn("Private Customer Ltd", after_verification)
        self.assertIn("2500", after_verification)
        self.assertNotIn("never expose this value", after_verification)

    async def test_terminal_runtime_message_requires_end_call_tool(self) -> None:
        controller = ConversationController(
            case=case_fixture(),
            interpreter=QueueInterpreter(TurnIntent.EXPLICIT_TERMINATION),
        )
        ended = await controller.process_user_turn("End the call.")

        control = build_runtime_control_message(ended)

        self.assertIn("call the `end_call` tool now", control)
        self.assertIn("Do not ask another question", control)

    async def test_spanish_runtime_message_forbids_artificial_system_wait(self) -> None:
        controller = ConversationController(
            case=case_fixture(),
            interpreter=QueueInterpreter(TurnIntent.UNKNOWN),
        )
        controller._state["case"]["locale"] = "es-ES"

        control = build_runtime_control_message(controller.state)

        self.assertIn("Estoy comprobando el sistema. Ah, de acuerdo.", control)
        self.assertIn("never simulate a background lookup", control)
        self.assertIn("in this same response", control)

    async def test_post_terminal_turn_is_rejected_without_interpretation(self) -> None:
        interpreter = QueueInterpreter(
            TurnIntent.IDENTITY_CONFIRMED,
            TurnIntent.RESOLUTION_SELECTED,
            TurnIntent.OUTCOME_CONFIRMED,
        )
        controller = ConversationController(case=case_fixture(), interpreter=interpreter)
        await controller.process_user_turn("Yes, that is me.")
        controller._state["phase"] = CallPhase.RESOLUTION.value
        selected = await controller.process_user_turn("Payment.")
        self.assertEqual(selected["phase"], CallPhase.CONFIRMATION.value)
        ended = await controller.process_user_turn("Confirmed.")
        self.assertTrue(ended["should_end"])

        with self.assertRaises(ConversationAlreadyEnded):
            await controller.process_user_turn("Thanks again.")
        self.assertEqual(len(interpreter.calls), 3)


if __name__ == "__main__":
    unittest.main()
