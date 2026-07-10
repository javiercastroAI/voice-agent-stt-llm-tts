from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from livekit.agents import ToolError
from livekit.agents.beta.tools import EndCallTool

from voice_agent.hangup import TERMINAL_FAREWELL_INSTRUCTIONS, TerminalEndCallTool


class TerminalEndCallToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_call_before_fsm_is_terminal(self) -> None:
        toolset = TerminalEndCallTool(is_terminal=lambda: False, delete_room=False)
        tool = toolset.tools[0]

        with self.assertRaisesRegex(ToolError, "FSM is not terminal"):
            await tool(SimpleNamespace())

    async def test_delegates_to_livekit_end_call_when_terminal(self) -> None:
        ctx = SimpleNamespace()
        with patch.object(
            EndCallTool,
            "_end_call",
            new=AsyncMock(return_value="closing"),
        ) as end_call:
            toolset = TerminalEndCallTool(is_terminal=lambda: True, delete_room=False)
            result = await toolset.tools[0](ctx)

        self.assertEqual(result, "closing")
        end_call.assert_awaited_once_with(ctx)

    def test_exposes_end_call_function_name(self) -> None:
        toolset = TerminalEndCallTool(is_terminal=lambda: True, delete_room=False)
        self.assertEqual(toolset.tools[0].info.name, "end_call")

    def test_terminal_farewell_is_warm_and_outcome_aware(self) -> None:
        self.assertIn("warm, natural farewell", TERMINAL_FAREWELL_INSTRUCTIONS)
        self.assertIn("confirm the agreed outcome once", TERMINAL_FAREWELL_INSTRUCTIONS)
        self.assertIn("thank the caller", TERMINAL_FAREWELL_INSTRUCTIONS)
        self.assertIn("Do not ask a question", TERMINAL_FAREWELL_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
