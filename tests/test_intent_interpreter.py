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
    is_clear_case_dispute,
    is_explicit_termination,
    is_contextual_case_review_acceptance,
    is_contextual_outcome_confirmation,
    explicit_resolution_selection,
    is_payment_refusal,
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


def objection_state():
    fsm = ConversationFSM()
    state = verification_state()
    state = fsm.advance(
        state,
        make_turn_event(
            TurnIntent.IDENTITY_CONFIRMED,
            verification_fields=["role", "name_and_first_surname"],
        ),
    )
    return fsm.advance(state, make_turn_event(TurnIntent.DISPUTES_CASE))


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
                verified_fields=["role", "name_and_first_surname", "invented_field"],
            )
        )
        event = await self.build_interpreter(responses).interpret(
            "My name is Javier Pérez and I am the managing director.",
            verification_state(),
        )

        self.assertEqual(event["intent"], TurnIntent.IDENTITY_CONFIRMED.value)
        self.assertEqual(
            event["verification_fields"],
            ["role", "name_and_first_surname"],
        )
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

    async def test_bare_identity_confirmation_cannot_invent_verification_fields(self) -> None:
        responses = FakeResponses(
            InterpretedTurn(
                intent=TurnIntent.IDENTITY_CONFIRMED,
                verified_fields=["role", "name_and_first_surname"],
            )
        )

        event = await self.build_interpreter(responses).interpret(
            "Sí, soy yo.",
            verification_state(),
        )

        self.assertEqual(event["intent"], TurnIntent.IDENTITY_CONFIRMED.value)
        self.assertEqual(event["verification_fields"], [])

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

        for transcript in ("Todo correcto.", "Confirmo", "Sí, de acuerdo", "Agreed"):
            event = await self.build_interpreter(responses).interpret(transcript, state)
            self.assertEqual(event["intent"], TurnIntent.OUTCOME_CONFIRMED.value)
            self.assertEqual(
                event["evidence"]["interpreter"],
                "deterministic_confirmation_guard",
            )
        self.assertEqual(responses.calls, [])

    async def test_ambiguous_terminal_confirmation_fails_closed(self) -> None:
        state = verification_state()
        state["phase"] = "confirmation"
        responses = FakeResponses(InterpretedTurn(intent=TurnIntent.OUTCOME_CONFIRMED))

        event = await self.build_interpreter(responses).interpret("Básicamente", state)

        self.assertEqual(event["intent"], TurnIntent.UNKNOWN.value)
        self.assertEqual(event["evidence"]["interpreter"], "terminal_confirmation_rejected")

    def test_confirmation_signoff_guard_is_phase_scoped(self) -> None:
        self.assertFalse(
            is_contextual_outcome_confirmation("Todo correcto", verification_state())
        )

    async def test_explicit_payment_selection_bypasses_model(self) -> None:
        state = verification_state()
        state["phase"] = "resolution"
        responses = FakeResponses(error=RuntimeError("must not be called"))

        event = await self.build_interpreter(responses).interpret("Pago inmediato.", state)

        self.assertEqual(event["intent"], TurnIntent.RESOLUTION_SELECTED.value)
        self.assertEqual(event["resolution_type"], "payment")
        self.assertEqual(event["evidence"]["interpreter"], "deterministic_resolution_selection_guard")
        self.assertEqual(responses.calls, [])
        self.assertEqual(explicit_resolution_selection("Pago inmediato", state), "payment")

    async def test_payment_refusal_variants_bypass_model(self) -> None:
        responses = FakeResponses(error=RuntimeError("must not be called"))
        state = objection_state()

        for transcript in (
            "No voy a pagar.",
            "Ya te he dicho que no pienso pagar.",
            "Non voi a pagar.",
            "Novojapar.",
            "I refuse to pay.",
        ):
            event = await self.build_interpreter(responses).interpret(transcript, state)
            self.assertEqual(event["intent"], TurnIntent.REFUSAL.value)
            self.assertEqual(
                event["evidence"]["interpreter"],
                "deterministic_payment_refusal_guard",
            )
        self.assertEqual(responses.calls, [])

    async def test_contextual_case_review_acceptance_bypasses_model(self) -> None:
        responses = FakeResponses(error=RuntimeError("must not be called"))
        state = objection_state()

        for transcript in ("Sí.", "Sí, revíselo.", "Review it."):
            event = await self.build_interpreter(responses).interpret(transcript, state)
            self.assertEqual(event["intent"], TurnIntent.OUTCOME_CONFIRMED.value)
            self.assertEqual(event["resolution_type"], "case_review")
        self.assertEqual(responses.calls, [])

    async def test_extended_case_review_confirmations_bypass_model(self) -> None:
        responses = FakeResponses(error=RuntimeError("must not be called"))
        state = objection_state()

        for transcript in (
            "Es correcto, correctísimo, diría yo.",
            "Claro.",
            "Sí, claro, ya se lo he dicho.",
        ):
            event = await self.build_interpreter(responses).interpret(transcript, state)
            self.assertEqual(event["intent"], TurnIntent.OUTCOME_CONFIRMED.value)
            self.assertEqual(event["resolution_type"], "case_review")
        self.assertEqual(responses.calls, [])

    async def test_bare_responsible_party_answer_does_not_count_as_refusal(self) -> None:
        responses = FakeResponses(error=RuntimeError("must not be called"))

        event = await self.build_interpreter(responses).interpret(
            "Habla con la persona responsable.",
            verification_state(),
        )

        self.assertEqual(event["intent"], TurnIntent.IDENTITY_CONFIRMED.value)
        self.assertEqual(event["verification_fields"], [])
        self.assertEqual(event["evidence"]["interpreter"], "deterministic_identity_guard")
        self.assertEqual(responses.calls, [])

    async def test_clear_case_dispute_bypasses_model(self) -> None:
        responses = FakeResponses(error=RuntimeError("must not be called"))
        state = objection_state()

        event = await self.build_interpreter(responses).interpret(
            "Pero no puede ser.",
            state,
        )

        self.assertEqual(event["intent"], TurnIntent.DISPUTES_CASE.value)
        self.assertEqual(
            event["evidence"]["interpreter"],
            "deterministic_dispute_guard",
        )
        self.assertEqual(responses.calls, [])

    def test_contextual_guards_are_phase_scoped(self) -> None:
        state = verification_state()

        self.assertFalse(is_payment_refusal("No voy a pagar", state))
        self.assertFalse(is_contextual_case_review_acceptance("Sí", state))
        self.assertFalse(is_clear_case_dispute("No puede ser", state))


if __name__ == "__main__":
    unittest.main()
