from __future__ import annotations

import json
from pathlib import Path
import unittest

from voice_agent.conversation_fsm import (
    ConversationFSM,
    TurnIntent,
    create_initial_state,
    make_turn_event,
)
from voice_agent.fsm_adherence import evaluate_scenario_pack, evaluate_trace
from voice_agent.fsm_trace import FSMTraceRecorder


def case_fixture():
    return {
        "case_id": "case-001",
        "creditor_name": "Northwind",
        "customer_name": "Private Customer Ltd",
        "locale": "en-GB",
        "disclosure_summary": "an outstanding service charge",
        "product_name": "Private Product",
        "amount_minor": 2500,
        "currency": "GBP",
        "available_resolution_types": ["payment", "payment_plan", "case_review"],
    }


def passing_trace():
    ids = iter(["turn-1", "turn-2", "turn-3"])
    recorder = FSMTraceRecorder(call_id="call-test", id_factory=lambda: next(ids))
    fsm = ConversationFSM()
    state = fsm.advance(
        create_initial_state(case_fixture()),
        make_turn_event(TurnIntent.CALL_STARTED, source="system"),
    )
    recorder.record_opening(state)
    recorder.record_assistant_response("Hello. May I confirm who I am speaking with?")

    event = make_turn_event(
        TurnIntent.IDENTITY_CONFIRMED,
        verification_fields=["role", "name_and_first_surname"],
    )
    state = fsm.advance(state, event)
    recorder.record_transition(user_transcript="Yes, speaking.", event=event, state=state)
    recorder.record_assistant_response(
        "Thank you. I am calling about an outstanding service charge. Do you recognize it?"
    )

    event = make_turn_event(TurnIntent.EXPLICIT_TERMINATION)
    state = fsm.advance(state, event)
    recorder.record_transition(user_transcript="End the call.", event=event, state=state)
    recorder.record_assistant_response("Understood. Thank you for your time. Goodbye.")
    return recorder.events


class FSMAdherenceTests(unittest.TestCase):
    def test_checked_in_scenario_pack_passes_and_covers_every_phase_and_guard(self) -> None:
        root = Path(__file__).resolve().parent.parent
        pack = json.loads(
            (root / "specs/scenarios/fsm-adherence.json").read_text(encoding="utf-8")
        )

        report = evaluate_scenario_pack(pack, case=case_fixture())

        self.assertEqual(report.status, "pass", report.findings)
        self.assertEqual(set(report.phase_coverage), set(pack["requiredPhaseCoverage"]))
        self.assertEqual(set(report.guard_coverage), set(pack["requiredGlobalGuardCoverage"]))

    def test_valid_correlated_trace_passes(self) -> None:
        report = evaluate_trace(passing_trace(), case=case_fixture())

        self.assertEqual(report.status, "pass", report.findings)
        self.assertEqual(report.evaluated_turns, 3)

    def test_pre_verification_case_disclosure_fails(self) -> None:
        events = passing_trace()
        events[1]["assistantText"] = "This concerns Private Customer Ltd and Private Product."

        report = evaluate_trace(events, case=case_fixture())

        self.assertIn("pre_verification_disclosure", {item.code for item in report.findings})
        self.assertEqual(report.status, "fail")

    def test_missing_response_fails(self) -> None:
        events = [event for event in passing_trace() if event["turnId"] != "turn-2" or event["type"] != "assistant_response"]

        report = evaluate_trace(events, case=case_fixture())

        self.assertIn("missing_assistant_response", {item.code for item in report.findings})

    def test_terminal_guard_and_persuasion_are_deterministic_failures(self) -> None:
        events = passing_trace()
        terminal_transition = next(
            event for event in events
            if event["type"] == "fsm_transition" and event["turnId"] == "turn-3"
        )
        terminal_transition["toPhase"] = "resolution"
        terminal_transition["shouldEnd"] = False
        terminal_response = next(
            event for event in events
            if event["type"] == "assistant_response" and event["turnId"] == "turn-3"
        )
        terminal_response["assistantText"] = "Would you like to discuss payment options?"

        report = evaluate_trace(events, case=case_fixture())
        codes = {item.code for item in report.findings}

        self.assertIn("terminal_guard_failed", codes)
        self.assertIn("persuasion_after_close_directive", codes)

    def test_repeated_payment_refusal_without_close_fails(self) -> None:
        events = passing_trace()
        transitions = [
            event for event in events if event["type"] == "fsm_transition"
        ]
        transitions[1]["userTranscript"] = "No voy a pagar."
        transitions[2]["userTranscript"] = "Ya he dicho que no voy a pagar."
        transitions[2]["interpretedIntent"] = "disputes_case"
        transitions[2]["toPhase"] = "case_disclosure"
        transitions[2]["shouldEnd"] = False

        report = evaluate_trace(events, case=case_fixture())

        self.assertIn(
            "repeated_persuasion_after_refusal",
            {item.code for item in report.findings},
        )

    def test_simulated_case_review_claim_fails(self) -> None:
        events = passing_trace()
        transition = next(
            event
            for event in events
            if event["type"] == "fsm_transition" and event["turnId"] == "turn-2"
        )
        transition["directive"] = (
            "confirm_case_review_request_without_claiming_execution"
        )
        response = next(
            event
            for event in events
            if event["type"] == "assistant_response" and event["turnId"] == "turn-2"
        )
        response["assistantText"] = "Voy a revisar su caso ahora mismo."

        report = evaluate_trace(events, case=case_fixture())

        self.assertIn("simulated_case_review", {item.code for item in report.findings})

    def test_trace_allows_case_review_from_objection_to_confirmation(self) -> None:
        events = [
            {
                "version": 1,
                "type": "fsm_transition",
                "callId": "call-review",
                "turnId": "turn-review",
                "recordedAt": "2026-07-10T12:00:00+00:00",
                "userTranscript": "Yes, review it.",
                "interpretedIntent": "resolution_selected",
                "fromPhase": "objection_handling",
                "toPhase": "confirmation",
                "directive": "confirm_case_review_request_without_claiming_execution",
                "guardReason": None,
                "identityVerified": True,
                "refusalCount": 0,
                "resolutionType": "case_review",
                "shouldEnd": False,
                "interpreter": "deterministic_case_review_guard",
            },
            {
                "version": 1,
                "type": "assistant_response",
                "callId": "call-review",
                "turnId": "turn-review",
                "recordedAt": "2026-07-10T12:00:01+00:00",
                "assistantText": "Your review request has been recorded. Is that correct?",
                "conversationItemId": "item-review",
            },
        ]

        report = evaluate_trace(events, case=case_fixture())

        self.assertEqual(report.status, "pass", report.findings)

    def test_repeated_identical_response_fails_quality_check(self) -> None:
        events = []
        for index in range(2):
            turn_id = f"turn-loop-{index}"
            events.extend(
                [
                    {
                        "version": 1,
                        "type": "fsm_transition",
                        "callId": "call-loop",
                        "turnId": turn_id,
                        "recordedAt": f"2026-07-10T12:00:0{index}+00:00",
                        "userTranscript": "Claro.",
                        "interpretedIntent": "unknown",
                        "fromPhase": "objection_handling",
                        "toPhase": "objection_handling",
                        "directive": "clarify_and_review_objection",
                        "guardReason": None,
                        "identityVerified": True,
                        "refusalCount": 0,
                        "resolutionType": None,
                        "shouldEnd": False,
                        "interpreter": "openai_structured_output",
                    },
                    {
                        "version": 1,
                        "type": "assistant_response",
                        "callId": "call-loop",
                        "turnId": turn_id,
                        "recordedAt": f"2026-07-10T12:00:1{index}+00:00",
                        "assistantText": "Should I record your review request?",
                        "conversationItemId": f"item-loop-{index}",
                    },
                ]
            )

        report = evaluate_trace(events, case=case_fixture())

        self.assertIn("repetitive_response_loop", {item.code for item in report.findings})

    def test_stalled_phase_and_directive_fails_after_four_turns(self) -> None:
        events = []
        for index in range(4):
            turn_id = f"turn-stalled-{index}"
            events.extend(
                [
                    {
                        "version": 1,
                        "type": "fsm_transition",
                        "callId": "call-stalled",
                        "turnId": turn_id,
                        "recordedAt": f"2026-07-10T12:00:0{index}+00:00",
                        "userTranscript": f"Answer {index}",
                        "interpretedIntent": "unknown",
                        "fromPhase": "objection_handling",
                        "toPhase": "objection_handling",
                        "directive": "clarify_and_review_objection",
                        "guardReason": None,
                        "identityVerified": True,
                        "refusalCount": 0,
                        "resolutionType": None,
                        "shouldEnd": False,
                        "interpreter": "openai_structured_output",
                    },
                    {
                        "version": 1,
                        "type": "assistant_response",
                        "callId": "call-stalled",
                        "turnId": turn_id,
                        "recordedAt": f"2026-07-10T12:00:1{index}+00:00",
                        "assistantText": f"Please clarify point {index}.",
                        "conversationItemId": f"item-stalled-{index}",
                    },
                ]
            )

        report = evaluate_trace(events, case=case_fixture())

        self.assertIn("stalled_dialogue_loop", {item.code for item in report.findings})

    def test_premature_review_record_and_payment_mismatch_fail(self) -> None:
        events = [
            {
                "version": 1,
                "type": "fsm_transition",
                "callId": "call-quality",
                "turnId": "turn-premature",
                "recordedAt": "2026-07-10T12:00:00+00:00",
                "userTranscript": "I disagree.",
                "interpretedIntent": "disputes_case",
                "fromPhase": "objection_handling",
                "toPhase": "objection_handling",
                "directive": "clarify_and_review_objection",
                "guardReason": None,
                "identityVerified": True,
                "refusalCount": 0,
                "resolutionType": None,
                "shouldEnd": False,
                "interpreter": "openai_structured_output",
            },
            {
                "version": 1,
                "type": "assistant_response",
                "callId": "call-quality",
                "turnId": "turn-premature",
                "recordedAt": "2026-07-10T12:00:01+00:00",
                "assistantText": "Your review request has been recorded.",
                "conversationItemId": "item-premature",
            },
            {
                "version": 1,
                "type": "fsm_transition",
                "callId": "call-quality",
                "turnId": "turn-mismatch",
                "recordedAt": "2026-07-10T12:00:02+00:00",
                "userTranscript": "Yes, review it.",
                "interpretedIntent": "resolution_selected",
                "fromPhase": "objection_handling",
                "toPhase": "confirmation",
                "directive": "confirm_case_review_request_without_claiming_execution",
                "guardReason": None,
                "identityVerified": True,
                "refusalCount": 0,
                "resolutionType": "case_review",
                "shouldEnd": False,
                "interpreter": "openai_structured_output",
            },
            {
                "version": 1,
                "type": "assistant_response",
                "callId": "call-quality",
                "turnId": "turn-mismatch",
                "recordedAt": "2026-07-10T12:00:03+00:00",
                "assistantText": "Would you like payment options or a payment plan?",
                "conversationItemId": "item-mismatch",
            },
        ]

        report = evaluate_trace(events, case=case_fixture())
        codes = {item.code for item in report.findings}

        self.assertIn("premature_resolution_claim", codes)
        self.assertIn("case_review_confirmation_mismatch", codes)

    def test_unsupported_resolution_fails(self) -> None:
        events = passing_trace()
        events[2]["resolutionType"] = "invented_discount"

        report = evaluate_trace(events, case=case_fixture())

        self.assertIn("unsupported_resolution", {item.code for item in report.findings})

    def test_invented_installment_count_fails_deterministically(self) -> None:
        events = passing_trace()
        events[3]["assistantText"] = "We have agreed a payment plan over 12 installments."

        report = evaluate_trace(events, case=case_fixture())

        self.assertIn("unsupported_numeric_claim", {item.code for item in report.findings})

    def test_ordered_option_labels_are_not_numeric_claims(self) -> None:
        events = passing_trace()
        events[3]["assistantText"] = (
            "Choose an option:\n"
            "1. Pay now.\n"
            "2) Choose a date.\n"
            "3: Request a payment plan.\n"
            "4. Review the case."
        )

        report = evaluate_trace(events, case=case_fixture())

        self.assertNotIn(
            "unsupported_numeric_claim",
            {item.code for item in report.findings},
        )

    def test_number_inside_ordered_option_remains_a_claim(self) -> None:
        events = passing_trace()
        events[3]["assistantText"] = "1. Pay now.\n2. Pay over 12 installments."

        report = evaluate_trace(events, case=case_fixture())

        self.assertIn("unsupported_numeric_claim", {item.code for item in report.findings})

    def test_superseded_turn_does_not_require_fabricated_response(self) -> None:
        events = [
            event
            for event in passing_trace()
            if not (
                event["type"] == "assistant_response"
                and event["turnId"] == "turn-2"
            )
        ]
        events.append(
            {
                "version": 1,
                "type": "turn_superseded",
                "callId": "call-test",
                "turnId": "turn-2",
                "recordedAt": "2026-07-10T12:00:00+00:00",
                "supersedeReason": "new_user_turn_before_assistant_response",
            }
        )

        report = evaluate_trace(events, case=case_fixture())

        self.assertEqual(report.status, "pass", report.findings)

    def test_multiple_calls_reset_transition_continuity(self) -> None:
        first = passing_trace()
        second = passing_trace()
        for event in second:
            event["callId"] = "call-second"
            event["turnId"] = f"second-{event['turnId']}"

        report = evaluate_trace([*first, *second], case=case_fixture())

        self.assertEqual(report.status, "pass", report.findings)


if __name__ == "__main__":
    unittest.main()
