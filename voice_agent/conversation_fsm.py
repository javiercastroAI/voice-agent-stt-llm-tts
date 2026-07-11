"""Case-agnostic, deterministic conversation FSM built with LangGraph."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional, TypedDict

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
    verification_fields: NotRequired[list[str]]
    evidence: NotRequired[dict[str, Any]]


class TransitionRecord(TypedDict):
    transition_id: str
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
    verified_fields: list[str]
    refusal_count: int
    objection_type: Optional[str]
    resolution_type: Optional[str]
    response_directive: str
    guard_reason: Optional[str]
    guard_handled: bool
    should_end: bool
    event: TurnEvent
    matched_transition_id: str
    transition_history: list[TransitionRecord]


TransitionGuard = Callable[[ConversationState], bool]
TransitionAction = Callable[[ConversationState], dict[str, Any]]


@dataclass(frozen=True)
class TransitionDefinition:
    """One ordered, executable transition in the canonical FSM registry."""

    id: str
    source: CallPhase | None
    intents: tuple[TurnIntent, ...]
    target: CallPhase | None
    directive: str
    guard_name: str | None = None
    guard: TransitionGuard | None = None
    action: TransitionAction | None = None
    global_guard: bool = False
    diagram: bool = False

    def matches(self, state: ConversationState) -> bool:
        if self.source is not None and state["phase"] != self.source.value:
            return False
        if self.intents and state["event"]["intent"] not in {
            intent.value for intent in self.intents
        }:
            return False
        return self.guard is None or self.guard(state)

    def apply(self, state: ConversationState) -> dict[str, Any]:
        updates: dict[str, Any] = {
            "matched_transition_id": self.id,
            "response_directive": self.directive,
        }
        if self.target is not None:
            updates["phase"] = self.target.value
            updates["should_end"] = self.target is CallPhase.ENDED
        if self.action is not None:
            updates.update(self.action(state))
        return updates


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
        "verified_fields": [],
        "refusal_count": 0,
        "objection_type": None,
        "resolution_type": None,
        "response_directive": "open_and_verify_identity",
        "guard_reason": None,
        "guard_handled": False,
        "should_end": False,
        "event": no_event,
        "matched_transition_id": "initial_state",
        "transition_history": [],
    }


def make_turn_event(
    intent: TurnIntent | str,
    *,
    source: str = "user",
    objection_type: str | None = None,
    resolution_type: str | None = None,
    verification_fields: list[str] | None = None,
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
    if verification_fields is not None:
        event["verification_fields"] = list(dict.fromkeys(verification_fields))
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
        builder.add_node(node_name, _apply_declared_phase_transition)
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
        "verified_fields": list(state["verified_fields"]),
        "remaining_verification_fields": [
            field
            for field in state["policy"]["verification_fields"]
            if field not in state["verified_fields"]
        ],
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
    for transition in GLOBAL_TRANSITIONS:
        if transition.matches(state):
            return {**transition.apply(state), "guard_handled": True}
    return {}


def _apply_declared_phase_transition(state: ConversationState) -> dict[str, Any]:
    for transition in PHASE_TRANSITIONS:
        if transition.matches(state):
            return transition.apply(state)
    raise RuntimeError(
        "declarative FSM has no matching transition for "
        f"{state['phase']} + {state['event']['intent']}"
    )


def _route_after_global_guards(state: ConversationState) -> str:
    if state["guard_handled"]:
        return "finalize"
    return state["phase"]


def _all_identity_fields_present(state: ConversationState) -> bool:
    required = state["policy"]["verification_fields"]
    reported = state["event"].get("verification_fields", [])
    accumulated = {*state["verified_fields"], *reported}
    return all(field in accumulated for field in required)


def _case_review_is_available(state: ConversationState) -> bool:
    return "case_review" in state["case"]["available_resolution_types"]


def _resolution_is_allowed(state: ConversationState) -> bool:
    selected = state["event"].get("resolution_type")
    return bool(selected and selected in state["case"]["available_resolution_types"])


def _refusal_limit_will_be_reached(state: ConversationState) -> bool:
    return state["refusal_count"] + 1 >= state["policy"]["max_refusals"]


def _record_identity_fields(state: ConversationState) -> dict[str, Any]:
    required = state["policy"]["verification_fields"]
    confirmed = [
        field
        for field in state["event"].get("verification_fields", [])
        if field in required
    ]
    verified_fields = list(dict.fromkeys([*state["verified_fields"], *confirmed]))
    return {
        "verified_fields": verified_fields,
        "identity_verified": all(field in verified_fields for field in required),
    }


def _enter_objection_action(state: ConversationState) -> dict[str, Any]:
    return {"objection_type": state["event"].get("objection_type")}


def _update_objection_action(state: ConversationState) -> dict[str, Any]:
    return {"objection_type": state["event"].get("objection_type")}


def _select_resolution_action(state: ConversationState) -> dict[str, Any]:
    selected = state["event"].get("resolution_type")
    directive = "confirm_selected_resolution"
    if selected == "immediate_payment":
        directive = (
            "confirm_immediate_payment_commitment_without_requesting_payment_credentials"
        )
    elif selected == "case_review":
        directive = "confirm_case_review_request_without_claiming_execution"
    return {"resolution_type": selected, "response_directive": directive}


def _reject_resolution_action(state: ConversationState) -> dict[str, Any]:
    return {
        "resolution_type": None,
        "guard_reason": "unsupported_resolution_type",
    }


def _record_case_review_action(state: ConversationState) -> dict[str, Any]:
    return {"resolution_type": "case_review"}


def _end_after_refusal_limit(state: ConversationState) -> dict[str, Any]:
    return {
        "refusal_count": state["refusal_count"] + 1,
        "guard_reason": "refusal_limit_reached",
    }


def _record_first_refusal(state: ConversationState) -> dict[str, Any]:
    return {
        "refusal_count": state["refusal_count"] + 1,
        "guard_reason": "refusal_recorded",
    }


def _clear_resolution(state: ConversationState) -> dict[str, Any]:
    return {"resolution_type": None}


def _confirmation_directive(state: ConversationState) -> dict[str, Any]:
    directive = "confirm_selected_resolution"
    if state["resolution_type"] == "immediate_payment":
        directive = (
            "confirm_immediate_payment_commitment_without_requesting_payment_credentials"
        )
    elif state["resolution_type"] == "case_review":
        directive = "confirm_case_review_request_without_claiming_execution"
    return {"response_directive": directive}


GLOBAL_TRANSITIONS: tuple[TransitionDefinition, ...] = (
    TransitionDefinition(
        id="ended_is_terminal",
        source=CallPhase.ENDED,
        intents=(),
        target=CallPhase.ENDED,
        directive="call_already_ended",
        global_guard=True,
    ),
    TransitionDefinition(
        id="explicit_termination",
        source=None,
        intents=(TurnIntent.EXPLICIT_TERMINATION,),
        target=CallPhase.ENDED,
        directive="close_without_further_persuasion",
        global_guard=True,
        diagram=True,
    ),
    TransitionDefinition(
        id="wrong_party",
        source=None,
        intents=(TurnIntent.WRONG_PARTY,),
        target=CallPhase.ENDED,
        directive="close_wrong_party_without_disclosure",
        global_guard=True,
        diagram=True,
    ),
    TransitionDefinition(
        id="human_requested",
        source=None,
        intents=(TurnIntent.REQUESTS_HUMAN,),
        target=CallPhase.ESCALATION,
        directive="arrange_human_assistance",
        global_guard=True,
        diagram=True,
    ),
    TransitionDefinition(
        id="vulnerability_detected",
        source=None,
        intents=(TurnIntent.VULNERABILITY_DETECTED,),
        target=CallPhase.ESCALATION,
        directive="apply_vulnerability_protocol",
        global_guard=True,
        diagram=True,
    ),
    TransitionDefinition(
        id="refusal_limit",
        source=None,
        intents=(TurnIntent.REFUSAL, TurnIntent.IDENTITY_REFUSED),
        target=CallPhase.ENDED,
        directive="close_after_refusal_limit",
        guard_name="refusal_limit_will_be_reached",
        guard=_refusal_limit_will_be_reached,
        action=_end_after_refusal_limit,
        global_guard=True,
        diagram=True,
    ),
    TransitionDefinition(
        id="first_refusal",
        source=None,
        intents=(TurnIntent.REFUSAL, TurnIntent.IDENTITY_REFUSED),
        target=None,
        directive="acknowledge_refusal_and_offer_one_clear_choice",
        action=_record_first_refusal,
        global_guard=True,
    ),
)


PHASE_TRANSITIONS: tuple[TransitionDefinition, ...] = (
    TransitionDefinition(
        "opening_to_identity", CallPhase.OPENING, (), CallPhase.IDENTITY_VERIFICATION,
        "open_and_verify_identity", diagram=True,
    ),
    TransitionDefinition(
        "identity_complete", CallPhase.IDENTITY_VERIFICATION,
        (TurnIntent.IDENTITY_CONFIRMED,), CallPhase.CASE_DISCLOSURE,
        "disclose_case_and_ask_recognition",
        guard_name="all_identity_fields_present", guard=_all_identity_fields_present,
        action=_record_identity_fields, diagram=True,
    ),
    TransitionDefinition(
        "identity_partial", CallPhase.IDENTITY_VERIFICATION,
        (TurnIntent.IDENTITY_CONFIRMED,), None, "verify_remaining_identity_fields",
        action=_record_identity_fields,
    ),
    TransitionDefinition(
        "identity_reason", CallPhase.IDENTITY_VERIFICATION, (TurnIntent.ASKS_REASON,),
        None, "give_pre_verification_reason_and_verify",
    ),
    TransitionDefinition(
        "identity_fallback", CallPhase.IDENTITY_VERIFICATION, (), None, "verify_identity",
    ),
    TransitionDefinition(
        "disclosure_recognized", CallPhase.CASE_DISCLOSURE,
        (TurnIntent.RECOGNIZES_CASE,), CallPhase.RESOLUTION,
        "offer_case_approved_resolutions", diagram=True,
    ),
    TransitionDefinition(
        "disclosure_disputed", CallPhase.CASE_DISCLOSURE,
        (TurnIntent.DISPUTES_CASE, TurnIntent.OBJECTION_PROVIDED),
        CallPhase.OBJECTION_HANDLING, "clarify_and_review_objection",
        action=_enter_objection_action, diagram=True,
    ),
    TransitionDefinition(
        "disclosure_presented", CallPhase.CASE_DISCLOSURE,
        (TurnIntent.CASE_DISCLOSED,), CallPhase.RECOGNITION,
        "ask_case_recognition", diagram=True,
    ),
    TransitionDefinition(
        "disclosure_fallback", CallPhase.CASE_DISCLOSURE, (), None,
        "disclose_case_and_ask_recognition",
    ),
    TransitionDefinition(
        "recognition_accepted", CallPhase.RECOGNITION,
        (TurnIntent.RECOGNIZES_CASE,), CallPhase.RESOLUTION,
        "offer_case_approved_resolutions", diagram=True,
    ),
    TransitionDefinition(
        "recognition_disputed", CallPhase.RECOGNITION,
        (TurnIntent.DISPUTES_CASE, TurnIntent.OBJECTION_PROVIDED),
        CallPhase.OBJECTION_HANDLING, "clarify_and_review_objection",
        action=_enter_objection_action, diagram=True,
    ),
    TransitionDefinition(
        "recognition_fallback", CallPhase.RECOGNITION, (), None,
        "ask_case_recognition",
    ),
    TransitionDefinition(
        "objection_case_review_confirmed", CallPhase.OBJECTION_HANDLING,
        (TurnIntent.OUTCOME_CONFIRMED,), CallPhase.ENDED,
        "confirm_outcome_and_close", guard_name="case_review_is_available",
        guard=_case_review_is_available, action=_record_case_review_action, diagram=True,
    ),
    TransitionDefinition(
        "objection_resolution_selected", CallPhase.OBJECTION_HANDLING,
        (TurnIntent.RESOLUTION_SELECTED,), CallPhase.CONFIRMATION,
        "confirm_selected_resolution", guard_name="resolution_is_allowed",
        guard=_resolution_is_allowed, action=_select_resolution_action, diagram=True,
    ),
    TransitionDefinition(
        "objection_resolution_rejected", CallPhase.OBJECTION_HANDLING,
        (TurnIntent.RESOLUTION_SELECTED,), None, "offer_case_approved_resolutions",
        action=_reject_resolution_action,
    ),
    TransitionDefinition(
        "objection_updated", CallPhase.OBJECTION_HANDLING,
        (TurnIntent.OBJECTION_PROVIDED,), None, "summarize_and_review_objection",
        action=_update_objection_action,
    ),
    TransitionDefinition(
        "objection_resolved", CallPhase.OBJECTION_HANDLING,
        (TurnIntent.OBJECTION_RESOLVED, TurnIntent.RECOGNIZES_CASE),
        CallPhase.RESOLUTION, "offer_case_approved_resolutions", diagram=True,
    ),
    TransitionDefinition(
        "objection_escalated", CallPhase.OBJECTION_HANDLING,
        (TurnIntent.CANNOT_RESOLVE,), CallPhase.ESCALATION,
        "explain_limit_and_escalate", diagram=True,
    ),
    TransitionDefinition(
        "objection_fallback", CallPhase.OBJECTION_HANDLING, (), None,
        "clarify_and_review_objection",
    ),
    TransitionDefinition(
        "resolution_disputed", CallPhase.RESOLUTION,
        (TurnIntent.DISPUTES_CASE, TurnIntent.OBJECTION_PROVIDED),
        CallPhase.OBJECTION_HANDLING, "clarify_and_review_objection",
        action=_enter_objection_action, diagram=True,
    ),
    TransitionDefinition(
        "resolution_escalated", CallPhase.RESOLUTION,
        (TurnIntent.CANNOT_RESOLVE,), CallPhase.ESCALATION,
        "explain_limit_and_escalate", diagram=True,
    ),
    TransitionDefinition(
        "resolution_selected", CallPhase.RESOLUTION,
        (TurnIntent.RESOLUTION_SELECTED,), CallPhase.CONFIRMATION,
        "confirm_selected_resolution", guard_name="resolution_is_allowed",
        guard=_resolution_is_allowed, action=_select_resolution_action, diagram=True,
    ),
    TransitionDefinition(
        "resolution_rejected", CallPhase.RESOLUTION,
        (TurnIntent.RESOLUTION_SELECTED,), None, "offer_case_approved_resolutions",
        action=_reject_resolution_action,
    ),
    TransitionDefinition(
        "resolution_fallback", CallPhase.RESOLUTION, (), None,
        "offer_case_approved_resolutions",
    ),
    TransitionDefinition(
        "confirmation_accepted", CallPhase.CONFIRMATION,
        (TurnIntent.OUTCOME_CONFIRMED,), CallPhase.ENDED,
        "confirm_outcome_and_close", diagram=True,
    ),
    TransitionDefinition(
        "confirmation_corrected", CallPhase.CONFIRMATION,
        (TurnIntent.CORRECTION_REQUESTED,), CallPhase.RESOLUTION,
        "correct_and_offer_case_approved_resolutions",
        action=_clear_resolution, diagram=True,
    ),
    TransitionDefinition(
        "confirmation_fallback", CallPhase.CONFIRMATION, (), None,
        "confirm_selected_resolution", action=_confirmation_directive,
    ),
    TransitionDefinition(
        "escalation_completed", CallPhase.ESCALATION,
        (TurnIntent.ESCALATION_COMPLETED,), CallPhase.ENDED,
        "confirm_escalation_and_close", diagram=True,
    ),
    TransitionDefinition(
        "escalation_fallback", CallPhase.ESCALATION, (), None,
        "complete_escalation",
    ),
    TransitionDefinition(
        "ended_fallback", CallPhase.ENDED, (), CallPhase.ENDED,
        "call_already_ended",
    ),
)


TRANSITION_REGISTRY = (*GLOBAL_TRANSITIONS, *PHASE_TRANSITIONS)


def validate_transition_registry() -> None:
    ids = [transition.id for transition in TRANSITION_REGISTRY]
    if len(ids) != len(set(ids)):
        raise ValueError("transition ids must be unique")
    for transition in TRANSITION_REGISTRY:
        if transition.guard is not None and not transition.guard_name:
            raise ValueError(f"transition {transition.id} must name its guard")
        if transition.global_guard != (transition in GLOBAL_TRANSITIONS):
            raise ValueError(f"transition {transition.id} has inconsistent scope")
    for phase in CallPhase:
        fallbacks = [
            transition
            for transition in PHASE_TRANSITIONS
            if transition.source is phase and not transition.intents
        ]
        if len(fallbacks) != 1:
            raise ValueError(f"phase {phase.value} must have exactly one fallback")


def render_business_graph() -> str:
    """Render the stakeholder graph from the executable transition registry."""

    lines = [
        "<!-- Generated by scripts/generate-fsm-graph.py; do not edit manually. -->",
        "# FSM business graph",
        "",
        "```mermaid",
        "flowchart LR",
    ]
    for phase in CallPhase:
        label = phase.value.replace("_", " ").title()
        lines.append(f'    {phase.name}["{label}"]')
    lines.append('    ANY["Any active phase"]')
    lines.append('    START(("START")) --> OPENING')
    for transition in TRANSITION_REGISTRY:
        if not transition.diagram or transition.target is None:
            continue
        source = "ANY" if transition.source is None else transition.source.name
        intents = " / ".join(intent.value for intent in transition.intents) or "continue"
        guard = f" [{transition.guard_name}]" if transition.guard_name else ""
        lines.append(
            f'    {source} -->|"{transition.id}: {intents}{guard}"| '
            f'{transition.target.name}'
        )
    lines.extend(
        [
            '    ENDED --> END(("END"))',
            "```",
            "",
            "The diagram is generated from `TRANSITION_REGISTRY`, the same ordered",
            "declarations executed by the runtime. Self-transitions and conversational",
            "fallbacks are omitted to keep the business journey readable.",
            "",
        ]
    )
    return "\n".join(lines)


def dashboard_graph_spec() -> dict[str, list[dict[str, Any]]]:
    """Project the executable business topology for the live dashboard.

    The dashboard consumes this minimized, serializable view instead of keeping
    a second hand-maintained copy of the FSM topology in JavaScript.
    """

    edges_by_route: dict[tuple[str, str], dict[str, Any]] = {}
    for transition in TRANSITION_REGISTRY:
        if not transition.diagram or transition.target is None:
            continue
        source = (
            transition.source.value
            if transition.source is not None
            else "any_active_phase"
        )
        target = transition.target.value
        edge = edges_by_route.setdefault(
            (source, target),
            {
                "source": source,
                "target": target,
                "transition_ids": [],
                "intents": [],
                "global": transition.global_guard,
            },
        )
        edge["transition_ids"].append(transition.id)
        edge["intents"].extend(intent.value for intent in transition.intents)

    return {
        "nodes": [
            {
                "id": phase.value,
                "label": phase.value.replace("_", " "),
                "terminal": phase is CallPhase.ENDED,
            }
            for phase in CallPhase
        ],
        "edges": list(edges_by_route.values()),
    }


def evaluate_transition_structure(
    *,
    transition_id: str,
    from_phase: str,
    to_phase: str,
    should_end: bool,
) -> dict[str, str]:
    """Validate one observed route against the executable transition registry."""

    transition = next(
        (item for item in TRANSITION_REGISTRY if item.id == transition_id),
        None,
    )
    if transition is None:
        return {
            "status": "fail",
            "reason": f"Unknown transition identifier: {transition_id or 'missing'}.",
        }
    if transition.source is not None and transition.source.value != from_phase:
        return {
            "status": "fail",
            "reason": (
                f"{transition_id} started at {from_phase}; expected "
                f"{transition.source.value}."
            ),
        }
    expected_target = (
        transition.target.value if transition.target is not None else from_phase
    )
    if to_phase != expected_target:
        return {
            "status": "fail",
            "reason": (
                f"{transition_id} ended at {to_phase}; expected {expected_target}."
            ),
        }
    expected_terminal = expected_target == CallPhase.ENDED.value
    if should_end != expected_terminal:
        return {
            "status": "fail",
            "reason": (
                f"{transition_id} terminal flag was {str(should_end).lower()}; "
                f"expected {str(expected_terminal).lower()}."
            ),
        }
    return {
        "status": "pass",
        "reason": f"{transition_id} matches the declared FSM route.",
    }


validate_transition_registry()


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
        "transition_id": state["matched_transition_id"],
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
    verification_fields = event.get("verification_fields", [])
    if not isinstance(verification_fields, list) or not all(
        isinstance(field, str) and field for field in verification_fields
    ):
        raise ValueError("verification_fields must be a list of non-empty strings")


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
