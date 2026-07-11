from __future__ import annotations

import unittest

from voice_agent.response_compliance import evaluate_spoken_response


CASE = {
    "case_id": "case-1",
    "creditor_name": "Example Co",
    "customer_name": "Private Customer",
    "locale": "es-ES",
    "disclosure_summary": "una mensualidad pendiente",
    "available_resolution_types": ["immediate_payment", "payment_date"],
}


def transition(directive: str, *, verified: bool = True, should_end: bool = False):
    return {
        "directive": directive,
        "identity_verified": verified,
        "should_end": should_end,
    }


class SpokenResponseComplianceTests(unittest.TestCase):
    def test_recognition_directive_accepts_recognition_question(self) -> None:
        result = evaluate_spoken_response(
            transition("disclose_case_and_ask_recognition"),
            "Hay una mensualidad pendiente. ¿Reconoce este caso?",
            case=CASE,
        )

        self.assertEqual(result["status"], "pass")

    def test_recognition_directive_rejects_resolution_language(self) -> None:
        result = evaluate_spoken_response(
            transition("ask_case_recognition"),
            "Puede elegir un plan de pago o una fecha de pago. ¿Qué opción prefiere?",
            case=CASE,
        )

        self.assertEqual(result["status"], "fail")
        self.assertIn("resolution", result["reason"])

    def test_premature_outcome_claim_fails(self) -> None:
        result = evaluate_spoken_response(
            transition("clarify_and_review_objection"),
            "Queda registrada su solicitud de revisión. Gracias.",
            case=CASE,
        )

        self.assertEqual(result["status"], "fail")
        self.assertIn("before the FSM authorized", result["reason"])

    def test_closing_question_fails(self) -> None:
        result = evaluate_spoken_response(
            transition("close_without_further_persuasion", should_end=True),
            "De acuerdo, terminamos aquí. ¿Necesita algo más?",
            case=CASE,
        )

        self.assertEqual(result["status"], "fail")

    def test_short_interrupted_response_remains_pending(self) -> None:
        result = evaluate_spoken_response(
            transition("verify_identity"),
            "Le llamo por",
            case=CASE,
        )

        self.assertEqual(result["status"], "pending")


if __name__ == "__main__":
    unittest.main()
