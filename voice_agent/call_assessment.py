"""Deterministic end-of-call assessment for the live dashboard."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .conversation_fsm import CaseContext
from .fsm_adherence import AdherenceFinding, evaluate_trace


_IMPROVEMENTS = {
    "invalid_trace_event": "Preserve call and turn identifiers on every trace event.",
    "unknown_trace_event": "Restrict runtime evidence to supported FSM trace events.",
    "orphan_response": "Correlate every assistant response with its triggering FSM turn.",
    "stale_or_discontinuous_state": "Serialize turns so each transition starts from the latest FSM state.",
    "invalid_phase_transition": "Route the turn through an allowed FSM transition.",
    "identity_gate_bypassed": "Keep case disclosure behind successful identity verification.",
    "terminal_guard_failed": "Apply terminal guards in the same turn and stop further dialogue.",
    "unsupported_resolution": "Offer only resolution types approved by the loaded case.",
    "missing_assistant_response": "Record exactly one assistant response for every FSM transition.",
    "duplicate_assistant_response": "Prevent duplicate assistant responses for a single FSM turn.",
    "pre_verification_disclosure": "Remove case-sensitive details from pre-verification responses.",
    "unsupported_numeric_claim": "Ground every numeric claim in the validated case context.",
    "persuasion_after_close_directive": "End with one farewell and do not ask another question.",
    "interpreter_fallback": "Review intent-interpreter reliability for the affected turn.",
    "repeated_persuasion_after_refusal": "End the call after the configured refusal limit instead of repeating persuasion.",
    "simulated_case_review": "Confirm that the review request was recorded without claiming an unequipped review ran.",
    "stalled_dialogue_loop": "Stop repeating the same phase and directive; resolve or close the proposed outcome.",
    "repetitive_response_loop": "Do not repeat the same confirmation question after the caller has answered it.",
    "premature_resolution_claim": "Do not claim a review request was recorded before the caller selects it.",
    "case_review_confirmation_mismatch": "Keep case-review confirmation focused on the review request and omit payment options.",
    "response_directive_mismatch": "Keep the spoken response within the current FSM directive before sending it to TTS.",
}

_QUALITY_FINDING_CODES = frozenset(
    {
        "interpreter_fallback",
        "repeated_persuasion_after_refusal",
        "simulated_case_review",
        "stalled_dialogue_loop",
        "repetitive_response_loop",
        "premature_resolution_claim",
        "case_review_confirmation_mismatch",
        "response_directive_mismatch",
    }
)


def assess_call(
    *,
    events: Sequence[Mapping[str, Any]],
    fsm_state: Mapping[str, Any],
    transitions: Sequence[Mapping[str, Any]],
    case: CaseContext | None,
) -> dict[str, Any]:
    """Return a dashboard-ready verdict without probabilistic judgment."""

    trail = [dict(item) for item in transitions]
    required_trail = [
        item for item in trail if item.get("response_disposition") != "coalesced"
    ]
    recorded_responses = sum(
        bool(item.get("response_recorded")) for item in required_trail
    )
    coalesced_turns = len(trail) - len(required_trail)
    total_transitions = len(trail)
    required_responses = len(required_trail)
    phase = str(fsm_state.get("phase") or "awaiting_start")
    terminal = phase == "ended" and bool(fsm_state.get("should_end"))
    terminal_response_recorded = bool(
        trail and trail[-1].get("should_end") and trail[-1].get("response_recorded")
    )

    if not trail or not terminal:
        return _assessment(
            status="in_progress",
            label="Call in progress",
            summary="The FSM has not reached its terminal state yet.",
            satisfactory=None,
            terminal=terminal,
            recorded_responses=recorded_responses,
            required_responses=required_responses,
            evaluated_turns=total_transitions,
            coalesced_turns=coalesced_turns,
            adherence_status="not_evaluated",
            quality_status="not_evaluated",
            improvements=(),
            findings=(),
        )

    if not terminal_response_recorded:
        return _assessment(
            status="finalizing",
            label="Finalizing evidence",
            summary="The FSM is terminal; the final assistant response is still being recorded.",
            satisfactory=None,
            terminal=True,
            recorded_responses=recorded_responses,
            required_responses=required_responses,
            evaluated_turns=total_transitions,
            coalesced_turns=coalesced_turns,
            adherence_status="pending",
            quality_status="pending",
            improvements=(),
            findings=(),
        )

    if case is None:
        return _assessment(
            status="warn",
            label="Needs review",
            summary="The FSM ended, but no validated case context was available for scoring.",
            satisfactory=False,
            terminal=True,
            recorded_responses=recorded_responses,
            required_responses=required_responses,
            evaluated_turns=total_transitions,
            coalesced_turns=coalesced_turns,
            adherence_status="not_evaluated",
            quality_status="not_evaluated",
            improvements=("Load the validated runtime case before starting the dashboard.",),
            findings=(),
        )

    report = evaluate_trace([dict(event) for event in events], case=case)
    quality_findings = tuple(
        finding for finding in report.findings if finding.code in _QUALITY_FINDING_CODES
    )
    structural_findings = tuple(
        finding for finding in report.findings if finding.code not in _QUALITY_FINDING_CODES
    )
    adherence_status = _finding_status(structural_findings)
    quality_status = _finding_status(quality_findings)
    status = max(
        (adherence_status, quality_status),
        key={"pass": 0, "warn": 1, "fail": 2}.__getitem__,
    )
    label = {
        "pass": "Satisfactory",
        "warn": "Needs review",
        "fail": "Unsatisfactory",
    }[status]
    summary = {
        "pass": "The call passed both structural FSM adherence and conversational-quality checks.",
        "warn": "The call finished, but one or more deterministic warnings need review.",
        "fail": "The call finished, but structural adherence or conversational quality failed.",
    }[status]
    improvements = _finding_improvements(report.findings)
    if status == "pass":
        improvements = ("No structural or conversational-quality improvements are required for this call.",)

    return _assessment(
        status=status,
        label=label,
        summary=summary,
        satisfactory=status == "pass",
        terminal=True,
        recorded_responses=recorded_responses,
        required_responses=required_responses,
        evaluated_turns=total_transitions,
        coalesced_turns=coalesced_turns,
        adherence_status=adherence_status,
        quality_status=quality_status,
        improvements=improvements,
        findings=tuple(finding.as_dict() for finding in report.findings),
    )


def _finding_improvements(
    findings: Sequence[AdherenceFinding],
) -> tuple[str, ...]:
    actions: list[str] = []
    for finding in findings:
        action = _IMPROVEMENTS.get(
            finding.code,
            f"Review {finding.code.replace('_', ' ')}: {finding.message}",
        )
        if action not in actions:
            actions.append(action)
    return tuple(actions)


def _finding_status(findings: Sequence[AdherenceFinding]) -> str:
    if any(finding.severity == "fail" for finding in findings):
        return "fail"
    if findings:
        return "warn"
    return "pass"


def _assessment(
    *,
    status: str,
    label: str,
    summary: str,
    satisfactory: bool | None,
    terminal: bool,
    recorded_responses: int,
    required_responses: int,
    evaluated_turns: int,
    coalesced_turns: int,
    adherence_status: str,
    quality_status: str,
    improvements: Sequence[str],
    findings: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    response_status = (
        "pass"
        if required_responses > 0 and recorded_responses == required_responses
        else "pending" if status in {"in_progress", "finalizing"} else "fail"
    )
    return {
        "status": status,
        "label": label,
        "summary": summary,
        "satisfactory": satisfactory,
        "terminal": terminal,
        "adherence_status": adherence_status,
        "conversation_quality_status": quality_status,
        "evaluated_turns": evaluated_turns,
        "recorded_responses": recorded_responses,
        "required_responses": required_responses,
        "coalesced_turns": coalesced_turns,
        "response_coverage": f"{recorded_responses}/{required_responses}",
        "evidence": [
            {
                "label": "FSM terminal",
                "status": "pass" if terminal else "pending",
                "value": "ended" if terminal else "active",
            },
            {
                "label": "Response evidence",
                "status": response_status,
                "value": (
                    f"{recorded_responses}/{required_responses}"
                    + (f" · {coalesced_turns} coalesced" if coalesced_turns else "")
                ),
            },
            {
                "label": "FSM adherence",
                "status": adherence_status,
                "value": adherence_status.replace("_", " "),
            },
            {
                "label": "Conversation quality",
                "status": quality_status,
                "value": quality_status.replace("_", " "),
            },
        ],
        "improvements": list(improvements),
        "findings": [dict(finding) for finding in findings],
    }
