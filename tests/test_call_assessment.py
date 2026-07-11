from __future__ import annotations

import unittest

from voice_agent.call_assessment import assess_call
from voice_agent.conversation_fsm import CaseContext


CASE: CaseContext = {
    "case_id": "case-1",
    "creditor_name": "Example Co",
    "customer_name": "Customer",
    "locale": "en-GB",
    "disclosure_summary": "an account matter",
    "available_resolution_types": ["payment_plan"],
}


def transition_event(
    *,
    turn_id: str,
    from_phase: str,
    to_phase: str,
    intent: str,
    should_end: bool,
    interpreter: str = "openai_structured_output",
) -> dict[str, object]:
    return {
        "version": 1,
        "type": "fsm_transition",
        "callId": "call-1",
        "turnId": turn_id,
        "recordedAt": "2026-07-10T12:00:00+00:00",
        "userTranscript": "",
        "interpretedIntent": intent,
        "fromPhase": from_phase,
        "toPhase": to_phase,
        "directive": (
            "close_without_further_persuasion"
            if should_end
            else "verify_identity"
        ),
        "guardReason": None,
        "identityVerified": False,
        "refusalCount": 0,
        "resolutionType": None,
        "shouldEnd": should_end,
        "interpreter": interpreter,
    }


def response_event(turn_id: str) -> dict[str, object]:
    return {
        "version": 1,
        "type": "assistant_response",
        "callId": "call-1",
        "turnId": turn_id,
        "recordedAt": "2026-07-10T12:00:01+00:00",
        "assistantText": "Thank you. Goodbye.",
        "conversationItemId": f"message-{turn_id}",
    }


def projected_transition(
    *, turn_id: str, should_end: bool, response_recorded: bool
) -> dict[str, object]:
    return {
        "turn_id": turn_id,
        "should_end": should_end,
        "response_recorded": response_recorded,
    }


class CallAssessmentTests(unittest.TestCase):
    def test_non_terminal_call_is_not_scored(self) -> None:
        result = assess_call(
            events=[],
            fsm_state={"phase": "confirmation", "should_end": False},
            transitions=[
                projected_transition(
                    turn_id="turn-1", should_end=False, response_recorded=True
                )
            ],
            case=CASE,
        )

        self.assertEqual(result["status"], "in_progress")
        self.assertIsNone(result["satisfactory"])
        self.assertEqual(result["adherence_status"], "not_evaluated")

    def test_terminal_call_waits_for_final_response_evidence(self) -> None:
        result = assess_call(
            events=[],
            fsm_state={"phase": "ended", "should_end": True},
            transitions=[
                projected_transition(
                    turn_id="turn-1", should_end=True, response_recorded=False
                )
            ],
            case=CASE,
        )

        self.assertEqual(result["status"], "finalizing")
        self.assertIsNone(result["satisfactory"])

    def test_completed_adherent_call_is_satisfactory(self) -> None:
        events = [
            transition_event(
                turn_id="turn-1",
                from_phase="opening",
                to_phase="identity_verification",
                intent="call_started",
                should_end=False,
            ),
            response_event("turn-1"),
            transition_event(
                turn_id="turn-2",
                from_phase="identity_verification",
                to_phase="ended",
                intent="explicit_termination",
                should_end=True,
            ),
            response_event("turn-2"),
        ]
        result = assess_call(
            events=events,
            fsm_state={"phase": "ended", "should_end": True},
            transitions=[
                projected_transition(
                    turn_id="turn-1", should_end=False, response_recorded=True
                ),
                projected_transition(
                    turn_id="turn-2", should_end=True, response_recorded=True
                ),
            ],
            case=CASE,
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["label"], "Satisfactory")
        self.assertTrue(result["satisfactory"])
        self.assertEqual(result["response_coverage"], "2/2")
        self.assertEqual(result["adherence_status"], "pass")
        self.assertEqual(result["conversation_quality_status"], "pass")

    def test_failed_trace_is_unsatisfactory_with_action(self) -> None:
        events = [
            transition_event(
                turn_id="turn-1",
                from_phase="opening",
                to_phase="identity_verification",
                intent="call_started",
                should_end=False,
            ),
            transition_event(
                turn_id="turn-2",
                from_phase="identity_verification",
                to_phase="ended",
                intent="explicit_termination",
                should_end=True,
            ),
            response_event("turn-2"),
        ]
        result = assess_call(
            events=events,
            fsm_state={"phase": "ended", "should_end": True},
            transitions=[
                projected_transition(
                    turn_id="turn-1", should_end=False, response_recorded=False
                ),
                projected_transition(
                    turn_id="turn-2", should_end=True, response_recorded=True
                ),
            ],
            case=CASE,
        )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["label"], "Unsatisfactory")
        self.assertFalse(result["satisfactory"])
        self.assertIn(
            "Record exactly one assistant response for every FSM transition.",
            result["improvements"],
        )

    def test_interpreter_fallback_requires_review(self) -> None:
        events = [
            transition_event(
                turn_id="turn-1",
                from_phase="opening",
                to_phase="ended",
                intent="explicit_termination",
                should_end=True,
                interpreter="safe_fallback",
            ),
            response_event("turn-1"),
        ]
        result = assess_call(
            events=events,
            fsm_state={"phase": "ended", "should_end": True},
            transitions=[
                projected_transition(
                    turn_id="turn-1", should_end=True, response_recorded=True
                )
            ],
            case=CASE,
        )

        self.assertEqual(result["status"], "warn")
        self.assertEqual(result["label"], "Needs review")
        self.assertFalse(result["satisfactory"])
        self.assertIn("intent-interpreter reliability", result["improvements"][0])
        self.assertEqual(result["adherence_status"], "pass")
        self.assertEqual(result["conversation_quality_status"], "warn")

    def test_structural_pass_and_quality_fail_are_shown_separately(self) -> None:
        events: list[dict[str, object]] = []
        for index in range(2):
            turn_id = f"turn-loop-{index}"
            events.extend(
                [
                    {
                        "version": 1,
                        "type": "fsm_transition",
                        "callId": "call-1",
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
                        "callId": "call-1",
                        "turnId": turn_id,
                        "recordedAt": f"2026-07-10T12:00:1{index}+00:00",
                        "assistantText": "Should I record your review request?",
                        "conversationItemId": f"item-loop-{index}",
                    },
                ]
            )
        events.extend(
            [
                {
                    **transition_event(
                        turn_id="turn-end",
                        from_phase="objection_handling",
                        to_phase="ended",
                        intent="explicit_termination",
                        should_end=True,
                    ),
                    "identityVerified": True,
                },
                response_event("turn-end"),
            ]
        )

        result = assess_call(
            events=events,
            fsm_state={"phase": "ended", "should_end": True},
            transitions=[
                projected_transition(
                    turn_id="turn-loop-0", should_end=False, response_recorded=True
                ),
                projected_transition(
                    turn_id="turn-loop-1", should_end=False, response_recorded=True
                ),
                projected_transition(
                    turn_id="turn-end", should_end=True, response_recorded=True
                ),
            ],
            case=CASE,
        )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["adherence_status"], "pass")
        self.assertEqual(result["conversation_quality_status"], "fail")
        evidence = {item["label"]: item["status"] for item in result["evidence"]}
        self.assertEqual(evidence["FSM adherence"], "pass")
        self.assertEqual(evidence["Conversation quality"], "fail")

    def test_coalesced_turn_is_excluded_from_response_denominator(self) -> None:
        events = [
            transition_event(
                turn_id="turn-1",
                from_phase="opening",
                to_phase="identity_verification",
                intent="call_started",
                should_end=False,
            ),
            {
                "version": 1,
                "type": "turn_superseded",
                "callId": "call-1",
                "turnId": "turn-1",
                "recordedAt": "2026-07-10T12:00:00+00:00",
                "supersedeReason": "new_user_turn_before_assistant_response",
            },
            transition_event(
                turn_id="turn-2",
                from_phase="identity_verification",
                to_phase="ended",
                intent="explicit_termination",
                should_end=True,
            ),
            response_event("turn-2"),
        ]
        result = assess_call(
            events=events,
            fsm_state={"phase": "ended", "should_end": True},
            transitions=[
                {
                    **projected_transition(
                        turn_id="turn-1",
                        should_end=False,
                        response_recorded=False,
                    ),
                    "response_disposition": "coalesced",
                },
                {
                    **projected_transition(
                        turn_id="turn-2",
                        should_end=True,
                        response_recorded=True,
                    ),
                    "response_disposition": "recorded",
                },
            ],
            case=CASE,
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["response_coverage"], "1/1")
        self.assertEqual(result["coalesced_turns"], 1)
        self.assertIn("1 coalesced", result["evidence"][1]["value"])


if __name__ == "__main__":
    unittest.main()
