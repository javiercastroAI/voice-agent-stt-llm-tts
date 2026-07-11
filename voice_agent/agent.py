"""Voice agent implementation."""

from __future__ import annotations

from collections.abc import Callable
import asyncio
from contextlib import suppress

from livekit.agents import Agent, ChatContext, ChatMessage, tokenize, tts
from livekit.agents.llm import StopResponse

from .case_context import load_case_context
from .barge_in import BargeTurnDecision
from .config import AgentConfig
from .conversation_controller import (
    ConversationAlreadyEnded,
    ConversationController,
    build_case_review_consent_offer,
    build_runtime_control_message,
)
from .diarized_stt import DiarizedTranscript, OpenAIDiarizedSTT
from .echo_guard import EchoInputGuard
from .intent_interpreter import (
    OpenAIIntentInterpreter,
    explicit_resolution_selection,
    is_explicit_termination,
    is_payment_refusal,
)
from .fsm_trace import FSMTraceRecorder
from .hangup import (
    TERMINAL_FAREWELL_INSTRUCTIONS,
    TerminalEndCallTool,
    build_terminal_farewell,
)

_PLUGIN_IMPORT_ERROR: ModuleNotFoundError | None = None

try:
    from livekit.plugins import openai as openai_plugin
    from livekit.plugins import silero as silero_plugin
except ModuleNotFoundError as exc:
    openai_plugin = None
    silero_plugin = None
    _PLUGIN_IMPORT_ERROR = exc


def _load_plugins():
    if _PLUGIN_IMPORT_ERROR is not None or openai_plugin is None or silero_plugin is None:
        raise RuntimeError(
            "Missing LiveKit voice plugin dependencies. Install the project dependencies with "
            "`python -m pip install -e .` before running the agent."
        ) from _PLUGIN_IMPORT_ERROR

    return openai_plugin, silero_plugin


def _build_realtime_turn_detection(config: AgentConfig) -> dict[str, object]:
    return {
        "type": "server_vad",
        "threshold": config.openai_fast_stt_vad_threshold,
        "prefix_padding_ms": config.openai_fast_stt_prefix_padding_ms,
        "silence_duration_ms": config.openai_fast_stt_turn_silence_ms,
    }


def build_silero_vad_options(config: AgentConfig) -> dict[str, float]:
    """Map the noise-robust runtime profile to Silero's public API."""

    return {
        "activation_threshold": config.silero_vad_activation_threshold,
        "deactivation_threshold": config.silero_vad_deactivation_threshold,
        "min_speech_duration": config.silero_vad_min_speech_seconds,
        "min_silence_duration": config.silero_vad_min_silence_seconds,
        "prefix_padding_duration": config.silero_vad_prefix_padding_seconds,
    }


class AssistantAgent(Agent):
    """Notebook-equivalent voice assistant."""

    def __init__(
        self,
        config: AgentConfig,
        *,
        on_user_diarized: Callable[[DiarizedTranscript], None] | None = None,
        conversation_controller: ConversationController | None = None,
        fsm_trace_recorder: FSMTraceRecorder | None = None,
        echo_input_guard: EchoInputGuard | None = None,
        consume_barge_turn_decision: Callable[[str], BargeTurnDecision | None] | None = None,
        delete_room_on_hangup: bool = True,
    ) -> None:
        openai, silero = _load_plugins()

        llm = openai.LLM(
            model=config.openai_model,
            max_completion_tokens=config.openai_max_completion_tokens,
            temperature=config.openai_llm_temperature,
            api_key=config.openai_api_key,
        )
        use_fast_path = config.voice_pipeline_mode == "controlled_fast"
        runtime_stt_model = (
            config.openai_fast_stt_model
            if use_fast_path
            else config.openai_stt_model
        )
        diarization_callback = (
            None
            if use_fast_path
            else on_user_diarized
        )
        stt = OpenAIDiarizedSTT(
            model=runtime_stt_model,
            language=config.openai_stt_language,
            api_key=config.openai_api_key,
            use_realtime=use_fast_path and config.openai_fast_stt_realtime,
            turn_detection=_build_realtime_turn_detection(config),
            on_diarization=diarization_callback,
        )
        tts = openai.TTS(
            model=config.openai_tts_model,
            voice=config.openai_tts_voice,
            response_format=config.openai_tts_response_format,
            speed=config.openai_tts_speed,
            instructions=config.openai_tts_instructions,
            api_key=config.openai_api_key,
        )
        vad = silero.VAD.load(**build_silero_vad_options(config))

        if conversation_controller is None and config.fsm_enabled:
            case = load_case_context(config.case_context_file)
            interpreter = OpenAIIntentInterpreter(
                api_key=config.openai_api_key or "",
                model=config.openai_intent_model,
                timeout_seconds=config.fsm_intent_timeout_seconds,
            )
            conversation_controller = ConversationController(
                case=case,
                interpreter=interpreter,
            )
        self._conversation_controller = conversation_controller
        self._fsm_trace_recorder = fsm_trace_recorder
        self._echo_input_guard = echo_input_guard
        self._consume_barge_turn_decision = consume_barge_turn_decision
        self._auto_opening_enabled = (
            config.fsm_enabled and config.fsm_auto_opening_enabled
        )
        self._opening_started = False
        self._terminal_shutdown_requested = False
        self._terminal_farewell_started = False
        self._hang_up_tool_called = False

        end_call_tool = TerminalEndCallTool(
            is_terminal=lambda: (
                self._conversation_controller is not None
                and self._conversation_controller.state["should_end"]
            ),
            delete_room=delete_room_on_hangup,
            end_instructions=TERMINAL_FAREWELL_INSTRUCTIONS,
            on_tool_called=self._on_end_call_tool_called,
            on_terminal_speech_done=(
                self._fsm_trace_recorder.record_terminal_speech_handle
                if self._fsm_trace_recorder is not None
                else None
            ),
        )

        super().__init__(
            instructions=config.agent_instructions,
            tools=[end_call_tool],
            stt=stt,
            llm=llm,
            tts=tts,
            vad=vad,
        )

    def observe_agent_state(
        self,
        *,
        old_state: str,
        new_state: str,
        created_at: float,
    ) -> None:
        if self._echo_input_guard is not None:
            self._echo_input_guard.on_agent_state_changed(
                old_state=old_state,
                new_state=new_state,
                created_at=created_at,
            )

    async def tts_node(self, text, model_settings):
        """Pace non-streaming TTS sentences to avoid audible multi-request gaps."""

        activity = self._get_activity_or_raise()
        if activity.tts is None:
            raise RuntimeError("tts_node called without a configured TTS provider")
        wrapped_tts = activity.tts
        if not wrapped_tts.capabilities.streaming:
            wrapped_tts = tts.StreamAdapter(
                tts=wrapped_tts,
                sentence_tokenizer=tokenize.blingfire.SentenceTokenizer(retain_format=True),
                text_pacing=tts.SentenceStreamPacer(
                    min_remaining_audio=0.8,
                    max_text_length=240,
                ),
            )
        conn_options = activity.session.conn_options.tts_conn_options
        async with wrapped_tts.stream(conn_options=conn_options) as stream:
            async def forward_input() -> None:
                async for chunk in text:
                    stream.push_text(chunk)
                stream.end_input()

            forward_task = asyncio.create_task(forward_input())
            try:
                async for event in stream:
                    yield event.frame
            finally:
                if not forward_task.done():
                    forward_task.cancel()
                with suppress(asyncio.CancelledError):
                    await forward_task

    async def on_enter(self) -> None:
        """Schedule one interruptible, disclosure-safe outbound opening."""

        if (
            self._conversation_controller is None
            or not self._auto_opening_enabled
            or self._opening_started
        ):
            return
        self._opening_started = True
        try:
            self.session.generate_reply(
                instructions=build_runtime_control_message(
                    self._conversation_controller.state
                ),
                allow_interruptions=True,
            )
            if self._fsm_trace_recorder is not None:
                self._fsm_trace_recorder.record_opening(
                    self._conversation_controller.state
                )
        except Exception:
            self._opening_started = False
            raise

    async def _on_end_call_tool_called(self, _event) -> None:
        """Mark that LiveKit's end-call tool owns terminal resource cleanup."""

        self._hang_up_tool_called = True

    async def on_user_turn_completed(
        self,
        turn_ctx: ChatContext,
        new_message: ChatMessage,
    ) -> None:
        """Advance the external FSM before the speaking LLM receives the turn."""

        if self._conversation_controller is None:
            return
        transcript = (new_message.text_content or "").strip()
        if not transcript:
            raise StopResponse()
        if self._consume_barge_turn_decision is not None:
            decision = self._consume_barge_turn_decision(transcript)
            if decision is not None and not decision.accepted:
                if self._fsm_trace_recorder is not None:
                    self._fsm_trace_recorder.record_suppressed_user_turn(
                        user_transcript=transcript,
                        reason=decision.reason,
                    )
                raise StopResponse()
        state_before_turn = self._conversation_controller.state
        preserve_input = (
            is_explicit_termination(transcript)
            or is_payment_refusal(transcript, state_before_turn)
            or explicit_resolution_selection(transcript, state_before_turn) is not None
        )
        if self._echo_input_guard is not None and not preserve_input:
            decision = self._echo_input_guard.evaluate(transcript)
            if decision.suppress:
                if self._fsm_trace_recorder is not None and decision.reason is not None:
                    self._fsm_trace_recorder.record_suppressed_user_turn(
                        user_transcript=transcript,
                        reason=decision.reason,
                    )
                raise StopResponse()
        try:
            state = await self._conversation_controller.process_user_turn(transcript)
        except ConversationAlreadyEnded as exc:
            raise StopResponse() from exc
        if state["should_end"]:
            self._terminal_farewell_started = False
        if self._fsm_trace_recorder is not None:
            self._fsm_trace_recorder.record_transition(
                user_transcript=transcript,
                event=self._conversation_controller.last_event,
                state=state,
            )
        if state["should_end"]:
            farewell = build_terminal_farewell(state)
            speech_handle = self.session.say(
                farewell,
                allow_interruptions=False,
                add_to_chat_ctx=True,
            )
            self._terminal_farewell_started = True
            if self._fsm_trace_recorder is not None:
                speech_handle.add_done_callback(
                    self._fsm_trace_recorder.record_terminal_speech_handle
                )
            raise StopResponse()
        review_consent_offer = build_case_review_consent_offer(state)
        if review_consent_offer is not None:
            self.session.say(
                review_consent_offer,
                allow_interruptions=True,
                add_to_chat_ctx=True,
            )
            raise StopResponse()
        turn_ctx.add_message(
            role="system",
            content=build_runtime_control_message(state),
        )

    def consume_terminal_shutdown(self, *, old_state: str, new_state: str) -> bool:
        """Return true once after the terminal farewell finishes speaking."""

        if self._conversation_controller is None or self._terminal_shutdown_requested:
            return False
        call_ended = self._conversation_controller.state["should_end"]
        if not call_ended:
            return False
        if self._hang_up_tool_called:
            return False
        if old_state != "speaking" and new_state == "speaking":
            self._terminal_farewell_started = True
            return False
        speech_finished = old_state == "speaking" and new_state in {"listening", "idle"}
        if not self._terminal_farewell_started or not speech_finished:
            return False
        self._terminal_shutdown_requested = True
        return True
