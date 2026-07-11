"""FSM-gated wrapper around LiveKit's call termination tool."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from livekit.agents import RunContext, ToolError
from livekit.agents.beta.tools import EndCallTool

TERMINAL_FAREWELL_INSTRUCTIONS = (
    "Say a warm, natural farewell in two short sentences. Briefly confirm the "
    "agreed outcome once, thank the caller for their time, and wish them a good "
    "day. Do not ask a question, introduce new details, repeat the negotiation, "
    "or sound abrupt."
)


def build_terminal_farewell(state: Mapping[str, Any]) -> str:
    """Return one locale-aware farewell derived only from terminal FSM state."""

    locale = str(state.get("case", {}).get("locale", "")).lower()
    spanish = locale.startswith("es")
    directive = str(state.get("response_directive") or "")
    resolution = str(state.get("resolution_type") or "")

    if directive == "close_after_refusal_limit":
        return (
            "Entiendo su decisión. Gracias por su tiempo; que tenga un buen día."
            if spanish
            else "I understand your decision. Thank you for your time; have a good day."
        )
    if directive == "close_after_repetition_limit":
        return (
            "No hemos podido avanzar en esta llamada, así que la finalizamos. "
            "Gracias por su tiempo; que tenga un buen día."
            if spanish
            else "We have not been able to make progress in this call, so we will end it. "
            "Thank you for your time; have a good day."
        )
    if directive == "close_wrong_party_without_disclosure":
        return (
            "Disculpe la molestia. Gracias por su tiempo; que tenga un buen día."
            if spanish
            else "I apologize for the inconvenience. Thank you for your time; have a good day."
        )
    if directive == "close_without_further_persuasion":
        return (
            "De acuerdo, terminamos aquí. Gracias por su tiempo; que tenga un buen día."
            if spanish
            else "Understood, we will end here. Thank you for your time; have a good day."
        )
    if resolution == "case_review":
        return (
            "Queda registrada su solicitud de revisión. Gracias por su tiempo; que tenga un buen día."
            if spanish
            else "Your review request has been recorded. Thank you for your time; have a good day."
        )
    if resolution == "immediate_payment":
        return (
            "Queda registrado su compromiso de pago. Gracias por su tiempo; que tenga un buen día."
            if spanish
            else "Your payment commitment has been recorded. Thank you for your time; have a good day."
        )
    return (
        "Queda registrado lo acordado. Gracias por su tiempo; que tenga un buen día."
        if spanish
        else "The agreed outcome has been recorded. Thank you for your time; have a good day."
    )


class TerminalEndCallTool(EndCallTool):
    """Release call resources only after the external FSM reaches terminal state."""

    def __init__(
        self,
        *,
        is_terminal: Callable[[], bool],
        on_terminal_speech_done: Callable[[object], object] | None = None,
        **kwargs: Any,
    ) -> None:
        self._is_terminal = is_terminal
        self._on_terminal_speech_done = on_terminal_speech_done
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
        if self._on_terminal_speech_done is not None:
            ctx.speech_handle.add_done_callback(self._on_terminal_speech_done)
        return await super()._end_call(ctx)
