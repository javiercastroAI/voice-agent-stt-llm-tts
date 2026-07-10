from __future__ import annotations

from types import SimpleNamespace
import unittest

from voice_agent.soft_quality import SoftQualityJudgment, judge_soft_quality


class FakeResponses:
    def __init__(self) -> None:
        self.kwargs = None

    async def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            output_parsed=SoftQualityJudgment(
                clarity="pass",
                tone="warn",
                concision="pass",
                notes=["Tone could be warmer."],
            )
        )


class SoftQualityTests(unittest.IsolatedAsyncioTestCase):
    async def test_judge_is_structured_opt_in_and_does_not_store(self) -> None:
        responses = FakeResponses()
        events = [
            {"type": "fsm_transition", "turnId": "1", "directive": "verify_identity", "userTranscript": "Hello"},
            {"type": "assistant_response", "turnId": "1", "assistantText": "Please confirm your role."},
        ]

        judgment = await judge_soft_quality(
            events,
            api_key="test-key",
            model="gpt-4o-mini",
            client=SimpleNamespace(responses=responses),
        )

        self.assertEqual(judgment.status, "warn")
        self.assertFalse(responses.kwargs["store"])
        self.assertIs(responses.kwargs["text_format"], SoftQualityJudgment)
        self.assertNotIn("privacy", json_text := responses.kwargs["input"].lower())
        self.assertIn("please confirm your role", json_text)


if __name__ == "__main__":
    unittest.main()
