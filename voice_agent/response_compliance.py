"""Deterministic checks that compare spoken text with an FSM directive."""

from __future__ import annotations

from collections.abc import Mapping
import re
import unicodedata
from typing import Any

from .conversation_fsm import CaseContext


_RECOGNITION_DIRECTIVES = frozenset(
    {"disclose_case_and_ask_recognition", "ask_case_recognition"}
)
_CLOSING_DIRECTIVES = frozenset(
    {
        "close_without_further_persuasion",
        "close_wrong_party_without_disclosure",
        "close_after_refusal_limit",
        "confirm_outcome_and_close",
        "confirm_escalation_and_close",
    }
)
_OUTCOME_CONFIRMATION_DIRECTIVES = frozenset(
    {
        "confirm_selected_resolution",
        "confirm_immediate_payment_commitment_without_requesting_payment_credentials",
        "confirm_case_review_request_without_claiming_execution",
        "confirm_outcome_and_close",
    }
)
_RESOLUTION_MARKERS = (
    "pago inmediato",
    "fecha de pago",
    "plan de pago",
    "opciones para resolver",
    "opciones de pago",
    "cual opcion",
    "que opcion",
    "proceder con el pago",
    "payment plan",
    "payment date",
    "pay immediately",
    "payment options",
    "which option",
)
_RECOGNITION_MARKERS = (
    "reconoce",
    "reconocer",
    "le resulta familiar",
    "recognise",
    "recognize",
)
_OUTCOME_CLAIM_MARKERS = (
    "queda registrado",
    "queda registrada",
    "registrar su compromiso",
    "procedere a registrar",
    "procederemos a establecer",
    "le enviare un recordatorio",
    "has been recorded",
    "i will record",
    "we will set",
    "send you a reminder",
)
_PERSUASION_MARKERS = (
    "le gustaria",
    "quiere continuar",
    "opciones de pago",
    "algo mas",
    "would you like",
    "anything else",
)


def evaluate_spoken_response(
    transition: Mapping[str, Any],
    assistant_text: str,
    *,
    case: CaseContext | None,
) -> dict[str, str]:
    """Return a small, deterministic response-versus-directive verdict."""

    text = assistant_text.strip()
    if not text:
        return {"status": "pending", "reason": "Assistant response is not recorded yet."}
    if len(text.split()) < 4 and not bool(transition.get("should_end")):
        return {
            "status": "pending",
            "reason": "Response is too incomplete to evaluate reliably.",
        }

    normalized = _normalize(text)
    directive = str(transition.get("directive") or "")
    verified = bool(transition.get("identity_verified", transition.get("identityVerified")))

    if not verified and case is not None:
        leaked = [
            value
            for value in _sensitive_values(case)
            if value and value in normalized
        ]
        if leaked:
            return {
                "status": "fail",
                "reason": "Response disclosed case data before identity verification.",
            }

    if directive in _RECOGNITION_DIRECTIVES:
        if any(marker in normalized for marker in _RESOLUTION_MARKERS):
            return {
                "status": "fail",
                "reason": "Response offered or accepted a resolution while recognition was required.",
            }
        if not any(marker in normalized for marker in _RECOGNITION_MARKERS):
            return {
                "status": "fail",
                "reason": "Response did not ask the caller to recognize the disclosed case.",
            }

    if (
        directive not in _OUTCOME_CONFIRMATION_DIRECTIVES
        and any(marker in normalized for marker in _OUTCOME_CLAIM_MARKERS)
    ):
        return {
            "status": "fail",
            "reason": "Response claimed an outcome or action before the FSM authorized it.",
        }

    if directive in _CLOSING_DIRECTIVES and (
        "?" in text or any(marker in normalized for marker in _PERSUASION_MARKERS)
    ):
        return {
            "status": "fail",
            "reason": "Closing response continued the conversation or asked another question.",
        }

    return {
        "status": "pass",
        "reason": f"Response complies with {directive or 'the current directive'}.",
    }


def _sensitive_values(case: CaseContext) -> tuple[str, ...]:
    values: list[str] = []
    for field in (
        "customer_name",
        "disclosure_summary",
        "product_name",
        "reference",
        "due_date",
    ):
        value = case.get(field)
        if isinstance(value, str) and len(value.strip()) >= 4:
            values.append(_normalize(value))
    amount = case.get("amount_minor")
    if isinstance(amount, int):
        values.append(str(amount))
        values.append(str(amount // 100))
    return tuple(dict.fromkeys(values))


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    lowered = without_marks.lower().replace("’", "'")
    return re.sub(r"\s+", " ", lowered).strip()
