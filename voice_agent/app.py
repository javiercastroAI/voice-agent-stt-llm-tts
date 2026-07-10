"""CLI entrypoint for the voice agent."""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
import webbrowser
from collections.abc import Callable, Mapping, Sequence

from livekit.agents import AgentSession, JobContext, WorkerOptions, cli

from .agent import AssistantAgent
from .barge_in import BargeInController, BargeInPolicy
from .case_context import load_case_context
from .config import AgentConfig, ConfigError, SUPPORTED_COMMANDS
from .metrics import VoiceTelemetryRecorder, log_metrics_event, sync_metric_panel
from .fsm_trace import FSMTraceRecorder
from .transcript import ConversationTraceLogger
from .web import TranscriptWebServer

FINAL_DASHBOARD_SYNC_SECONDS = 0.75


def request_console_process_exit() -> None:
    """Enter LiveKit's graceful exit path with a bounded process fallback."""

    # LiveKit's console signal handler can block while joining a worker that has
    # already shut down. Arm the fallback first because raise_signal may never
    # return to this frame. At this point AgentSession and the dashboard server
    # have already closed, so a forced process exit cannot truncate the call.
    force_exit = threading.Timer(2.0, os._exit, args=(0,))
    force_exit.daemon = True
    force_exit.start()

    signal.raise_signal(signal.SIGINT)


def open_console_dashboard(url: str) -> bool:
    """Open the live console dashboard in the user's default browser."""

    try:
        return bool(webbrowser.open(url, new=2, autoraise=True))
    except Exception:
        return False


def close_console_session(
    *,
    web_server: TranscriptWebServer,
    console_exit: Callable[[], None],
    finalize_transcript: Callable[[], None],
    wait: Callable[[float], None] | None = None,
) -> None:
    """Expose the final verdict for one browser poll before process exit."""

    finalize_transcript()
    (wait or time.sleep)(FINAL_DASHBOARD_SYNC_SECONDS)
    web_server.close()
    console_exit()


def build_web_metadata(config: AgentConfig) -> tuple[list[dict[str, str]], list[str]]:
    models = [
        {"label": "Pipeline", "value": config.voice_pipeline_mode},
        {"label": "LLM", "value": config.openai_model},
        {
            "label": "LLM Max Tokens",
            "value": str(config.openai_max_completion_tokens or "unlimited"),
        },
        {"label": "LLM Temperature", "value": f"{config.openai_llm_temperature:.2f}"},
        {
            "label": "Runtime STT",
            "value": (
                config.openai_fast_stt_model
                if config.voice_pipeline_mode == "controlled_fast"
                else config.openai_stt_model
            ),
        },
        {
            "label": "Runtime STT Realtime",
            "value": "enabled" if config.openai_fast_stt_realtime else "disabled",
        },
        {"label": "Analytics STT", "value": config.openai_stt_model},
        {"label": "STT Language", "value": config.openai_stt_language},
        {"label": "TTS", "value": config.openai_tts_model},
        {"label": "Voice", "value": config.openai_tts_voice},
        {
            "label": "TTS Format/Speed",
            "value": f"{config.openai_tts_response_format}/{config.openai_tts_speed:.2f}x",
        },
        {"label": "VAD", "value": "silero"},
        {"label": "Barge-in", "value": "enabled" if config.barge_in_enabled else "disabled"},
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
    adherence_case = (
        load_case_context(config.case_context_file)
        if ctx.is_fake_job() and config.fsm_enabled
        else None
    )
    web_server = (
        TranscriptWebServer(adherence_case=adherence_case)
        if ctx.is_fake_job()
        else None
    )
    barge_in_policy = BargeInPolicy.from_config(config)
    session = AgentSession(**barge_in_policy.session_options())
    voice_telemetry = VoiceTelemetryRecorder(
        jsonl_path=config.voice_metrics_telemetry_path,
        sqlite_path=config.voice_metrics_sqlite_path,
    )
    fsm_event_writer = web_server.store.add_fsm_event if web_server else None
    fsm_trace_recorder = (
        FSMTraceRecorder(
            jsonl_path=config.fsm_trace_path,
            event_writer=fsm_event_writer,
        )
        if config.fsm_trace_path or fsm_event_writer is not None
        else None
    )
    trace_logger = ConversationTraceLogger(
        store=web_server.store if web_server else None,
        on_agent_text_finalized=(
            fsm_trace_recorder.record_streamed_terminal_response
            if fsm_trace_recorder is not None
            else None
        ),
    )

    def request_immediate_agent_mute(_created_at: float) -> tuple[bool, str | None]:
        try:
            interruption = session.interrupt(force=True)
        except Exception as exc:
            return False, f"{exc.__class__.__name__}: {exc}"

        def drain_interruption_result(future) -> None:
            try:
                future.result()
            except Exception:
                return

        interruption.add_done_callback(drain_interruption_result)
        return True, "session.interrupt(force=True)"

    barge_in_controller = BargeInController(
        barge_in_policy,
        store=web_server.store if web_server else None,
        on_immediate_mute=request_immediate_agent_mute,
    )

    def handle_metrics_collected(event) -> None:
        log_metrics_event(event)
        voice_telemetry.record_metric(event.metrics)
        if web_server is not None:
            sync_metric_panel(event.metrics, store=web_server.store)

    session.on("metrics_collected", handle_metrics_collected)

    agent: AssistantAgent | None = None

    def handle_agent_state_changed(event) -> None:
        trace_logger.on_agent_state_changed(event)
        barge_in_controller.on_agent_state_changed(event)
        if agent is not None and agent.consume_terminal_shutdown(
            old_state=event.old_state,
            new_state=event.new_state,
        ):
            session.shutdown(drain=True)

    def handle_user_state_changed(event) -> None:
        trace_logger.on_user_state_changed(event)
        barge_in_controller.on_user_state_changed(event)

    def handle_user_input_transcribed(event) -> None:
        trace_logger.on_user_input_transcribed(event)
        voice_telemetry.record_user_transcript(event)
        barge_in_controller.on_user_input_transcribed(event)

    session.on("agent_state_changed", handle_agent_state_changed)
    session.on("user_state_changed", handle_user_state_changed)
    session.on("user_input_transcribed", handle_user_input_transcribed)
    session.on("agent_false_interruption", barge_in_controller.on_agent_false_interruption)
    def handle_conversation_item_added(event) -> None:
        trace_logger.on_conversation_item_added(event)
        if fsm_trace_recorder is not None:
            fsm_trace_recorder.record_conversation_item(event)

    session.on("conversation_item_added", handle_conversation_item_added)

    if ctx.is_fake_job():
        models, technologies = build_web_metadata(config)
        web_server.store.set_models(models)
        web_server.store.set_hero_card(title="", items=["Javier Castro", "DNAI", "2026"])
        web_server.store.set_technologies(technologies)
        session.output.transcription = trace_logger.build_agent_text_output()
        web_server.start()
        open_console_dashboard(web_server.url)
        console_exit = request_console_process_exit

        def handle_console_session_close(_event) -> None:
            close_console_session(
                web_server=web_server,
                console_exit=console_exit,
                finalize_transcript=trace_logger.on_agent_text_flush,
            )

        session.on("close", handle_console_session_close)
        print(f"\nTranscript Web UI: {web_server.url}\n")

    agent = AssistantAgent(
        config,
        on_user_diarized=trace_logger.on_user_diarized,
        fsm_trace_recorder=fsm_trace_recorder,
        delete_room_on_hangup=not ctx.is_fake_job(),
    )

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
