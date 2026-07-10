from __future__ import annotations

from types import SimpleNamespace
import unittest

from voice_agent.conversation_fsm import (
    ConversationFSM,
    TurnIntent,
    create_initial_state,
    make_turn_event,
)
from voice_agent.intent_interpreter import (
    InterpretedTurn,
    OpenAIIntentInterpreter,
    is_explicit_termination,
    is_contextual_outcome_confirmation,
)


def case_fixture():
    return {
        "case_id": "case-001",
        "creditor_name": "Northwind Services",
        "customer_name": "Private Customer Ltd",
        "locale": "en-GB",
        "disclosure_summary": "a private outstanding charge",
        "product_name": "Private Product",
        "amount_minor": 987654,
        "currency": "GBP",
        "reference": "PRIVATE-REFERENCE",
        "available_resolution_types": ["payment", "case_review"],
    }


def verification_state():
    fsm = ConversationFSM()
    return fsm.advance(
        create_initial_state(case_fixture()),
        make_turn_event(TurnIntent.CALL_STARTED, source="system"),
    )


class FakeResponses:
    def __init__(self, output=None, error: Exception | None = None) -> None:
        self.output = output
        self.error = error
        self.calls = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(output_parsed=self.output)


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


class OpenAIIntentInterpreterTests(unittest.IsolatedAsyncioTestCase):
    def build_interpreter(self, responses: FakeResponses) -> OpenAIIntentInterpreter:
        return OpenAIIntentInterpreter(
            api_key="test-key",
            model="gpt-4o-mini",
            timeout_seconds=1.0,
            client=FakeClient(responses),
        )

    async def test_parses_typed_intent_and_minimizes_case_data(self) -> None:
        responses = FakeResponses(
            InterpretedTurn(
                intent=TurnIntent.IDENTITY_CONFIRMED,
                objection_type=None,
                resolution_type=None,
            )
        )
        event = await self.build_interpreter(responses).interpret(
            "Yes, I am responsible for the account.",
            verification_state(),
        )

        self.assertEqual(event["intent"], TurnIntent.IDENTITY_CONFIRMED.value)
        self.assertEqual(event["evidence"]["interpreter"], "openai_structured_output")
        request = responses.calls[0]
        self.assertFalse(request["store"])
        self.assertIs(request["text_format"], InterpretedTurn)
        serialized_input = request["input"]
        for sensitive_value in (
            "Northwind Services",
            "Private Customer Ltd",
            "Private Product",
            "987654",
            "PRIVATE-REFERENCE",
            "private outstanding charge",
        ):
            self.assertNotIn(sensitive_value, serialized_input)

    async def test_api_error_fails_closed_to_unknown(self) -> None:
        responses = FakeResponses(error=RuntimeError("provider unavailable"))
        event = await self.build_interpreter(responses).interpret(
            "I have a question.",
            verification_state(),
        )

        self.assertEqual(event["intent"], TurnIntent.UNKNOWN.value)
        self.assertEqual(event["evidence"]["interpreter"], "safe_fallback")

    async def test_explicit_termination_bypasses_failed_api(self) -> None:
        responses = FakeResponses(error=RuntimeError("provider unavailable"))
        event = await self.build_interpreter(responses).interpret(
            "No me llame más, termine la llamada.",
            verification_state(),
        )

        self.assertEqual(event["intent"], TurnIntent.EXPLICIT_TERMINATION.value)
        self.assertEqual(responses.calls, [])

    def test_termination_detection_is_narrow(self) -> None:
        self.assertTrue(is_explicit_termination("Cuelgue, por favor."))
        self.assertTrue(is_explicit_termination("Please end this call."))
        self.assertFalse(is_explicit_termination("No puedo pagar ahora."))

    async def test_confirmation_signoff_bypasses_model_only_in_confirmation(self) -> None:
        state = verification_state()
        state["phase"] = "confirmation"
        responses = FakeResponses(error=RuntimeError("must not be called"))

        for transcript in ("Todo correcto.", "Gracias", "Buen día", "Agreed"):
            event = await self.build_interpreter(responses).interpret(transcript, state)
            self.assertEqual(event["intent"], TurnIntent.OUTCOME_CONFIRMED.value)
            self.assertEqual(
                event["evidence"]["interpreter"],
                "deterministic_confirmation_guard",
            )
        self.assertEqual(responses.calls, [])

    def test_confirmation_signoff_guard_is_phase_scoped(self) -> None:
        self.assertFalse(
            is_contextual_outcome_confirmation("Todo correcto", verification_state())
        )


if __name__ == "__main__":
    unittest.main()
