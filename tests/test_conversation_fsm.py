from __future__ import annotations

import json
from pathlib import Path
import unittest

from voice_agent.conversation_fsm import (
    CallPhase,
    CaseContext,
    ConversationFSM,
    DEFAULT_POLICY,
    PHASE_TRANSITIONS,
    TRANSITION_REGISTRY,
    TurnIntent,
    create_initial_state,
    make_turn_event,
    render_business_graph,
    response_context,
    validate_transition_registry,
)


def case_fixture(
    *,
    case_id: str = "case-001",
    creditor: str = "Northwind Services",
    customer: str = "Example Customer Ltd",
) -> CaseContext:
    return {
        "case_id": case_id,
        "creditor_name": creditor,
        "customer_name": customer,
        "locale": "en-GB",
        "disclosure_summary": "an outstanding monthly service charge",
        "amount_minor": 12500,
        "currency": "GBP",
        "product_name": "Managed Service",
        "available_resolution_types": [
            "immediate_payment",
            "payment_date",
            "payment_plan",
            "case_review",
        ],
    }


class ConversationFSMTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fsm = ConversationFSM()
        self.state = create_initial_state(case_fixture())

    def advance(self, intent: TurnIntent, **kwargs):
        self.state = self.fsm.advance(
            self.state,
            make_turn_event(intent, **kwargs),
        )
        return self.state

    def verify_identity(self) -> None:
        self.advance(TurnIntent.CALL_STARTED, source="system")
        self.advance(
            TurnIntent.IDENTITY_CONFIRMED,
            verification_fields=list(DEFAULT_POLICY["verification_fields"]),
        )

    def test_opening_moves_to_identity_verification(self) -> None:
        state = self.advance(TurnIntent.CALL_STARTED, source="system")

        self.assertEqual(state["phase"], CallPhase.IDENTITY_VERIFICATION.value)
        self.assertFalse(state["identity_verified"])
        self.assertEqual(state["response_directive"], "open_and_verify_identity")

    def test_reason_request_does_not_disclose_case_context(self) -> None:
        self.advance(TurnIntent.CALL_STARTED, source="system")
        state = self.advance(TurnIntent.ASKS_REASON)

        self.assertEqual(state["phase"], CallPhase.IDENTITY_VERIFICATION.value)
        self.assertEqual(
            state["response_directive"],
            "give_pre_verification_reason_and_verify",
        )
        safe_context = response_context(state)
        self.assertNotIn("case", safe_context)
        self.assertNotIn("customer_name", json.dumps(safe_context))
        self.assertNotIn("disclosure_summary", json.dumps(safe_context))

    def test_verified_identity_allows_case_disclosure(self) -> None:
        self.verify_identity()

        self.assertTrue(self.state["identity_verified"])
        self.assertEqual(self.state["phase"], CallPhase.CASE_DISCLOSURE.value)
        self.assertIn("case", response_context(self.state))

    def test_identity_gate_waits_for_every_configured_field(self) -> None:
        self.advance(TurnIntent.CALL_STARTED, source="system")

        bare_confirmation = self.advance(
            TurnIntent.IDENTITY_CONFIRMED,
            verification_fields=[],
        )
        self.assertFalse(bare_confirmation["identity_verified"])
        self.assertEqual(
            bare_confirmation["response_directive"],
            "verify_remaining_identity_fields",
        )

        partial = self.advance(
            TurnIntent.IDENTITY_CONFIRMED,
            verification_fields=["name_and_first_surname"],
        )
        self.assertFalse(partial["identity_verified"])
        self.assertEqual(partial["verified_fields"], ["name_and_first_surname"])
        self.assertNotIn("case", response_context(partial))

        complete = self.advance(
            TurnIntent.IDENTITY_CONFIRMED,
            verification_fields=["role"],
        )
        self.assertTrue(complete["identity_verified"])
        self.assertEqual(complete["phase"], CallPhase.CASE_DISCLOSURE.value)

    def test_invariant_blocks_sensitive_phase_without_identity(self) -> None:
        self.state["phase"] = CallPhase.CASE_DISCLOSURE.value
        state = self.advance(TurnIntent.CASE_DISCLOSED, source="system")

        self.assertEqual(state["phase"], CallPhase.IDENTITY_VERIFICATION.value)
        self.assertEqual(
            state["guard_reason"],
            "identity_required_before_case_disclosure",
        )
        self.assertNotIn("case", response_context(state))

    def test_recognized_case_routes_to_resolution(self) -> None:
        self.verify_identity()
        state = self.advance(TurnIntent.RECOGNIZES_CASE)

        self.assertEqual(state["phase"], CallPhase.RESOLUTION.value)
        self.assertEqual(
            state["response_directive"],
            "offer_case_approved_resolutions",
        )

    def test_dispute_routes_to_generic_objection_handling(self) -> None:
        self.verify_identity()
        state = self.advance(
            TurnIntent.OBJECTION_PROVIDED,
            objection_type="already_paid",
        )

        self.assertEqual(state["phase"], CallPhase.OBJECTION_HANDLING.value)
        self.assertEqual(state["objection_type"], "already_paid")

    def test_only_case_approved_resolution_can_be_selected(self) -> None:
        self.verify_identity()
        self.advance(TurnIntent.RECOGNIZES_CASE)
        state = self.advance(
            TurnIntent.RESOLUTION_SELECTED,
            resolution_type="unsupported_discount",
        )

        self.assertEqual(state["phase"], CallPhase.RESOLUTION.value)
        self.assertIsNone(state["resolution_type"])
        self.assertEqual(state["guard_reason"], "unsupported_resolution_type")

        state = self.advance(
            TurnIntent.RESOLUTION_SELECTED,
            resolution_type="payment_plan",
        )
        self.assertEqual(state["phase"], CallPhase.CONFIRMATION.value)
        self.assertEqual(state["resolution_type"], "payment_plan")

    def test_confirmation_completes_call(self) -> None:
        self.verify_identity()
        self.advance(TurnIntent.RECOGNIZES_CASE)
        self.advance(
            TurnIntent.RESOLUTION_SELECTED,
            resolution_type="payment_date",
        )
        state = self.advance(TurnIntent.OUTCOME_CONFIRMED)

        self.assertEqual(state["phase"], CallPhase.ENDED.value)
        self.assertTrue(state["should_end"])

    def test_immediate_payment_directive_forbids_credential_request(self) -> None:
        self.verify_identity()
        self.advance(TurnIntent.RECOGNIZES_CASE)
        state = self.advance(
            TurnIntent.RESOLUTION_SELECTED,
            resolution_type="immediate_payment",
        )

        self.assertEqual(state["phase"], CallPhase.CONFIRMATION.value)
        self.assertEqual(
            state["response_directive"],
            "confirm_immediate_payment_commitment_without_requesting_payment_credentials",
        )

    def test_case_review_can_be_selected_directly_from_objection_handling(self) -> None:
        self.verify_identity()
        self.advance(TurnIntent.DISPUTES_CASE)

        state = self.advance(
            TurnIntent.RESOLUTION_SELECTED,
            resolution_type="case_review",
        )

        self.assertEqual(state["phase"], CallPhase.CONFIRMATION.value)
        self.assertEqual(state["resolution_type"], "case_review")
        self.assertEqual(
            state["response_directive"],
            "confirm_case_review_request_without_claiming_execution",
        )

    def test_contextual_case_review_confirmation_closes_from_objection(self) -> None:
        self.verify_identity()
        self.advance(TurnIntent.DISPUTES_CASE)

        state = self.advance(
            TurnIntent.OUTCOME_CONFIRMED,
            resolution_type="case_review",
        )

        self.assertEqual(state["phase"], CallPhase.ENDED.value)
        self.assertEqual(state["resolution_type"], "case_review")
        self.assertEqual(state["response_directive"], "confirm_outcome_and_close")
        self.assertTrue(state["should_end"])

    def test_explicit_termination_ends_from_every_phase(self) -> None:
        for phase in CallPhase:
            with self.subTest(phase=phase.value):
                state = create_initial_state(case_fixture())
                state["phase"] = phase.value
                if phase.value in {
                    CallPhase.CASE_DISCLOSURE.value,
                    CallPhase.RECOGNITION.value,
                    CallPhase.OBJECTION_HANDLING.value,
                    CallPhase.RESOLUTION.value,
                    CallPhase.CONFIRMATION.value,
                }:
                    state["identity_verified"] = True
                result = self.fsm.advance(
                    state,
                    make_turn_event(TurnIntent.EXPLICIT_TERMINATION),
                )
                self.assertEqual(result["phase"], CallPhase.ENDED.value)
                self.assertTrue(result["should_end"])

    def test_wrong_party_ends_without_disclosure(self) -> None:
        self.advance(TurnIntent.CALL_STARTED, source="system")
        state = self.advance(TurnIntent.WRONG_PARTY)

        self.assertEqual(state["phase"], CallPhase.ENDED.value)
        self.assertFalse(state["identity_verified"])
        self.assertEqual(
            state["response_directive"],
            "close_wrong_party_without_disclosure",
        )
        self.assertNotIn("case", response_context(state))

    def test_refusal_limit_is_deterministic(self) -> None:
        self.advance(TurnIntent.CALL_STARTED, source="system")
        first = self.advance(TurnIntent.IDENTITY_REFUSED)
        self.assertEqual(first["refusal_count"], 1)
        self.assertFalse(first["should_end"])
        self.assertEqual(
            first["response_directive"],
            "acknowledge_refusal_and_offer_one_clear_choice",
        )

        second = self.advance(TurnIntent.IDENTITY_REFUSED)
        self.assertEqual(second["refusal_count"], DEFAULT_POLICY["max_refusals"])
        self.assertEqual(second["phase"], CallPhase.ENDED.value)
        self.assertTrue(second["should_end"])

    def test_human_and_vulnerability_signals_escalate(self) -> None:
        for intent in (
            TurnIntent.REQUESTS_HUMAN,
            TurnIntent.VULNERABILITY_DETECTED,
        ):
            with self.subTest(intent=intent.value):
                state = self.fsm.advance(
                    create_initial_state(case_fixture()),
                    make_turn_event(intent),
                )
                self.assertEqual(state["phase"], CallPhase.ESCALATION.value)
                self.assertFalse(state["should_end"])

    def test_same_graph_accepts_unrelated_case_contexts(self) -> None:
        first = create_initial_state(case_fixture())
        second = create_initial_state(
            case_fixture(
                case_id="case-XYZ",
                creditor="Fabrikam Utilities",
                customer="Different Customer PLC",
            )
        )

        first = self.fsm.advance(first, make_turn_event(TurnIntent.CALL_STARTED))
        second = self.fsm.advance(second, make_turn_event(TurnIntent.CALL_STARTED))

        self.assertEqual(first["phase"], second["phase"])
        self.assertNotEqual(first["case"]["case_id"], second["case"]["case_id"])

    def test_transition_history_is_auditable(self) -> None:
        self.advance(TurnIntent.CALL_STARTED, source="system")
        self.advance(
            TurnIntent.IDENTITY_CONFIRMED,
            verification_fields=list(DEFAULT_POLICY["verification_fields"]),
        )

        self.assertEqual(len(self.state["transition_history"]), 2)
        self.assertEqual(
            self.state["transition_history"][-1],
            {
                "transition_id": "identity_complete",
                "from_phase": CallPhase.IDENTITY_VERIFICATION.value,
                "to_phase": CallPhase.CASE_DISCLOSURE.value,
                "intent": TurnIntent.IDENTITY_CONFIRMED.value,
                "directive": "disclose_case_and_ask_recognition",
                "guard_reason": None,
            },
        )

    def test_machine_spec_matches_runtime_phases(self) -> None:
        root = Path(__file__).resolve().parent.parent
        spec = json.loads(
            (root / "specs/system/conversation-fsm.json").read_text(encoding="utf-8")
        )

        self.assertEqual(spec["phases"], [phase.value for phase in CallPhase])
        self.assertEqual(
            spec["transitionSource"],
            "voice_agent.conversation_fsm.TRANSITION_REGISTRY",
        )

    def test_transition_registry_has_unique_ids_and_phase_fallbacks(self) -> None:
        validate_transition_registry()
        self.assertEqual(
            len({transition.id for transition in TRANSITION_REGISTRY}),
            len(TRANSITION_REGISTRY),
        )
        for phase in CallPhase:
            fallbacks = [
                transition
                for transition in PHASE_TRANSITIONS
                if transition.source is phase and not transition.intents
            ]
            self.assertEqual(len(fallbacks), 1, phase.value)

    def test_generated_business_graph_matches_registry(self) -> None:
        root = Path(__file__).resolve().parent.parent
        graph_path = root / "docs/generated/fsm-business-graph.md"
        self.assertEqual(graph_path.read_text(encoding="utf-8"), render_business_graph())
        graph = render_business_graph()
        for transition in TRANSITION_REGISTRY:
            if transition.diagram:
                source = "ANY" if transition.source is None else transition.source.name
                self.assertIn(f'{source} -->|"{transition.id}:', graph)
                self.assertIn(f'| {transition.target.name}', graph)

    def test_runtime_contains_no_demo_case_values(self) -> None:
        source = Path(__file__).resolve().parent.parent / "voice_agent/conversation_fsm.py"
        content = source.read_text(encoding="utf-8")

        self.assertNotIn("Al Corriente", content)
        self.assertNotIn("CloudX", content)
        self.assertNotIn("1527", content)


class ConversationFSMValidationTests(unittest.TestCase):
    def test_rejects_missing_case_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "customer_name"):
            create_initial_state(
                {
                    "case_id": "case-1",
                    "creditor_name": "Creditor",
                    "customer_name": "",
                    "locale": "en-GB",
                    "disclosure_summary": "summary",
                    "available_resolution_types": [],
                }
            )

    def test_rejects_unknown_intent(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown turn intent"):
            make_turn_event("model_invented_transition")

    def test_checkpointed_graph_requires_thread_id(self) -> None:
        from langgraph.checkpoint.memory import InMemorySaver

        fsm = ConversationFSM(checkpointer=InMemorySaver())
        state = create_initial_state(case_fixture())

        with self.assertRaisesRegex(ValueError, "thread_id"):
            fsm.advance(state, make_turn_event(TurnIntent.CALL_STARTED))


if __name__ == "__main__":
    unittest.main()
