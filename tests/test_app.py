from __future__ import annotations

import importlib
import os
import signal
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from voice_agent.app import (
    build_web_metadata,
    build_worker_options,
    close_console_session,
    entrypoint,
    FINAL_DASHBOARD_SYNC_SECONDS,
    main,
    open_console_dashboard,
    request_console_process_exit,
    resolve_cli_command,
    should_skip_validation,
    validate_startup,
)
from voice_agent.config import AgentConfig


class AppTests(unittest.TestCase):
    def test_module_import_smoke(self) -> None:
        module = importlib.import_module("voice_agent.app")
        self.assertTrue(hasattr(module, "main"))

    def test_resolve_cli_command(self) -> None:
        self.assertEqual(resolve_cli_command(["console"]), "console")
        self.assertEqual(resolve_cli_command(["--help"]), None)
        self.assertEqual(resolve_cli_command(["dev", "--log-level", "debug"]), "dev")

    def test_should_skip_validation_for_help_and_device_listing(self) -> None:
        self.assertTrue(should_skip_validation(["--help"]))
        self.assertTrue(should_skip_validation(["console", "--list-devices"]))
        self.assertFalse(should_skip_validation(["start"]))

    def test_validate_startup_allows_console_with_provider_keys_only(self) -> None:
        config = validate_startup(
            ["console"],
            environ={
                "OPENAI_API_KEY": "openai-key",
            },
        )

        self.assertEqual(config.openai_api_key, "openai-key")
        self.assertEqual(config.openai_stt_model, "gpt-4o-transcribe-diarize")

    def test_build_worker_options_uses_runtime_config(self) -> None:
        config = AgentConfig.from_env(
            {
                "OPENAI_API_KEY": "openai-key",
                "LIVEKIT_URL": "wss://example.livekit.cloud",
                "LIVEKIT_API_KEY": "livekit-key",
                "LIVEKIT_API_SECRET": "livekit-secret",
            }
        )

        options = build_worker_options(config)

        self.assertIs(options.entrypoint_fnc, entrypoint)
        self.assertEqual(options.ws_url, "wss://example.livekit.cloud")
        self.assertEqual(options.api_key, "livekit-key")
        self.assertEqual(options.api_secret, "livekit-secret")

    def test_dashboard_browser_failure_is_non_fatal(self) -> None:
        with patch("voice_agent.app.webbrowser.open", side_effect=RuntimeError("no browser")):
            self.assertFalse(open_console_dashboard("http://127.0.0.1:8765/"))

    def test_console_process_exit_has_bounded_fallback(self) -> None:
        timer = Mock()
        with (
            patch("voice_agent.app.threading.Timer", return_value=timer) as timer_factory,
            patch(
                "voice_agent.app.signal.raise_signal",
                side_effect=RuntimeError("signal dispatched"),
            ) as raise_signal,
        ):
            with self.assertRaisesRegex(RuntimeError, "signal dispatched"):
                request_console_process_exit()

        timer_factory.assert_called_once_with(2.0, os._exit, args=(0,))
        self.assertTrue(timer.daemon)
        timer.start.assert_called_once_with()
        raise_signal.assert_called_once_with(signal.SIGINT)

    def test_console_close_waits_one_poll_before_server_and_process_exit(self) -> None:
        calls: list[str] = []
        finalize_transcript = Mock(side_effect=lambda: calls.append("flush"))
        wait = Mock(side_effect=lambda _seconds: calls.append("wait"))
        web_server = SimpleNamespace(close=Mock(side_effect=lambda: calls.append("close")))
        console_exit = Mock(side_effect=lambda: calls.append("exit"))

        close_console_session(
            web_server=web_server,
            console_exit=console_exit,
            finalize_transcript=finalize_transcript,
            wait=wait,
        )

        finalize_transcript.assert_called_once_with()
        wait.assert_called_once_with(FINAL_DASHBOARD_SYNC_SECONDS)
        self.assertGreater(FINAL_DASHBOARD_SYNC_SECONDS, 0.35)
        self.assertEqual(calls, ["flush", "wait", "close", "exit"])

    def test_build_worker_options_uses_console_defaults_without_livekit_credentials(self) -> None:
        config = AgentConfig.from_env(
            {
                "OPENAI_API_KEY": "openai-key",
            }
        )

        options = build_worker_options(config, command="console")

        self.assertEqual(options.ws_url, "ws://127.0.0.1")
        self.assertEqual(options.api_key, "console-key")
        self.assertEqual(options.api_secret, "console-secret")

    def test_main_validates_and_calls_runner(self) -> None:
        calls = []

        def runner(options) -> None:
            calls.append(options)

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "openai-key",
            },
            clear=True,
        ):
            main(
                argv=["console"],
                runner=runner,
            )

        self.assertEqual(len(calls), 1)

    def test_main_exits_cleanly_on_missing_environment(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit) as ctx:
                main(argv=["dev"], runner=lambda _: None)

        self.assertIn("Missing required environment variables for `dev`", str(ctx.exception))

    def test_build_web_metadata_uses_runtime_configuration(self) -> None:
        config = AgentConfig.from_env(
            {
                "OPENAI_API_KEY": "openai-key",
                "OPENAI_MODEL": "gpt-4o-mini",
                "OPENAI_STT_MODEL": "gpt-4o-transcribe-diarize",
                "OPENAI_TTS_MODEL": "gpt-4o-mini-tts",
                "OPENAI_TTS_VOICE": "marin",
            }
        )

        models, technologies = build_web_metadata(config)

        self.assertEqual(models[0], {"label": "Pipeline", "value": "controlled_fast"})
        self.assertEqual(models[1], {"label": "LLM", "value": "gpt-4o-mini"})
        self.assertEqual(models[2], {"label": "LLM Max Tokens", "value": "60"})
        self.assertEqual(models[3], {"label": "LLM Temperature", "value": "0.20"})
        self.assertEqual(models[4], {"label": "Runtime STT", "value": "gpt-4o-mini-transcribe"})
        self.assertEqual(models[5], {"label": "Runtime STT Realtime", "value": "enabled"})
        self.assertEqual(models[7], {"label": "STT Language", "value": "es"})
        self.assertEqual(models[9], {"label": "Voice", "value": "marin"})
        self.assertEqual(models[10], {"label": "TTS Format/Speed", "value": "pcm/1.05x"})
        self.assertIn("OpenAI", technologies)
        self.assertIn("LiveKit Agents", technologies)


class EntrypointTests(unittest.IsolatedAsyncioTestCase):
    async def test_console_web_server_stays_up_until_session_close(self) -> None:
        fake_config = AgentConfig.from_env({"OPENAI_API_KEY": "openai-key"})
        fake_store = SimpleNamespace(
            set_models=Mock(),
            set_hero_card=Mock(),
            set_technologies=Mock(),
            set_agent_state=Mock(),
            set_barge_in_state=Mock(),
            add_barge_in_event=Mock(),
            add_fsm_event=Mock(),
            set_metric_panel=Mock(),
        )
        fake_web_server = SimpleNamespace(
            store=fake_store,
            url="http://127.0.0.1:8765/",
            start=Mock(),
            close=Mock(),
        )

        class FakeSession:
            def __init__(self) -> None:
                self.output = SimpleNamespace(transcription=None)
                self.handlers: dict[str, list[object]] = {}
                self.shutdown = Mock()

            def on(self, event: str, callback) -> None:
                self.handlers.setdefault(event, []).append(callback)

            async def start(self, *, agent, room=None) -> None:
                return None

        fake_session = FakeSession()
        fake_ctx = SimpleNamespace(is_fake_job=lambda: True)
        fake_agent = SimpleNamespace(
            consume_terminal_shutdown=Mock(return_value=True),
        )

        with (
            patch("voice_agent.app.AgentConfig.from_env", return_value=fake_config),
            patch("voice_agent.app.TranscriptWebServer", return_value=fake_web_server),
            patch("voice_agent.app.AgentSession", return_value=fake_session) as session_factory,
            patch("voice_agent.app.AssistantAgent", return_value=fake_agent) as agent_factory,
            patch("voice_agent.app.request_console_process_exit") as console_exit,
            patch("voice_agent.app.open_console_dashboard") as open_dashboard,
        ):
            await entrypoint(fake_ctx)

        session_factory.assert_called_once_with(
            turn_handling={
                "endpointing": {
                    "mode": "dynamic",
                    "min_delay": 0.20,
                    "max_delay": 0.55,
                },
                "interruption": {
                    "enabled": True,
                    "mode": "vad",
                    "discard_audio_if_uninterruptible": True,
                    "min_duration": 0.20,
                    "min_words": 2,
                    "false_interruption_timeout": 1.2,
                    "resume_false_interruption": True,
                },
            },
            min_consecutive_speech_delay=0.10,
            preemptive_generation=False,
            user_away_timeout=30.0,
        )
        self.assertFalse(agent_factory.call_args.kwargs["delete_room_on_hangup"])
        fake_web_server.start.assert_called_once_with()
        open_dashboard.assert_called_once_with(fake_web_server.url)
        fake_web_server.close.assert_not_called()
        fake_store.set_models.assert_called_once()
        fake_store.set_hero_card.assert_called_once_with(
            title="",
            items=["Javier Castro", "DNAI", "2026"],
        )
        fake_store.set_technologies.assert_called_once()
        self.assertIsNotNone(fake_session.output.transcription)
        self.assertIn("close", fake_session.handlers)
        self.assertIn("agent_false_interruption", fake_session.handlers)

        agent_state_handler = fake_session.handlers["agent_state_changed"][0]
        agent_state_handler(
            SimpleNamespace(old_state="speaking", new_state="listening", created_at=1.0)
        )
        fake_agent.consume_terminal_shutdown.assert_called_once_with(
            old_state="speaking",
            new_state="listening",
        )
        fake_session.shutdown.assert_called_once_with(drain=True)

        close_handler = fake_session.handlers["close"][0]
        with patch("voice_agent.app.time.sleep") as dashboard_wait:
            close_handler(None)
        dashboard_wait.assert_called_once_with(FINAL_DASHBOARD_SYNC_SECONDS)
        fake_web_server.close.assert_called_once_with()
        console_exit.assert_called_once_with()
