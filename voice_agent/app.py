"""CLI entrypoint for the voice agent."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence

from livekit.agents import AgentSession, JobContext, WorkerOptions, cli

from .agent import AssistantAgent
from .config import AgentConfig, ConfigError, SUPPORTED_COMMANDS
from .metrics import log_metrics_event
from .transcript import ConversationTraceLogger
from .web import TranscriptWebServer


def build_web_metadata(config: AgentConfig) -> tuple[list[dict[str, str]], list[str]]:
    models = [
        {"label": "LLM", "value": config.openai_model},
        {"label": "STT", "value": config.openai_stt_model},
        {"label": "TTS", "value": config.openai_tts_model},
        {"label": "Voice", "value": config.openai_tts_voice},
        {"label": "VAD", "value": "silero"},
    ]
    technologies = [
        "OpenAI",
        "LiveKit Agents",
        "Silero VAD",
        "Local Transcript Web UI",
        "Python 3.11",
    ]
    return models, technologies


def resolve_cli_command(argv: Sequence[str]) -> str | None:
    for arg in argv:
        if arg.startswith("-"):
            continue
        return arg if arg in SUPPORTED_COMMANDS else None
    return None


def should_skip_validation(argv: Sequence[str]) -> bool:
    if not argv:
        return True

    if any(arg in {"-h", "--help"} for arg in argv):
        return True

    command = resolve_cli_command(argv)
    if command is None:
        return True

    return command == "console" and "--list-devices" in argv


def validate_startup(
    argv: Sequence[str],
    *,
    environ: Mapping[str, str] | None = None,
) -> AgentConfig:
    config = AgentConfig.from_env(environ, load_dotenv_file=environ is None)
    if should_skip_validation(argv):
        return config

    command = resolve_cli_command(argv)
    if command is not None:
        config.validate_for_command(command)
    return config


def build_worker_options(
    config: AgentConfig | None = None,
    *,
    command: str | None = None,
) -> WorkerOptions:
    runtime_config = config or AgentConfig.from_env(load_dotenv_file=True)
    ws_url = runtime_config.livekit_url
    api_key = runtime_config.livekit_api_key
    api_secret = runtime_config.livekit_api_secret

    # Current LiveKit console mode still requires worker connection fields even
    # though the job runs as a local fake job and does not join a real room.
    if command == "console":
        ws_url = ws_url or "ws://127.0.0.1"
        api_key = api_key or "console-key"
        api_secret = api_secret or "console-secret"

    return WorkerOptions(
        entrypoint_fnc=entrypoint,
        agent_name="voice-agent",
        ws_url=ws_url,
        api_key=api_key,
        api_secret=api_secret,
    )


async def entrypoint(ctx: JobContext) -> None:
    config = AgentConfig.from_env(load_dotenv_file=True)
    web_server = TranscriptWebServer() if ctx.is_fake_job() else None
    session = AgentSession()
    trace_logger = ConversationTraceLogger(store=web_server.store if web_server else None)

    session.on("metrics_collected", log_metrics_event)
    session.on("agent_state_changed", trace_logger.on_agent_state_changed)
    session.on("user_state_changed", trace_logger.on_user_state_changed)
    session.on("user_input_transcribed", trace_logger.on_user_input_transcribed)
    session.on("conversation_item_added", trace_logger.on_conversation_item_added)

    if ctx.is_fake_job():
        models, technologies = build_web_metadata(config)
        web_server.store.set_models(models)
        web_server.store.set_hero_card(title="", items=["Javier Castro", "DNAI", "2026"])
        web_server.store.set_technologies(technologies)
        session.output.transcription = trace_logger.build_agent_text_output()
        web_server.start()
        session.on("close", lambda _event: web_server.close())
        print(f"\nTranscript Web UI: {web_server.url}\n")

    agent = AssistantAgent(config, on_user_diarized=trace_logger.on_user_diarized)

    # Console mode runs as a fake job and can use the built-in local audio path.
    if ctx.is_fake_job():
        await session.start(agent=agent)
        return

    await ctx.connect()
    await session.start(agent=agent, room=ctx.room)


def main(
    argv: Sequence[str] | None = None,
    *,
    runner=cli.run_app,
) -> None:
    runtime_argv = list(sys.argv[1:] if argv is None else argv)

    try:
        config = validate_startup(runtime_argv)
    except ConfigError as exc:
        raise SystemExit(str(exc)) from None

    options = build_worker_options(config, command=resolve_cli_command(runtime_argv))

    if argv is None or runtime_argv == sys.argv[1:]:
        runner(options)
        return

    original_argv = sys.argv[:]
    sys.argv = [sys.argv[0], *runtime_argv]
    try:
        runner(options)
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    main()
