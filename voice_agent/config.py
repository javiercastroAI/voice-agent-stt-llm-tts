"""Configuration loading and validation for the voice agent."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_OPENAI_STT_MODEL = "gpt-4o-transcribe-diarize"
DEFAULT_OPENAI_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_OPENAI_TTS_VOICE = "marin"
DEFAULT_AGENT_INSTRUCTIONS = "You are a helpful assistant communicating via voice"
LIVEKIT_COMMANDS = frozenset({"dev", "start"})
SUPPORTED_COMMANDS = frozenset({"console", "dev", "start"})
HOME_ENV_FALLBACK_KEYS = frozenset({"OPENAI_API_KEY"})
PLACEHOLDER_VALUES = frozenset(
    {
        "your-openai-api-key",
        "wss://your-project.livekit.cloud",
        "your-livekit-api-key",
        "your-livekit-api-secret",
    }
)


class ConfigError(ValueError):
    """Raised when required environment variables are missing."""


def _clean(value: str | None) -> str | None:
    if value is None:
        return None

    stripped = value.strip()
    if stripped in PLACEHOLDER_VALUES:
        return None
    return stripped or None


@dataclass(frozen=True)
class AgentConfig:
    """Normalized environment configuration."""

    openai_api_key: str | None
    livekit_url: str | None
    livekit_api_key: str | None
    livekit_api_secret: str | None
    openai_model: str = DEFAULT_OPENAI_MODEL
    openai_stt_model: str = DEFAULT_OPENAI_STT_MODEL
    openai_tts_model: str = DEFAULT_OPENAI_TTS_MODEL
    openai_tts_voice: str = DEFAULT_OPENAI_TTS_VOICE
    agent_instructions: str = DEFAULT_AGENT_INSTRUCTIONS

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        load_dotenv_file: bool = False,
    ) -> "AgentConfig":
        source = dict(environ) if environ is not None else cls._load_runtime_env(load_dotenv_file)

        openai_model = _clean(source.get("OPENAI_MODEL")) or DEFAULT_OPENAI_MODEL
        openai_stt_model = _clean(source.get("OPENAI_STT_MODEL")) or DEFAULT_OPENAI_STT_MODEL
        openai_tts_model = _clean(source.get("OPENAI_TTS_MODEL")) or DEFAULT_OPENAI_TTS_MODEL
        openai_tts_voice = _clean(source.get("OPENAI_TTS_VOICE")) or DEFAULT_OPENAI_TTS_VOICE
        instructions = _clean(source.get("AGENT_INSTRUCTIONS")) or DEFAULT_AGENT_INSTRUCTIONS

        return cls(
            openai_api_key=_clean(source.get("OPENAI_API_KEY")),
            livekit_url=_clean(source.get("LIVEKIT_URL")),
            livekit_api_key=_clean(source.get("LIVEKIT_API_KEY")),
            livekit_api_secret=_clean(source.get("LIVEKIT_API_SECRET")),
            openai_model=openai_model,
            openai_stt_model=openai_stt_model,
            openai_tts_model=openai_tts_model,
            openai_tts_voice=openai_tts_voice,
            agent_instructions=instructions,
        )

    @staticmethod
    def _load_runtime_env(load_dotenv_file: bool) -> dict[str, str]:
        from os import environ as os_environ

        merged = dict(os_environ)
        if not load_dotenv_file:
            return merged

        repo_env = dotenv_values(Path.cwd() / ".env")
        home_env = dotenv_values(Path.home() / ".env")

        for key, value in repo_env.items():
            cleaned = _clean(value)
            if cleaned is not None:
                merged.setdefault(key, cleaned)

        for key in HOME_ENV_FALLBACK_KEYS:
            cleaned = _clean(home_env.get(key))
            if cleaned is not None:
                merged.setdefault(key, cleaned)

        return merged

    def validate_for_command(self, command: str) -> None:
        if command not in SUPPORTED_COMMANDS:
            return

        required = {
            "OPENAI_API_KEY": self.openai_api_key,
        }
        if command in LIVEKIT_COMMANDS:
            required.update(
                {
                    "LIVEKIT_URL": self.livekit_url,
                    "LIVEKIT_API_KEY": self.livekit_api_key,
                    "LIVEKIT_API_SECRET": self.livekit_api_secret,
                }
            )

        missing = [name for name, value in required.items() if not value]
        if missing:
            missing_text = ", ".join(missing)
            raise ConfigError(
                f"Missing required environment variables for `{command}`: {missing_text}"
            )
