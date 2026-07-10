"""Case-agnostic, deterministic conversation FSM built with LangGraph."""

from __future__ import annotations

from copy import deepcopy
from enum import Enum
from typing import Any, Optional, TypedDict

try:
    from typing import NotRequired
except ImportError:  # Python 3.9/3.10 compatibility for local tooling.
    from typing_extensions import NotRequired

from langgraph.graph import END, START, StateGraph


class CallPhase(str, Enum):
    OPENING = "opening"
    IDENTITY_VERIFICATION = "identity_verification"
    CASE_DISCLOSURE = "case_disclosure"
    RECOGNITION = "recognition"
    OBJECTION_HANDLING = "objection_handling"
    RESOLUTION = "resolution"
    CONFIRMATION = "confirmation"
    ESCALATION = "escalation"
    ENDED = "ended"


class TurnIntent(str, Enum):
    CALL_STARTED = "call_started"
    ASKS_REASON = "asks_reason"
    IDENTITY_CONFIRMED = "identity_confirmed"
    IDENTITY_REFUSED = "identity_refused"
    WRONG_PARTY = "wrong_party"
    CASE_DISCLOSED = "case_disclosed"
    RECOGNIZES_CASE = "recognizes_case"
    DISPUTES_CASE = "disputes_case"
    OBJECTION_PROVIDED = "objection_provided"
    OBJECTION_RESOLVED = "objection_resolved"
    RESOLUTION_SELECTED = "resolution_selected"
    OUTCOME_CONFIRMED = "outcome_confirmed"
    CORRECTION_REQUESTED = "correction_requested"
    CANNOT_RESOLVE = "cannot_resolve"
    REQUESTS_HUMAN = "requests_human"
    VULNERABILITY_DETECTED = "vulnerability_detected"
    REFUSAL = "refusal"
    EXPLICIT_TERMINATION = "explicit_termination"
    ESCALATION_COMPLETED = "escalation_completed"
    UNKNOWN = "unknown"


class CaseContext(TypedDict):
    case_id: str
    creditor_name: str
    customer_name: str
    locale: str
    disclosure_summary: str
    available_resolution_types: list[str]
    product_name: NotRequired[str]
    amount_minor: NotRequired[int]
    currency: NotRequired[str]
    due_date: NotRequired[str]
    reference: NotRequired[str]
    metadata: NotRequired[dict[str, Any]]


class FSMPolicy(TypedDict):
    max_refusals: int
    verification_fields: list[str]
    pre_verification_reason: str


class TurnEvent(TypedDict):
    intent: str
    source: str
    objection_type: NotRequired[str]
    resolution_type: NotRequired[str]
    evidence: NotRequired[dict[str, Any]]


class TransitionRecord(TypedDict):
    from_phase: str
    to_phase: str
    intent: str
    directive: str
    guard_reason: Optional[str]


class ConversationState(TypedDict):
    case: CaseContext
    policy: FSMPolicy
    phase: str
    previous_phase: str
    identity_verified: bool
    refusal_count: int
    objection_type: Optional[str]
    resolution_type: Optional[str]
    response_directive: str
    guard_reason: Optional[str]
    guard_handled: bool
    should_end: bool
    event: TurnEvent
    transition_history: list[TransitionRecord]


SENSITIVE_PHASES = frozenset(
    {
        CallPhase.CASE_DISCLOSURE.value,
        CallPhase.RECOGNITION.value,
        CallPhase.OBJECTION_HANDLING.value,
        CallPhase.RESOLUTION.value,
        CallPhase.CONFIRMATION.value,
    }
)

DEFAULT_POLICY: FSMPolicy = {
    "max_refusals": 2,
    "verification_fields": ["role", "name_and_first_surname"],
    "pre_verification_reason": "an administrative issue with a payment",
}


def create_initial_state(
    case: CaseContext,
    *,
    policy: FSMPolicy | None = None,
) -> ConversationState:
    """Create serializable state for one call without embedding case behavior."""

    _validate_case(case)
    resolved_policy = deepcopy(policy or DEFAULT_POLICY)
    _validate_policy(resolved_policy)
    no_event = make_turn_event(TurnIntent.UNKNOWN, source="system")
    return {
        "case": deepcopy(case),
        "policy": resolved_policy,
        "phase": CallPhase.OPENING.value,
        "previous_phase": CallPhase.OPENING.value,
        "identity_verified": False,
        "refusal_count": 0,
        "objection_type": None,
        "resolution_type": None,
        "response_directive": "open_and_verify_identity",
        "guard_reason": None,
        "guard_handled": False,
        "should_end": False,
        "event": no_event,
        "transition_history": [],
    }


def make_turn_event(
    intent: TurnIntent | str,
    *,
    source: str = "user",
    objection_type: str | None = None,
    resolution_type: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> TurnEvent:
    """Build and validate the typed boundary consumed by the FSM."""

    normalized_intent = _normalize_intent(intent)
    if source not in {"user", "system"}:
        raise ValueError("turn event source must be 'user' or 'system'")
    event: TurnEvent = {"intent": normalized_intent, "source": source}
    if objection_type:
        event["objection_type"] = objection_type
    if resolution_type:
        event["resolution_type"] = resolution_type
    if evidence:
        event["evidence"] = deepcopy(evidence)
    return event


class ConversationFSM:
    """Advance deterministic call state one interpreted event at a time."""

    def __init__(self, *, checkpointer: Any | None = None) -> None:
        self._uses_checkpointer = checkpointer is not None
        self.graph = build_conversation_graph(checkpointer=checkpointer)

    def advance(
        self,
        state: ConversationState,
        event: TurnEvent,
        *,
        thread_id: str | None = None,
    ) -> ConversationState:
        _validate_state(state)
        _validate_event(event)
        if self._uses_checkpointer and not thread_id:
            raise ValueError("thread_id is required when a checkpointer is configured")

        graph_input = deepcopy(state)
        graph_input.update(
            {
                "event": deepcopy(event),
                "previous_phase": state["phase"],
                "guard_reason": None,
                "guard_handled": False,
            }
        )
        config = {"configurable": {"thread_id": thread_id}} if thread_id else None
        result = self.graph.invoke(graph_input, config=config)
        return ConversationState(**result)


def build_conversation_graph(*, checkpointer: Any | None = None):
    """Compile the low-level LangGraph used solely as the external FSM."""

    builder = StateGraph(ConversationState)
    builder.add_node("apply_global_guards", _apply_global_guards)
    builder.add_node("enforce_invariants", _enforce_invariants)

    phase_nodes: dict[str, str] = {}
    for phase in CallPhase:
        node_name = f"phase_{phase.value}"
        phase_nodes[phase.value] = node_name
        builder.add_node(node_name, _PHASE_HANDLERS[phase])
        builder.add_edge(node_name, "enforce_invariants")

    builder.add_edge(START, "apply_global_guards")
    builder.add_conditional_edges(
        "apply_global_guards",
        _route_after_global_guards,
        {**phase_nodes, "finalize": "enforce_invariants"},
    )
    builder.add_edge("enforce_invariants", END)
    return builder.compile(checkpointer=checkpointer)


def response_context(state: ConversationState) -> dict[str, Any]:
    """Return only the context the response model may use in the current phase."""

    context: dict[str, Any] = {
        "phase": state["phase"],
        "directive": state["response_directive"],
        "locale": state["case"]["locale"],
        "calling_party": state["case"]["creditor_name"],
        "verification_fields": list(state["policy"]["verification_fields"]),
        "pre_verification_reason": state["policy"]["pre_verification_reason"],
        "should_end": state["should_end"],
    }
    if state["identity_verified"]:
        disclosed_case = deepcopy(state["case"])
        disclosed_case.pop("metadata", None)
        context["case"] = disclosed_case
    if state["objection_type"]:
        context["objection_type"] = state["objection_type"]
    if state["resolution_type"]:
        context["resolution_type"] = state["resolution_type"]
    return context


def _apply_global_guards(state: ConversationState) -> dict[str, Any]:
    phase = state["phase"]
    intent = state["event"]["intent"]
    refusal_count = state["refusal_count"]

    if phase == CallPhase.ENDED.value:
        return {
            "guard_handled": True,
            "should_end": True,
            "response_directive": "call_already_ended",
        }
    if intent == TurnIntent.EXPLICIT_TERMINATION.value:
        return _guard_transition(CallPhase.ENDED, "close_without_further_persuasion")
    if intent == TurnIntent.WRONG_PARTY.value:
        return _guard_transition(CallPhase.ENDED, "close_wrong_party_without_disclosure")
    if intent == TurnIntent.REQUESTS_HUMAN.value:
        return _guard_transition(CallPhase.ESCALATION, "arrange_human_assistance")
    if intent == TurnIntent.VULNERABILITY_DETECTED.value:
        return _guard_transition(CallPhase.ESCALATION, "apply_vulnerability_protocol")
    if intent in {TurnIntent.REFUSAL.value, TurnIntent.IDENTITY_REFUSED.value}:
        refusal_count += 1
        if refusal_count >= state["policy"]["max_refusals"]:
            result = _guard_transition(CallPhase.ENDED, "close_after_refusal_limit")
            result["refusal_count"] = refusal_count
            result["guard_reason"] = "refusal_limit_reached"
            return result
        return {
            "refusal_count": refusal_count,
            "guard_handled": True,
            "guard_reason": "refusal_recorded",
            "response_directive": "acknowledge_refusal_and_offer_one_clear_choice",
        }
    return {}


def _guard_transition(phase: CallPhase, directive: str) -> dict[str, Any]:
    return {
        "phase": phase.value,
        "guard_handled": True,
        "should_end": phase is CallPhase.ENDED,
        "response_directive": directive,
    }


def _route_after_global_guards(state: ConversationState) -> str:
    if state["guard_handled"]:
        return "finalize"
    return state["phase"]


def _opening(state: ConversationState) -> dict[str, Any]:
    return {
        "phase": CallPhase.IDENTITY_VERIFICATION.value,
        "response_directive": "open_and_verify_identity",
    }


def _identity_verification(state: ConversationState) -> dict[str, Any]:
    intent = state["event"]["intent"]
    if intent == TurnIntent.IDENTITY_CONFIRMED.value:
        return {
            "identity_verified": True,
            "phase": CallPhase.CASE_DISCLOSURE.value,
            "response_directive": "disclose_case_and_ask_recognition",
        }
    if intent == TurnIntent.ASKS_REASON.value:
        return {"response_directive": "give_pre_verification_reason_and_verify"}
    return {"response_directive": "verify_identity"}


def _case_disclosure(state: ConversationState) -> dict[str, Any]:
    intent = state["event"]["intent"]
    if intent == TurnIntent.RECOGNIZES_CASE.value:
        return {
            "phase": CallPhase.RESOLUTION.value,
            "response_directive": "offer_case_approved_resolutions",
        }
    if intent in {TurnIntent.DISPUTES_CASE.value, TurnIntent.OBJECTION_PROVIDED.value}:
        return _enter_objection(state)
    if intent == TurnIntent.CASE_DISCLOSED.value:
        return {
            "phase": CallPhase.RECOGNITION.value,
            "response_directive": "ask_case_recognition",
        }
    return {"response_directive": "disclose_case_and_ask_recognition"}


def _recognition(state: ConversationState) -> dict[str, Any]:
    intent = state["event"]["intent"]
    if intent == TurnIntent.RECOGNIZES_CASE.value:
        return {
            "phase": CallPhase.RESOLUTION.value,
            "response_directive": "offer_case_approved_resolutions",
        }
    if intent in {TurnIntent.DISPUTES_CASE.value, TurnIntent.OBJECTION_PROVIDED.value}:
        return _enter_objection(state)
    return {"response_directive": "ask_case_recognition"}


def _enter_objection(state: ConversationState) -> dict[str, Any]:
    return {
        "phase": CallPhase.OBJECTION_HANDLING.value,
        "objection_type": state["event"].get("objection_type"),
        "response_directive": "clarify_and_review_objection",
    }


def _objection_handling(state: ConversationState) -> dict[str, Any]:
    intent = state["event"]["intent"]
    if intent == TurnIntent.OBJECTION_PROVIDED.value:
        return {
            "objection_type": state["event"].get("objection_type"),
            "response_directive": "summarize_and_review_objection",
        }
    if intent in {TurnIntent.OBJECTION_RESOLVED.value, TurnIntent.RECOGNIZES_CASE.value}:
        return {
            "phase": CallPhase.RESOLUTION.value,
            "response_directive": "offer_case_approved_resolutions",
        }
    if intent == TurnIntent.CANNOT_RESOLVE.value:
        return {
            "phase": CallPhase.ESCALATION.value,
            "response_directive": "explain_limit_and_escalate",
        }
    return {"response_directive": "clarify_and_review_objection"}


def _resolution(state: ConversationState) -> dict[str, Any]:
    intent = state["event"]["intent"]
    if intent in {TurnIntent.DISPUTES_CASE.value, TurnIntent.OBJECTION_PROVIDED.value}:
        return _enter_objection(state)
    if intent == TurnIntent.CANNOT_RESOLVE.value:
        return {
            "phase": CallPhase.ESCALATION.value,
            "response_directive": "explain_limit_and_escalate",
        }
    if intent == TurnIntent.RESOLUTION_SELECTED.value:
        selected = state["event"].get("resolution_type")
        allowed = state["case"]["available_resolution_types"]
        if not selected or selected not in allowed:
            return {
                "resolution_type": None,
                "guard_reason": "unsupported_resolution_type",
                "response_directive": "offer_case_approved_resolutions",
            }
        return {
            "phase": CallPhase.CONFIRMATION.value,
            "resolution_type": selected,
            "response_directive": "confirm_selected_resolution",
        }
    return {"response_directive": "offer_case_approved_resolutions"}


def _confirmation(state: ConversationState) -> dict[str, Any]:
    intent = state["event"]["intent"]
    if intent == TurnIntent.OUTCOME_CONFIRMED.value:
        return {
            "phase": CallPhase.ENDED.value,
            "should_end": True,
            "response_directive": "confirm_outcome_and_close",
        }
    if intent == TurnIntent.CORRECTION_REQUESTED.value:
        return {
            "phase": CallPhase.RESOLUTION.value,
            "resolution_type": None,
            "response_directive": "correct_and_offer_case_approved_resolutions",
        }
    return {"response_directive": "confirm_selected_resolution"}


def _escalation(state: ConversationState) -> dict[str, Any]:
    if state["event"]["intent"] == TurnIntent.ESCALATION_COMPLETED.value:
        return {
            "phase": CallPhase.ENDED.value,
            "should_end": True,
            "response_directive": "confirm_escalation_and_close",
        }
    return {"response_directive": "complete_escalation"}


def _ended(state: ConversationState) -> dict[str, Any]:
    return {"should_end": True, "response_directive": "call_already_ended"}


_PHASE_HANDLERS = {
    CallPhase.OPENING: _opening,
    CallPhase.IDENTITY_VERIFICATION: _identity_verification,
    CallPhase.CASE_DISCLOSURE: _case_disclosure,
    CallPhase.RECOGNITION: _recognition,
    CallPhase.OBJECTION_HANDLING: _objection_handling,
    CallPhase.RESOLUTION: _resolution,
    CallPhase.CONFIRMATION: _confirmation,
    CallPhase.ESCALATION: _escalation,
    CallPhase.ENDED: _ended,
}


def _enforce_invariants(state: ConversationState) -> dict[str, Any]:
    phase = state["phase"]
    updates: dict[str, Any] = {}
    if phase in SENSITIVE_PHASES and not state["identity_verified"]:
        phase = CallPhase.IDENTITY_VERIFICATION.value
        updates.update(
            {
                "phase": phase,
                "response_directive": "verify_identity",
                "guard_reason": "identity_required_before_case_disclosure",
                "resolution_type": None,
                "objection_type": None,
            }
        )

    record: TransitionRecord = {
        "from_phase": state["previous_phase"],
        "to_phase": phase,
        "intent": state["event"]["intent"],
        "directive": updates.get("response_directive", state["response_directive"]),
        "guard_reason": updates.get("guard_reason", state["guard_reason"]),
    }
    updates["transition_history"] = [*state["transition_history"], record]
    return updates


def _validate_case(case: CaseContext) -> None:
    required_strings = {
        "case_id",
        "creditor_name",
        "customer_name",
        "locale",
        "disclosure_summary",
    }
    missing = sorted(field for field in required_strings if not case.get(field))
    if "available_resolution_types" not in case:
        missing.append("available_resolution_types")
    if missing:
        raise ValueError(f"case context is missing required fields: {', '.join(missing)}")
    resolutions = case["available_resolution_types"]
    if not isinstance(resolutions, list) or not all(
        isinstance(item, str) and item.strip() for item in resolutions
    ):
        raise ValueError("available_resolution_types must be a list of non-empty strings")
    if "amount_minor" in case and case["amount_minor"] < 0:
        raise ValueError("amount_minor cannot be negative")


def _validate_policy(policy: FSMPolicy) -> None:
    if policy.get("max_refusals", 0) < 1:
        raise ValueError("max_refusals must be at least 1")
    if not policy.get("verification_fields"):
        raise ValueError("verification_fields must not be empty")
    if not policy.get("pre_verification_reason"):
        raise ValueError("pre_verification_reason must not be empty")


def _validate_event(event: TurnEvent) -> None:
    _normalize_intent(event.get("intent", ""))
    if event.get("source") not in {"user", "system"}:
        raise ValueError("turn event source must be 'user' or 'system'")


def _validate_state(state: ConversationState) -> None:
    _validate_case(state["case"])
    _validate_policy(state["policy"])
    try:
        CallPhase(state["phase"])
    except ValueError as exc:
        raise ValueError(f"unknown call phase: {state['phase']}") from exc


def _normalize_intent(intent: TurnIntent | str) -> str:
    try:
        return TurnIntent(intent).value
    except ValueError as exc:
        raise ValueError(f"unknown turn intent: {intent}") from exc
