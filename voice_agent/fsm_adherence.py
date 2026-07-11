"""Deterministic FSM scenario replay and runtime trace adherence checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Iterable

from .conversation_fsm import (
    CallPhase,
    CaseContext,
    ConversationFSM,
    TurnIntent,
    create_initial_state,
    make_turn_event,
)
from .response_compliance import evaluate_spoken_response


@dataclass(frozen=True)
class AdherenceFinding:
    code: str
    severity: str
    message: str
    turn_id: str | None = None
    scenario_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if value is not None
        }


@dataclass(frozen=True)
class AdherenceReport:
    status: str
    evaluated_turns: int
    findings: tuple[AdherenceFinding, ...]
    phase_coverage: tuple[str, ...] = ()
    guard_coverage: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "evaluatedTurns": self.evaluated_turns,
            "findings": [finding.as_dict() for finding in self.findings],
            "phaseCoverage": list(self.phase_coverage),
            "guardCoverage": list(self.guard_coverage),
        }


SENSITIVE_PHASES = {
    CallPhase.CASE_DISCLOSURE.value,
    CallPhase.RECOGNITION.value,
    CallPhase.OBJECTION_HANDLING.value,
    CallPhase.RESOLUTION.value,
    CallPhase.CONFIRMATION.value,
}

ALLOWED_PHASE_TRANSITIONS = {
    CallPhase.OPENING.value: {
        CallPhase.IDENTITY_VERIFICATION.value,
        CallPhase.ESCALATION.value,
        CallPhase.ENDED.value,
    },
    CallPhase.IDENTITY_VERIFICATION.value: {
        CallPhase.IDENTITY_VERIFICATION.value,
        CallPhase.CASE_DISCLOSURE.value,
        CallPhase.ESCALATION.value,
        CallPhase.ENDED.value,
    },
    CallPhase.CASE_DISCLOSURE.value: {
        CallPhase.CASE_DISCLOSURE.value,
        CallPhase.RECOGNITION.value,
        CallPhase.OBJECTION_HANDLING.value,
        CallPhase.RESOLUTION.value,
        CallPhase.ESCALATION.value,
        CallPhase.ENDED.value,
    },
    CallPhase.RECOGNITION.value: {
        CallPhase.RECOGNITION.value,
        CallPhase.OBJECTION_HANDLING.value,
        CallPhase.RESOLUTION.value,
        CallPhase.ESCALATION.value,
        CallPhase.ENDED.value,
    },
    CallPhase.OBJECTION_HANDLING.value: {
        CallPhase.OBJECTION_HANDLING.value,
        CallPhase.RESOLUTION.value,
        CallPhase.CONFIRMATION.value,
        CallPhase.ESCALATION.value,
        CallPhase.ENDED.value,
    },
    CallPhase.RESOLUTION.value: {
        CallPhase.RESOLUTION.value,
        CallPhase.OBJECTION_HANDLING.value,
        CallPhase.CONFIRMATION.value,
        CallPhase.ESCALATION.value,
        CallPhase.ENDED.value,
    },
    CallPhase.CONFIRMATION.value: {
        CallPhase.CONFIRMATION.value,
        CallPhase.RESOLUTION.value,
        CallPhase.ESCALATION.value,
        CallPhase.ENDED.value,
    },
    CallPhase.ESCALATION.value: {
        CallPhase.ESCALATION.value,
        CallPhase.ENDED.value,
    },
    CallPhase.ENDED.value: {CallPhase.ENDED.value},
}

_CLOSING_DIRECTIVES = {
    "close_without_further_persuasion",
    "close_wrong_party_without_disclosure",
    "close_after_refusal_limit",
    "confirm_outcome_and_close",
    "confirm_escalation_and_close",
}

_PERSUASION_MARKERS = (
    "le gustaria",
    "podemos revisar",
    "quiere continuar",
    "opciones de pago",
    "antes de finalizar",
    "algo mas que desee discutir",
)

_ORDERED_LIST_MARKER = re.compile(r"(?m)^\s*\d+[.):]\s+")

_PAYMENT_REFUSAL_TRACE_PATTERNS = (
    r"\bno\s+(?:voy|pienso|quiero)\s+(?:a\s+)?pagar\b",
    r"\bno\s+pagare\b",
    r"\bme\s+niego\s+a\s+pagar\b",
    r"\b(?:i\s+will\s+not|i\s+won\s+t|i\s+refuse\s+to)\s+pay\b",
)

_SIMULATED_CASE_REVIEW_MARKERS = (
    "estoy revisando",
    "voy a revisar",
    "revisaremos el caso",
    "procederemos con la revision",
    "mientras se revisa",
    "while the case is reviewed",
    "i am reviewing",
    "i will review",
    "we will review the case",
)


def load_jsonl_events(path: str | Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid trace JSON on line {line_number}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"Trace line {line_number} must be a JSON object")
            events.append(event)
    return events


def evaluate_trace(
    events: Iterable[dict[str, Any]],
    *,
    case: CaseContext,
) -> AdherenceReport:
    event_list = list(events)
    findings: list[AdherenceFinding] = []
    transitions: list[dict[str, Any]] = []
    superseded_turn_ids: set[str] = set()
    responses_by_turn: dict[str, list[dict[str, Any]]] = {}

    for event in event_list:
        event_type = event.get("type")
        turn_id = str(event.get("turnId") or "")
        call_id = str(event.get("callId") or "")
        if event.get("version") != 1 or not call_id or not turn_id:
            findings.append(
                AdherenceFinding(
                    "invalid_trace_event",
                    "fail",
                    "Trace event is missing version 1, a call identifier, or a turn identifier.",
                    turn_id=turn_id or None,
                )
            )
            continue
        if event_type == "fsm_transition":
            transitions.append(event)
        elif event_type == "assistant_response":
            responses_by_turn.setdefault(turn_id, []).append(event)
        elif event_type == "turn_superseded":
            superseded_turn_ids.add(turn_id)
        else:
            findings.append(
                AdherenceFinding(
                    "unknown_trace_event",
                    "fail",
                    f"Unsupported trace event type: {event_type}",
                    turn_id=turn_id,
                )
            )

    transition_ids = {str(event["turnId"]) for event in transitions}
    for turn_id in superseded_turn_ids - transition_ids:
        findings.append(
            AdherenceFinding(
                "orphan_superseded_turn",
                "fail",
                "Superseded turn has no matching FSM transition.",
                turn_id=turn_id,
            )
        )
    for turn_id in responses_by_turn:
        if turn_id not in transition_ids:
            findings.append(
                AdherenceFinding(
                    "orphan_response",
                    "fail",
                    "Assistant response has no matching FSM transition.",
                    turn_id=turn_id,
                )
            )

    previous_to_phase_by_call: dict[str, str] = {}
    payment_refusals_by_call: dict[str, int] = {}
    previous_response_signature_by_call: dict[str, tuple[str, str, str, str]] = {}
    stalled_directive_by_call: dict[str, tuple[str, str, int]] = {}
    phase_coverage: set[str] = set()
    guard_coverage: set[str] = set()
    sensitive_values = _sensitive_case_values(case)
    allowed_numeric_claims = _allowed_numeric_claims(case)

    for transition in transitions:
        turn_id = str(transition["turnId"])
        call_id = str(transition.get("callId") or "")
        from_phase = str(transition.get("fromPhase") or "")
        to_phase = str(transition.get("toPhase") or "")
        intent = str(transition.get("interpretedIntent") or "")
        directive = str(transition.get("directive") or "")
        verified = bool(transition.get("identityVerified"))
        should_end = bool(transition.get("shouldEnd"))
        response_events = responses_by_turn.get(turn_id, [])
        response_text = (
            str(response_events[0].get("assistantText") or "")
            if response_events
            else ""
        )
        user_transcript = str(transition.get("userTranscript") or "")

        if response_text:
            spoken = evaluate_spoken_response(transition, response_text, case=case)
            if spoken["status"] == "fail":
                findings.append(
                    AdherenceFinding(
                        "response_directive_mismatch",
                        "fail",
                        spoken["reason"],
                        turn_id=turn_id,
                    )
                )

        if from_phase == to_phase and not should_end:
            previous_phase, previous_directive, previous_count = (
                stalled_directive_by_call.get(call_id, ("", "", 0))
            )
            stalled_count = (
                previous_count + 1
                if previous_phase == from_phase and previous_directive == directive
                else 1
            )
            stalled_directive_by_call[call_id] = (
                from_phase,
                directive,
                stalled_count,
            )
            if stalled_count == 4:
                findings.append(
                    AdherenceFinding(
                        "stalled_dialogue_loop",
                        "fail",
                        "The same phase and response directive repeated without progress.",
                        turn_id=turn_id,
                    )
                )
        else:
            stalled_directive_by_call.pop(call_id, None)

        phase_coverage.update({from_phase, to_phase})
        if intent in {
            TurnIntent.EXPLICIT_TERMINATION.value,
            TurnIntent.WRONG_PARTY.value,
            TurnIntent.REQUESTS_HUMAN.value,
            TurnIntent.VULNERABILITY_DETECTED.value,
        }:
            guard_coverage.add(intent)
        if transition.get("guardReason") == "refusal_limit_reached":
            guard_coverage.add("refusal_limit_reached")

        if _looks_like_payment_refusal(user_transcript):
            refusal_evidence_count = payment_refusals_by_call.get(call_id, 0) + 1
            payment_refusals_by_call[call_id] = refusal_evidence_count
            if refusal_evidence_count >= 2 and (
                to_phase != CallPhase.ENDED.value or not should_end
            ):
                findings.append(
                    AdherenceFinding(
                        "repeated_persuasion_after_refusal",
                        "fail",
                        "Repeated explicit payment refusal did not end the call.",
                        turn_id=turn_id,
                    )
                )

        previous_to_phase = previous_to_phase_by_call.get(call_id)
        if previous_to_phase is not None and from_phase != previous_to_phase:
            findings.append(
                AdherenceFinding(
                    "stale_or_discontinuous_state",
                    "fail",
                    f"Transition starts at {from_phase}, expected {previous_to_phase}.",
                    turn_id=turn_id,
                )
            )
        previous_to_phase_by_call[call_id] = to_phase

        allowed = ALLOWED_PHASE_TRANSITIONS.get(from_phase, set())
        if to_phase not in allowed:
            findings.append(
                AdherenceFinding(
                    "invalid_phase_transition",
                    "fail",
                    f"Transition {from_phase} -> {to_phase} is not allowed.",
                    turn_id=turn_id,
                )
            )
        if to_phase in SENSITIVE_PHASES and not verified:
            findings.append(
                AdherenceFinding(
                    "identity_gate_bypassed",
                    "fail",
                    "Sensitive phase entered before identity verification.",
                    turn_id=turn_id,
                )
            )
        if intent in {
            TurnIntent.EXPLICIT_TERMINATION.value,
            TurnIntent.WRONG_PARTY.value,
        } and (to_phase != CallPhase.ENDED.value or not should_end):
            findings.append(
                AdherenceFinding(
                    "terminal_guard_failed",
                    "fail",
                    f"{intent} did not end the call in the same turn.",
                    turn_id=turn_id,
                )
            )
        resolution = transition.get("resolutionType")
        if resolution and resolution not in case["available_resolution_types"]:
            findings.append(
                AdherenceFinding(
                    "unsupported_resolution",
                    "fail",
                    f"Selected resolution is not case-approved: {resolution}",
                    turn_id=turn_id,
                )
            )
        if not response_events and turn_id not in superseded_turn_ids:
            findings.append(
                AdherenceFinding(
                    "missing_assistant_response",
                    "fail",
                    "FSM transition has no correlated assistant response.",
                    turn_id=turn_id,
                )
            )
        elif len(response_events) > 1:
            findings.append(
                AdherenceFinding(
                    "duplicate_assistant_response",
                    "fail",
                    "FSM transition has multiple correlated assistant responses.",
                    turn_id=turn_id,
                )
            )
        if response_text and not verified:
            normalized_response = _normalize(response_text)
            leaked = sorted(
                value for value in sensitive_values if value and value in normalized_response
            )
            if leaked:
                findings.append(
                    AdherenceFinding(
                        "pre_verification_disclosure",
                        "fail",
                        "Assistant response contains case-sensitive data before verification.",
                        turn_id=turn_id,
                    )
                )
        if response_text:
            normalized_response = _normalize(response_text)
            signature = (from_phase, to_phase, directive, normalized_response)
            if (
                normalized_response
                and previous_response_signature_by_call.get(call_id) == signature
                and directive not in _CLOSING_DIRECTIVES
            ):
                findings.append(
                    AdherenceFinding(
                        "repetitive_response_loop",
                        "fail",
                        "Assistant repeated the same response without conversational progress.",
                        turn_id=turn_id,
                    )
                )
            previous_response_signature_by_call[call_id] = signature
            numeric_claims = _numeric_claims(response_text)
            unsupported_numbers = sorted(numeric_claims - allowed_numeric_claims)
            if unsupported_numbers:
                findings.append(
                    AdherenceFinding(
                        "unsupported_numeric_claim",
                        "fail",
                        "Assistant response contains a numeric claim absent from approved case data: "
                        + ", ".join(unsupported_numbers),
                        turn_id=turn_id,
                    )
                )
        if response_text and directive in _CLOSING_DIRECTIVES:
            normalized_response = _normalize(response_text)
            if "?" in response_text or any(
                marker in normalized_response for marker in _PERSUASION_MARKERS
            ):
                findings.append(
                    AdherenceFinding(
                        "persuasion_after_close_directive",
                        "fail",
                        "Closing response asks another question or continues persuasion.",
                        turn_id=turn_id,
                    )
                )
        if (
            response_text
            and directive == "confirm_case_review_request_without_claiming_execution"
            and any(
                marker in _normalize(response_text)
                for marker in _SIMULATED_CASE_REVIEW_MARKERS
            )
        ):
            findings.append(
                AdherenceFinding(
                    "simulated_case_review",
                    "fail",
                    "Case-review response claims an unequipped review is running or will run.",
                    turn_id=turn_id,
                )
            )
        if response_text and directive in {
            "clarify_and_review_objection",
            "summarize_and_review_objection",
        }:
            normalized_response = _normalize(response_text)
            if any(
                marker in normalized_response
                for marker in (
                    "he registrado su solicitud",
                    "voy a registrar su solicitud",
                    "su solicitud queda registrada",
                    "your review request has been recorded",
                    "i will record your review request",
                )
            ):
                findings.append(
                    AdherenceFinding(
                        "premature_resolution_claim",
                        "fail",
                        "Assistant claimed a review request was recorded before selection.",
                        turn_id=turn_id,
                    )
                )
        if (
            response_text
            and directive == "confirm_case_review_request_without_claiming_execution"
        ):
            normalized_response = _normalize(response_text)
            if any(
                marker in normalized_response
                for marker in (
                    "opciones de pago",
                    "pago inmediato",
                    "fecha de pago",
                    "plan de pago",
                    "payment options",
                    "pay immediately",
                    "payment plan",
                )
            ):
                findings.append(
                    AdherenceFinding(
                        "case_review_confirmation_mismatch",
                        "fail",
                        "Case-review confirmation introduced payment alternatives.",
                        turn_id=turn_id,
                    )
                )
        if transition.get("interpreter") == "safe_fallback":
            findings.append(
                AdherenceFinding(
                    "interpreter_fallback",
                    "warn",
                    "Intent interpreter failed closed to unknown.",
                    turn_id=turn_id,
                )
            )

    return _report(
        findings,
        evaluated_turns=len(transitions),
        phase_coverage=phase_coverage,
        guard_coverage=guard_coverage,
    )


def evaluate_scenario_pack(
    pack: dict[str, Any],
    *,
    case: CaseContext,
) -> AdherenceReport:
    findings: list[AdherenceFinding] = []
    phase_coverage: set[str] = {CallPhase.OPENING.value}
    guard_coverage: set[str] = set()
    turn_count = 0

    for scenario in pack.get("scenarios", []):
        scenario_id = str(scenario.get("id") or "unknown")
        fsm = ConversationFSM()
        state = fsm.advance(
            create_initial_state(case),
            make_turn_event(TurnIntent.CALL_STARTED, source="system"),
        )
        phase_coverage.add(state["phase"])
        for index, turn in enumerate(scenario.get("turns", []), start=1):
            turn_count += 1
            try:
                event = make_turn_event(
                    str(turn["intent"]),
                    source=str(turn.get("source", "user")),
                    objection_type=turn.get("objectionType"),
                    resolution_type=turn.get("resolutionType"),
                    verification_fields=turn.get("verificationFields"),
                )
                state = fsm.advance(state, event)
            except (KeyError, ValueError) as exc:
                findings.append(
                    AdherenceFinding(
                        "invalid_scenario_turn",
                        "fail",
                        f"Turn {index} is invalid: {exc}",
                        scenario_id=scenario_id,
                    )
                )
                continue
            phase_coverage.add(state["phase"])
            if event["intent"] in pack.get("requiredGlobalGuardCoverage", []):
                guard_coverage.add(event["intent"])
            if state["guard_reason"] == "refusal_limit_reached":
                guard_coverage.add("refusal_limit_reached")
            _compare_expected_state(
                state,
                turn,
                scenario_id=scenario_id,
                turn_index=index,
                findings=findings,
            )

    required_phases = set(pack.get("requiredPhaseCoverage", []))
    missing_phases = sorted(required_phases - phase_coverage)
    if missing_phases:
        findings.append(
            AdherenceFinding(
                "missing_phase_coverage",
                "fail",
                f"Scenario pack does not reach phases: {', '.join(missing_phases)}",
            )
        )
    required_guards = set(pack.get("requiredGlobalGuardCoverage", []))
    missing_guards = sorted(required_guards - guard_coverage)
    if missing_guards:
        findings.append(
            AdherenceFinding(
                "missing_guard_coverage",
                "fail",
                f"Scenario pack does not exercise guards: {', '.join(missing_guards)}",
            )
        )
    return _report(
        findings,
        evaluated_turns=turn_count,
        phase_coverage=phase_coverage,
        guard_coverage=guard_coverage,
    )


def _compare_expected_state(
    state: dict[str, Any],
    turn: dict[str, Any],
    *,
    scenario_id: str,
    turn_index: int,
    findings: list[AdherenceFinding],
) -> None:
    expectations = {
        "expectedPhase": "phase",
        "expectedDirective": "response_directive",
        "expectedShouldEnd": "should_end",
        "expectedRefusalCount": "refusal_count",
        "expectedVerifiedFields": "verified_fields",
    }
    for expected_key, state_key in expectations.items():
        if expected_key not in turn:
            continue
        if state[state_key] != turn[expected_key]:
            findings.append(
                AdherenceFinding(
                    "scenario_expectation_failed",
                    "fail",
                    f"Turn {turn_index}: expected {state_key}={turn[expected_key]!r}, "
                    f"got {state[state_key]!r}.",
                    scenario_id=scenario_id,
                )
            )


def _sensitive_case_values(case: CaseContext) -> set[str]:
    values: set[str] = set()
    for key in (
        "customer_name",
        "product_name",
        "reference",
        "due_date",
        "disclosure_summary",
    ):
        value = case.get(key)
        if value:
            normalized_value = _normalize(str(value))
            values.add(normalized_value)
            if key in {"customer_name", "product_name", "reference"}:
                values.update(
                    token
                    for token in re.findall(r"[a-z0-9]+", normalized_value)
                    if len(token) >= 4 and token not in {"company", "empresa", "limited"}
                )
    amount_minor = case.get("amount_minor")
    if isinstance(amount_minor, int):
        major = amount_minor / 100
        if major.is_integer():
            integer = str(int(major))
            values.update({integer, f"{int(major):,}".replace(",", ".")})
        else:
            values.update({f"{major:.2f}", f"{major:.2f}".replace(".", ",")})
    return {value for value in values if len(value) >= 3}


def _allowed_numeric_claims(case: CaseContext) -> set[str]:
    allowed: set[str] = set()
    for key, value in case.items():
        if key in {"metadata", "case_id", "amount_minor"} or value is None:
            continue
        if isinstance(value, (str, int, float)):
            allowed.update(re.findall(r"\b\d[\d.,]*\b", str(value)))
    amount_minor = case.get("amount_minor")
    if isinstance(amount_minor, int):
        major = amount_minor / 100
        if major.is_integer():
            integer = str(int(major))
            allowed.update({integer, f"{int(major):,}", f"{int(major):,}".replace(",", ".")})
        else:
            allowed.update({f"{major:.2f}", f"{major:.2f}".replace(".", ",")})
    return allowed


def _numeric_claims(text: str) -> set[str]:
    """Extract substantive numbers while ignoring ordered-list labels."""

    without_list_markers = _ORDERED_LIST_MARKER.sub("", text)
    return set(re.findall(r"\b\d[\d.,]*\b", without_list_markers))


def _looks_like_payment_refusal(text: str) -> bool:
    normalized = _normalize(text)
    compact = normalized.replace(" ", "")
    if compact in {
        "novoyapagar",
        "novoiapagar",
        "nonvoyapagar",
        "nonvoiapagar",
        "novojapar",
    }:
        return True
    return any(re.search(pattern, normalized) for pattern in _PAYMENT_REFUSAL_TRACE_PATTERNS)


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _report(
    findings: list[AdherenceFinding],
    *,
    evaluated_turns: int,
    phase_coverage: set[str],
    guard_coverage: set[str],
) -> AdherenceReport:
    status = "fail" if any(item.severity == "fail" for item in findings) else (
        "warn" if findings else "pass"
    )
    return AdherenceReport(
        status=status,
        evaluated_turns=evaluated_turns,
        findings=tuple(findings),
        phase_coverage=tuple(sorted(phase_coverage)),
        guard_coverage=tuple(sorted(guard_coverage)),
    )
