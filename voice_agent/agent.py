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


class AssistantAgent(Agent):
    """Notebook-equivalent voice assistant."""

    def __init__(
        self,
        config: AgentConfig,
        *,
        on_user_diarized: Callable[[DiarizedTranscript], None] | None = None,
    ) -> None:
        openai, silero = _load_plugins()

        llm = openai.LLM(model=config.openai_model, api_key=config.openai_api_key)
        stt = OpenAIDiarizedSTT(
            model=config.openai_stt_model,
            api_key=config.openai_api_key,
            on_diarization=on_user_diarized,
        )
        tts = openai.TTS(
            model=config.openai_tts_model,
            voice=config.openai_tts_voice,
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
