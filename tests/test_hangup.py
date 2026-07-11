from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from livekit.agents import ToolError
from livekit.agents.beta.tools import EndCallTool

from voice_agent.hangup import (
    TERMINAL_FAREWELL_INSTRUCTIONS,
    TerminalEndCallTool,
    build_terminal_farewell,
)


class TerminalEndCallToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_call_before_fsm_is_terminal(self) -> None:
        toolset = TerminalEndCallTool(is_terminal=lambda: False, delete_room=False)
        tool = toolset.tools[0]

        with self.assertRaisesRegex(ToolError, "FSM is not terminal"):
            await tool(SimpleNamespace())

    async def test_delegates_to_livekit_end_call_when_terminal(self) -> None:
        speech_handle = SimpleNamespace(add_done_callback=Mock())
        ctx = SimpleNamespace(speech_handle=speech_handle)
        on_terminal_speech_done = Mock()
        with patch.object(
            EndCallTool,
            "_end_call",
            new=AsyncMock(return_value="closing"),
        ) as end_call:
            toolset = TerminalEndCallTool(
                is_terminal=lambda: True,
                delete_room=False,
                on_terminal_speech_done=on_terminal_speech_done,
            )
            result = await toolset.tools[0](ctx)

        self.assertEqual(result, "closing")
        speech_handle.add_done_callback.assert_called_once_with(on_terminal_speech_done)
        end_call.assert_awaited_once_with(ctx)

    def test_exposes_end_call_function_name(self) -> None:
        toolset = TerminalEndCallTool(is_terminal=lambda: True, delete_room=False)
        self.assertEqual(toolset.tools[0].info.name, "end_call")

    def test_terminal_farewell_is_warm_and_outcome_aware(self) -> None:
        self.assertIn("warm, natural farewell", TERMINAL_FAREWELL_INSTRUCTIONS)
        self.assertIn("confirm the agreed outcome once", TERMINAL_FAREWELL_INSTRUCTIONS)
        self.assertIn("thank the caller", TERMINAL_FAREWELL_INSTRUCTIONS)
        self.assertIn("Do not ask a question", TERMINAL_FAREWELL_INSTRUCTIONS)

    def test_deterministic_refusal_farewell_is_question_free(self) -> None:
        state = {
            "case": {"locale": "es-ES"},
            "response_directive": "close_after_refusal_limit",
            "resolution_type": "case_review",
        }

        farewell = build_terminal_farewell(state)

        self.assertEqual(
            farewell,
            "Entiendo su decisión. Gracias por su tiempo; que tenga un buen día.",
        )
        self.assertNotIn("?", farewell)

    def test_deterministic_case_review_farewell_records_without_execution_claim(self) -> None:
        state = {
            "case": {"locale": "en-GB"},
            "response_directive": "confirm_outcome_and_close",
            "resolution_type": "case_review",
        }

        farewell = build_terminal_farewell(state)

        self.assertIn("review request has been recorded", farewell)
        self.assertNotIn("will review", farewell)


if __name__ == "__main__":
    unittest.main()
