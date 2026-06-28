"""Voice agent implementation."""

from __future__ import annotations

from collections.abc import Callable

from livekit.agents import Agent

from .config import AgentConfig
from .diarized_stt import DiarizedTranscript, OpenAIDiarizedSTT

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


class AssistantAgent(Agent):
    """Notebook-equivalent voice assistant."""

    def __init__(
        self,
        config: AgentConfig,
        *,
        on_user_diarized: Callable[[DiarizedTranscript], None] | None = None,
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
        vad = silero.VAD.load()

        super().__init__(
            instructions=config.agent_instructions,
            stt=stt,
            llm=llm,
            tts=tts,
            vad=vad,
        )
