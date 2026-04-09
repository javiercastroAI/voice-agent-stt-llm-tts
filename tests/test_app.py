from __future__ import annotations

import importlib
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from voice_agent.app import (
    build_web_metadata,
    build_worker_options,
    entrypoint,
    main,
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
                "OPENAI_MODEL": "gpt-4o",
                "OPENAI_STT_MODEL": "gpt-4o-transcribe-diarize",
                "OPENAI_TTS_MODEL": "gpt-4o-mini-tts",
                "OPENAI_TTS_VOICE": "marin",
            }
        )

        models, technologies = build_web_metadata(config)

        self.assertEqual(models[0], {"label": "LLM", "value": "gpt-4o"})
        self.assertEqual(models[3], {"label": "Voice", "value": "marin"})
        self.assertIn("OpenAI", technologies)
        self.assertIn("LiveKit Agents", technologies)


class EntrypointTests(unittest.IsolatedAsyncioTestCase):
    async def test_console_web_server_stays_up_until_session_close(self) -> None:
        fake_config = AgentConfig.from_env({"OPENAI_API_KEY": "openai-key"})
        fake_store = SimpleNamespace(
            set_models=Mock(),
            set_hero_card=Mock(),
            set_technologies=Mock(),
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

            def on(self, event: str, callback) -> None:
                self.handlers.setdefault(event, []).append(callback)

            async def start(self, *, agent, room=None) -> None:
                return None

        fake_session = FakeSession()
        fake_ctx = SimpleNamespace(is_fake_job=lambda: True)

        with (
            patch("voice_agent.app.AgentConfig.from_env", return_value=fake_config),
            patch("voice_agent.app.TranscriptWebServer", return_value=fake_web_server),
            patch("voice_agent.app.AgentSession", return_value=fake_session),
            patch("voice_agent.app.AssistantAgent", return_value=object()),
        ):
            await entrypoint(fake_ctx)

        fake_web_server.start.assert_called_once_with()
        fake_web_server.close.assert_not_called()
        fake_store.set_models.assert_called_once()
        fake_store.set_hero_card.assert_called_once_with(
            title="",
            items=["Javier Castro", "DNAI", "2026"],
        )
        fake_store.set_technologies.assert_called_once()
        self.assertIsNotNone(fake_session.output.transcription)
        self.assertIn("close", fake_session.handlers)

        close_handler = fake_session.handlers["close"][0]
        close_handler(None)
        fake_web_server.close.assert_called_once_with()
