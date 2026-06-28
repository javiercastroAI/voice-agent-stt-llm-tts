"""Configuration loading and validation for the voice agent."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_MAX_COMPLETION_TOKENS = 60
DEFAULT_OPENAI_LLM_TEMPERATURE = 0.2
DEFAULT_VOICE_PIPELINE_MODE = "controlled_fast"
DEFAULT_OPENAI_STT_MODEL = "gpt-4o-transcribe-diarize"
DEFAULT_OPENAI_FAST_STT_MODEL = "gpt-4o-mini-transcribe"
DEFAULT_OPENAI_FAST_STT_REALTIME = True
DEFAULT_OPENAI_FAST_STT_TURN_SILENCE_MS = 150
DEFAULT_OPENAI_FAST_STT_PREFIX_PADDING_MS = 300
DEFAULT_OPENAI_FAST_STT_VAD_THRESHOLD = 0.5
DEFAULT_OPENAI_STT_LANGUAGE = "es"
DEFAULT_OPENAI_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_OPENAI_TTS_VOICE = "marin"
DEFAULT_OPENAI_TTS_RESPONSE_FORMAT = "pcm"
DEFAULT_OPENAI_TTS_SPEED = 1.05
DEFAULT_OPENAI_TTS_INSTRUCTIONS = (
    "Speak in Spanish from Spain with a natural, professional contact-center tone."
)
DEFAULT_AGENT_INSTRUCTIONS_FILE = "prompts/collections-es.md"
DEFAULT_AGENT_INSTRUCTIONS_FALLBACK = (
    "You are a concise, professional voice assistant. Ask one clear question per turn."
)
DEFAULT_BARGE_IN_ENABLED = True
DEFAULT_BARGE_IN_TURN_DETECTION_MODE: str | None = None
DEFAULT_BARGE_IN_ENDPOINTING_MODE = "dynamic"
DEFAULT_BARGE_IN_INTERRUPTION_MODE = "vad"
DEFAULT_BARGE_IN_MIN_SPEECH_SECONDS = 0.20
DEFAULT_BARGE_IN_MIN_WORDS = 2
DEFAULT_BARGE_IN_FALSE_INTERRUPTION_TIMEOUT_SECONDS = 1.2
DEFAULT_BARGE_IN_RESUME_FALSE_INTERRUPTION = True
DEFAULT_BARGE_IN_MIN_ENDPOINTING_DELAY_SECONDS = 0.20
DEFAULT_BARGE_IN_MAX_ENDPOINTING_DELAY_SECONDS = 0.55
DEFAULT_BARGE_IN_MIN_CONSECUTIVE_SPEECH_DELAY_SECONDS = 0.10
DEFAULT_BARGE_IN_PREEMPTIVE_GENERATION = False
DEFAULT_BARGE_IN_USER_AWAY_TIMEOUT_SECONDS = 30.0
DEFAULT_BARGE_IN_CONFIRMATION_GRACE_SECONDS = 6.0
DEFAULT_BARGE_IN_IMMEDIATE_MUTE_ENABLED = True
DEFAULT_BARGE_IN_TELEMETRY_PATH: str | None = None
DEFAULT_BARGE_IN_SQLITE_PATH: str | None = None
DEFAULT_VOICE_METRICS_TELEMETRY_PATH: str | None = None
DEFAULT_VOICE_METRICS_SQLITE_PATH: str | None = None
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

_DEFAULT_AGENT_PROMPT_PATH = Path(__file__).resolve().parent.parent / DEFAULT_AGENT_INSTRUCTIONS_FILE
DEFAULT_AGENT_INSTRUCTIONS = (
    _DEFAULT_AGENT_PROMPT_PATH.read_text(encoding="utf-8").strip()
    if _DEFAULT_AGENT_PROMPT_PATH.exists()
    else DEFAULT_AGENT_INSTRUCTIONS_FALLBACK
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


def _clean_bool(value: str | None, default: bool) -> bool:
    cleaned = _clean(value)
    if cleaned is None:
        return default

    lowered = cleaned.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _clean_float(value: str | None, default: float) -> float:
    cleaned = _clean(value)
    if cleaned is None:
        return default

    try:
        parsed = float(cleaned)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _clean_bounded_float(value: str | None, default: float, *, minimum: float, maximum: float) -> float:
    parsed = _clean_float(value, default)
    if parsed < minimum or parsed > maximum:
        return default
    return parsed


def _clean_optional_float(value: str | None, default: float | None) -> float | None:
    cleaned = _clean(value)
    if cleaned is None:
        return default
    if cleaned.lower() in {"none", "off", "disabled"}:
        return None

    try:
        parsed = float(cleaned)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _clean_int(value: str | None, default: int) -> int:
    cleaned = _clean(value)
    if cleaned is None:
        return default

    try:
        parsed = int(cleaned)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _clean_optional_int(value: str | None, default: int | None) -> int | None:
    cleaned = _clean(value)
    if cleaned is None:
        return default
    if cleaned.lower() in {"none", "off", "disabled"}:
        return None

    try:
        parsed = int(cleaned)
    except ValueError:
        return default
    return parsed if parsed >= 0 else default


def _clean_optional_string(value: str | None, default: str | None) -> str | None:
    cleaned = _clean(value)
    if cleaned is None:
        return default
    if cleaned.lower() in {"none", "off", "disabled"}:
        return None
    return cleaned


def _read_prompt_file(value: str | None) -> str | None:
    cleaned = _clean_optional_string(value, None)
    if cleaned is None:
        return None

    path = Path(cleaned)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def _clean_choice(
    value: str | None,
    default: str,
    *,
    choices: frozenset[str],
) -> str:
    cleaned = _clean(value)
    if cleaned is None:
        return default
    lowered = cleaned.lower()
    return lowered if lowered in choices else default


def _clean_optional_choice(
    value: str | None,
    default: str | None,
    *,
    choices: frozenset[str],
) -> str | None:
    cleaned = _clean_optional_string(value, default)
    if cleaned is None:
        return default
    lowered = cleaned.lower()
    if lowered == "auto":
        return None
    return lowered if lowered in choices else default


@dataclass(frozen=True)
class AgentConfig:
    """Normalized environment configuration."""

    openai_api_key: str | None
    livekit_url: str | None
    livekit_api_key: str | None
    livekit_api_secret: str | None
    openai_model: str = DEFAULT_OPENAI_MODEL
    openai_max_completion_tokens: int | None = DEFAULT_OPENAI_MAX_COMPLETION_TOKENS
    openai_llm_temperature: float = DEFAULT_OPENAI_LLM_TEMPERATURE
    voice_pipeline_mode: str = DEFAULT_VOICE_PIPELINE_MODE
    openai_stt_model: str = DEFAULT_OPENAI_STT_MODEL
    openai_fast_stt_model: str = DEFAULT_OPENAI_FAST_STT_MODEL
    openai_fast_stt_realtime: bool = DEFAULT_OPENAI_FAST_STT_REALTIME
    openai_fast_stt_turn_silence_ms: int = DEFAULT_OPENAI_FAST_STT_TURN_SILENCE_MS
    openai_fast_stt_prefix_padding_ms: int = DEFAULT_OPENAI_FAST_STT_PREFIX_PADDING_MS
    openai_fast_stt_vad_threshold: float = DEFAULT_OPENAI_FAST_STT_VAD_THRESHOLD
    openai_stt_language: str = DEFAULT_OPENAI_STT_LANGUAGE
    openai_tts_model: str = DEFAULT_OPENAI_TTS_MODEL
    openai_tts_voice: str = DEFAULT_OPENAI_TTS_VOICE
    openai_tts_response_format: str = DEFAULT_OPENAI_TTS_RESPONSE_FORMAT
    openai_tts_speed: float = DEFAULT_OPENAI_TTS_SPEED
    openai_tts_instructions: str = DEFAULT_OPENAI_TTS_INSTRUCTIONS
    agent_instructions: str = DEFAULT_AGENT_INSTRUCTIONS
    barge_in_enabled: bool = DEFAULT_BARGE_IN_ENABLED
    barge_in_turn_detection_mode: str | None = DEFAULT_BARGE_IN_TURN_DETECTION_MODE
    barge_in_endpointing_mode: str = DEFAULT_BARGE_IN_ENDPOINTING_MODE
    barge_in_interruption_mode: str = DEFAULT_BARGE_IN_INTERRUPTION_MODE
    barge_in_min_speech_seconds: float = DEFAULT_BARGE_IN_MIN_SPEECH_SECONDS
    barge_in_min_words: int = DEFAULT_BARGE_IN_MIN_WORDS
    barge_in_false_interruption_timeout_seconds: float | None = (
        DEFAULT_BARGE_IN_FALSE_INTERRUPTION_TIMEOUT_SECONDS
    )
    barge_in_resume_false_interruption: bool = DEFAULT_BARGE_IN_RESUME_FALSE_INTERRUPTION
    barge_in_min_endpointing_delay_seconds: float = DEFAULT_BARGE_IN_MIN_ENDPOINTING_DELAY_SECONDS
    barge_in_max_endpointing_delay_seconds: float = DEFAULT_BARGE_IN_MAX_ENDPOINTING_DELAY_SECONDS
    barge_in_min_consecutive_speech_delay_seconds: float = (
        DEFAULT_BARGE_IN_MIN_CONSECUTIVE_SPEECH_DELAY_SECONDS
    )
    barge_in_preemptive_generation: bool = DEFAULT_BARGE_IN_PREEMPTIVE_GENERATION
    barge_in_user_away_timeout_seconds: float | None = DEFAULT_BARGE_IN_USER_AWAY_TIMEOUT_SECONDS
    barge_in_confirmation_grace_seconds: float = DEFAULT_BARGE_IN_CONFIRMATION_GRACE_SECONDS
    barge_in_immediate_mute_enabled: bool = DEFAULT_BARGE_IN_IMMEDIATE_MUTE_ENABLED
    barge_in_telemetry_path: str | None = DEFAULT_BARGE_IN_TELEMETRY_PATH
    barge_in_sqlite_path: str | None = DEFAULT_BARGE_IN_SQLITE_PATH
    voice_metrics_telemetry_path: str | None = DEFAULT_VOICE_METRICS_TELEMETRY_PATH
    voice_metrics_sqlite_path: str | None = DEFAULT_VOICE_METRICS_SQLITE_PATH

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        load_dotenv_file: bool = False,
    ) -> "AgentConfig":
        source = dict(environ) if environ is not None else cls._load_runtime_env(load_dotenv_file)

        openai_model = _clean(source.get("OPENAI_MODEL")) or DEFAULT_OPENAI_MODEL
        openai_max_completion_tokens = _clean_optional_int(
            source.get("OPENAI_MAX_COMPLETION_TOKENS"),
            DEFAULT_OPENAI_MAX_COMPLETION_TOKENS,
        )
        openai_llm_temperature = _clean_bounded_float(
            source.get("OPENAI_LLM_TEMPERATURE"),
            DEFAULT_OPENAI_LLM_TEMPERATURE,
            minimum=0.0,
            maximum=2.0,
        )
        voice_pipeline_mode = _clean_choice(
            source.get("VOICE_PIPELINE_MODE"),
            DEFAULT_VOICE_PIPELINE_MODE,
            choices=frozenset({"controlled_fast", "cascade_diarized"}),
        )
        openai_stt_model = _clean(source.get("OPENAI_STT_MODEL")) or DEFAULT_OPENAI_STT_MODEL
        openai_fast_stt_model = (
            _clean(source.get("OPENAI_FAST_STT_MODEL")) or DEFAULT_OPENAI_FAST_STT_MODEL
        )
        openai_fast_stt_realtime = _clean_bool(
            source.get("OPENAI_FAST_STT_REALTIME"),
            DEFAULT_OPENAI_FAST_STT_REALTIME,
        )
        openai_fast_stt_turn_silence_ms = _clean_int(
            source.get("OPENAI_FAST_STT_TURN_SILENCE_MS"),
            DEFAULT_OPENAI_FAST_STT_TURN_SILENCE_MS,
        )
        openai_fast_stt_prefix_padding_ms = _clean_int(
            source.get("OPENAI_FAST_STT_PREFIX_PADDING_MS"),
            DEFAULT_OPENAI_FAST_STT_PREFIX_PADDING_MS,
        )
        openai_fast_stt_vad_threshold = _clean_bounded_float(
            source.get("OPENAI_FAST_STT_VAD_THRESHOLD"),
            DEFAULT_OPENAI_FAST_STT_VAD_THRESHOLD,
            minimum=0.0,
            maximum=1.0,
        )
        openai_stt_language = (
            _clean(source.get("OPENAI_STT_LANGUAGE")) or DEFAULT_OPENAI_STT_LANGUAGE
        )
        openai_tts_model = _clean(source.get("OPENAI_TTS_MODEL")) or DEFAULT_OPENAI_TTS_MODEL
        openai_tts_voice = _clean(source.get("OPENAI_TTS_VOICE")) or DEFAULT_OPENAI_TTS_VOICE
        openai_tts_response_format = (
            _clean(source.get("OPENAI_TTS_RESPONSE_FORMAT")) or DEFAULT_OPENAI_TTS_RESPONSE_FORMAT
        )
        openai_tts_speed = _clean_bounded_float(
            source.get("OPENAI_TTS_SPEED"),
            DEFAULT_OPENAI_TTS_SPEED,
            minimum=0.25,
            maximum=4.0,
        )
        openai_tts_instructions = (
            _clean(source.get("OPENAI_TTS_INSTRUCTIONS")) or DEFAULT_OPENAI_TTS_INSTRUCTIONS
        )
        instructions = (
            _clean(source.get("AGENT_INSTRUCTIONS"))
            or _read_prompt_file(source.get("AGENT_INSTRUCTIONS_FILE"))
            or DEFAULT_AGENT_INSTRUCTIONS
        )
        min_endpointing_delay = _clean_float(
            source.get("BARGE_IN_MIN_ENDPOINTING_DELAY_SECONDS"),
            DEFAULT_BARGE_IN_MIN_ENDPOINTING_DELAY_SECONDS,
        )
        max_endpointing_delay = _clean_float(
            source.get("BARGE_IN_MAX_ENDPOINTING_DELAY_SECONDS"),
            DEFAULT_BARGE_IN_MAX_ENDPOINTING_DELAY_SECONDS,
        )
        if max_endpointing_delay < min_endpointing_delay:
            max_endpointing_delay = min_endpointing_delay

        return cls(
            openai_api_key=_clean(source.get("OPENAI_API_KEY")),
            livekit_url=_clean(source.get("LIVEKIT_URL")),
            livekit_api_key=_clean(source.get("LIVEKIT_API_KEY")),
            livekit_api_secret=_clean(source.get("LIVEKIT_API_SECRET")),
            openai_model=openai_model,
            openai_max_completion_tokens=openai_max_completion_tokens,
            openai_llm_temperature=openai_llm_temperature,
            voice_pipeline_mode=voice_pipeline_mode,
            openai_stt_model=openai_stt_model,
            openai_fast_stt_model=openai_fast_stt_model,
            openai_fast_stt_realtime=openai_fast_stt_realtime,
            openai_fast_stt_turn_silence_ms=openai_fast_stt_turn_silence_ms,
            openai_fast_stt_prefix_padding_ms=openai_fast_stt_prefix_padding_ms,
            openai_fast_stt_vad_threshold=openai_fast_stt_vad_threshold,
            openai_stt_language=openai_stt_language,
            openai_tts_model=openai_tts_model,
            openai_tts_voice=openai_tts_voice,
            openai_tts_response_format=openai_tts_response_format,
            openai_tts_speed=openai_tts_speed,
            openai_tts_instructions=openai_tts_instructions,
            agent_instructions=instructions,
            barge_in_enabled=_clean_bool(
                source.get("BARGE_IN_ENABLED"),
                DEFAULT_BARGE_IN_ENABLED,
            ),
            barge_in_turn_detection_mode=_clean_optional_choice(
                source.get("BARGE_IN_TURN_DETECTION_MODE"),
                DEFAULT_BARGE_IN_TURN_DETECTION_MODE,
                choices=frozenset({"stt", "vad", "realtime_llm", "manual"}),
            ),
            barge_in_endpointing_mode=_clean_choice(
                source.get("BARGE_IN_ENDPOINTING_MODE"),
                DEFAULT_BARGE_IN_ENDPOINTING_MODE,
                choices=frozenset({"dynamic", "fixed"}),
            ),
            barge_in_interruption_mode=_clean_choice(
                source.get("BARGE_IN_INTERRUPTION_MODE"),
                DEFAULT_BARGE_IN_INTERRUPTION_MODE,
                choices=frozenset({"adaptive", "vad"}),
            ),
            barge_in_min_speech_seconds=_clean_float(
                source.get("BARGE_IN_MIN_SPEECH_SECONDS"),
                DEFAULT_BARGE_IN_MIN_SPEECH_SECONDS,
            ),
            barge_in_min_words=_clean_int(
                source.get("BARGE_IN_MIN_WORDS"),
                DEFAULT_BARGE_IN_MIN_WORDS,
            ),
            barge_in_false_interruption_timeout_seconds=_clean_optional_float(
                source.get("BARGE_IN_FALSE_INTERRUPTION_TIMEOUT_SECONDS"),
                DEFAULT_BARGE_IN_FALSE_INTERRUPTION_TIMEOUT_SECONDS,
            ),
            barge_in_resume_false_interruption=_clean_bool(
                source.get("BARGE_IN_RESUME_FALSE_INTERRUPTION"),
                DEFAULT_BARGE_IN_RESUME_FALSE_INTERRUPTION,
            ),
            barge_in_min_endpointing_delay_seconds=min_endpointing_delay,
            barge_in_max_endpointing_delay_seconds=max_endpointing_delay,
            barge_in_min_consecutive_speech_delay_seconds=_clean_float(
                source.get("BARGE_IN_MIN_CONSECUTIVE_SPEECH_DELAY_SECONDS"),
                DEFAULT_BARGE_IN_MIN_CONSECUTIVE_SPEECH_DELAY_SECONDS,
            ),
            barge_in_preemptive_generation=_clean_bool(
                source.get("BARGE_IN_PREEMPTIVE_GENERATION"),
                DEFAULT_BARGE_IN_PREEMPTIVE_GENERATION,
            ),
            barge_in_user_away_timeout_seconds=_clean_optional_float(
                source.get("BARGE_IN_USER_AWAY_TIMEOUT_SECONDS"),
                DEFAULT_BARGE_IN_USER_AWAY_TIMEOUT_SECONDS,
            ),
            barge_in_confirmation_grace_seconds=_clean_float(
                source.get("BARGE_IN_CONFIRMATION_GRACE_SECONDS"),
                DEFAULT_BARGE_IN_CONFIRMATION_GRACE_SECONDS,
            ),
            barge_in_immediate_mute_enabled=_clean_bool(
                source.get("BARGE_IN_IMMEDIATE_MUTE_ENABLED"),
                DEFAULT_BARGE_IN_IMMEDIATE_MUTE_ENABLED,
            ),
            barge_in_telemetry_path=_clean_optional_string(
                source.get("BARGE_IN_TELEMETRY_PATH"),
                DEFAULT_BARGE_IN_TELEMETRY_PATH,
            ),
            barge_in_sqlite_path=_clean_optional_string(
                source.get("BARGE_IN_SQLITE_PATH"),
                DEFAULT_BARGE_IN_SQLITE_PATH,
            ),
            voice_metrics_telemetry_path=_clean_optional_string(
                source.get("VOICE_METRICS_TELEMETRY_PATH"),
                DEFAULT_VOICE_METRICS_TELEMETRY_PATH,
            ),
            voice_metrics_sqlite_path=_clean_optional_string(
                source.get("VOICE_METRICS_SQLITE_PATH"),
                DEFAULT_VOICE_METRICS_SQLITE_PATH,
            ),
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
