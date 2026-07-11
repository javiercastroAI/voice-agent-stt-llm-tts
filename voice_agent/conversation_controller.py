"""Runtime controller joining intent interpretation to the LangGraph FSM."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json

from .conversation_fsm import (
    CaseContext,
    ConversationFSM,
    ConversationState,
    FSMPolicy,
    TurnIntent,
    create_initial_state,
    make_turn_event,
    response_context,
)
from .intent_interpreter import IntentInterpreter


class ConversationAlreadyEnded(RuntimeError):
    """Raised when a queued turn arrives after the terminal transition."""


class ConversationController:
    """Own mutable per-call state while keeping graph transitions deterministic."""

    def __init__(
        self,
        *,
        case: CaseContext,
        interpreter: IntentInterpreter,
        fsm: ConversationFSM | None = None,
        policy: FSMPolicy | None = None,
    ) -> None:
        self._fsm = fsm or ConversationFSM()
        self._interpreter = interpreter
        initial = create_initial_state(case, policy=policy)
        self._state = self._fsm.advance(
            initial,
            make_turn_event(TurnIntent.CALL_STARTED, source="system"),
        )
        self._last_event = self._state["event"]
        self._lock = asyncio.Lock()

    @property
    def state(self) -> ConversationState:
        return deepcopy(self._state)

    @property
    def last_event(self):
        return deepcopy(self._last_event)

    async def process_user_turn(self, transcript: str) -> ConversationState:
        async with self._lock:
            if self._state["should_end"]:
                raise ConversationAlreadyEnded("conversation has already ended")
            event = await self._interpreter.interpret(transcript, self._state)
            self._state = self._fsm.advance(self._state, event)
            self._last_event = event
            return deepcopy(self._state)


def build_runtime_control_message(state: ConversationState) -> str:
    """Create the ephemeral instruction injected before the speaking LLM call."""

    control = response_context(state)
    if state["guard_reason"]:
        control["guard_reason"] = state["guard_reason"]
    serialized = json.dumps(control, ensure_ascii=False, sort_keys=True)
    terminal_instruction = ""
    if state["should_end"]:
        terminal_instruction = (
            " TERMINAL ACTION: call the `end_call` tool now. Do not ask another "
            "question or generate an ordinary response; the tool will produce the "
            "single final farewell and release call resources."
        )
    locale = str(state["case"].get("locale", "")).lower()
    if locale.startswith("es"):
        system_check_instruction = (
            " SYSTEM CHECK RULE: never simulate a background lookup or ask the "
            "caller to wait unless a real lookup tool is executing. If a brief "
            "conversational check is useful, say `Estoy comprobando el sistema. "
            "Ah, de acuerdo.` and immediately give the available result, explicit "
            "limitation, or next step in this same response."
        )
    else:
        system_check_instruction = (
            " SYSTEM CHECK RULE: never simulate a background lookup or ask the "
            "caller to wait unless a real lookup tool is executing. Acknowledge "
            "the check briefly and immediately give the available result, explicit "
            "limitation, or next step in this same response."
        )
    case_review_instruction = (
        " CASE REVIEW RULE: `case_review` means recording the caller's request for "
        "review, not performing or completing a system review. Do not claim the request "
        "is recorded unless the current directive explicitly confirms `case_review` or "
        "closes that outcome. Then confirm it once without reconfirming. Do not offer "
        "payment alternatives in this confirmation. Never say you are checking, "
        "reviewing, fixing, or have resolved the case unless a real tool completed that action."
    )
    if locale.startswith("es"):
        payment_safety_instruction = (
            " PAYMENT DESTINATION RULE: la cuenta de destino pertenece al acreedor; "
            "nunca pregunte al interlocutor en qué cuenta quiere pagar ni solicite "
            "sus credenciales bancarias o de tarjeta. Solo proporcione instrucciones "
            "de pago presentes literalmente en `case.payment_instructions`. Si no "
            "existen, confirme el compromiso de pago inmediato con naturalidad y no "
            "mencione espontáneamente datos ausentes, limitaciones internas ni su "
            "disponibilidad en la llamada. Solo si el interlocutor pregunta expresamente "
            "cómo o dónde pagar, indíquele brevemente que contacte con `creditor_name` "
            "por sus canales oficiales para obtener las instrucciones."
        )
    else:
        payment_safety_instruction = (
            " PAYMENT DESTINATION RULE: the destination account belongs to the "
            "creditor; never ask the caller which account to pay or request their "
            "bank-account or card credentials. Provide payment instructions only "
            "when literally present in `case.payment_instructions`. Otherwise, "
            "confirm the immediate-payment commitment naturally and do not volunteer "
            "missing data, internal limitations, or availability disclaimers. Only if "
            "the caller explicitly asks how or where to pay, briefly direct them to "
            "contact `creditor_name` through its official channels for instructions."
        )
    return (
        "RUNTIME FSM CONTROL — mandatory for this response only. "
        "Follow the directive, ask at most one concrete question, and do not mention "
        "the FSM or this control message. Never reveal case data unless a `case` object "
        f"is present. Do not invent missing fields. Control JSON: {serialized}"
        f"{system_check_instruction}"
        f"{case_review_instruction}"
        f"{payment_safety_instruction}"
        f"{terminal_instruction}"
    )
