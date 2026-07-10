"""FSM-gated wrapper around LiveKit's call termination tool."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from livekit.agents import RunContext, ToolError
from livekit.agents.beta.tools import EndCallTool

TERMINAL_FAREWELL_INSTRUCTIONS = (
    "Say a warm, natural farewell in two short sentences. Briefly confirm the "
    "agreed outcome once, thank the caller for their time, and wish them a good "
    "day. Do not ask a question, introduce new details, repeat the negotiation, "
    "or sound abrupt."
)


class TerminalEndCallTool(EndCallTool):
    """Release call resources only after the external FSM reaches terminal state."""

    def __init__(self, *, is_terminal: Callable[[], bool], **kwargs: Any) -> None:
        self._is_terminal = is_terminal
        super().__init__(
            extra_description=(
                "The external runtime FSM is authoritative. Call this tool only when "
                "the current runtime control has should_end=true and explicitly "
                "requires end_call."
            ),
            **kwargs,
        )

    async def _end_call(self, ctx: RunContext) -> Any | None:
        if not self._is_terminal():
            raise ToolError(
                "end_call rejected: the external conversation FSM is not terminal"
            )
        return await super()._end_call(ctx)
