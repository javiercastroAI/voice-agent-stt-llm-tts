from __future__ import annotations

import unittest

from voice_agent.config import AgentConfig, ConfigError, DEFAULT_AGENT_INSTRUCTIONS


class AgentConfigTests(unittest.TestCase):
    def test_from_env_applies_defaults_and_strips_values(self) -> None:
        config = AgentConfig.from_env(
            {
                "OPENAI_API_KEY": " openai-key ",
                "OPENAI_MODEL": " gpt-4o-mini ",
                "OPENAI_STT_MODEL": " gpt-4o-mini-transcribe ",
                "OPENAI_TTS_MODEL": " gpt-4o-mini-tts ",
                "OPENAI_TTS_VOICE": " alloy ",
                "AGENT_INSTRUCTIONS": " custom instructions ",
            }
        )

        self.assertEqual(config.openai_api_key, "openai-key")
        self.assertEqual(config.openai_model, "gpt-4o-mini")
        self.assertEqual(config.openai_stt_model, "gpt-4o-mini-transcribe")
        self.assertEqual(config.openai_tts_model, "gpt-4o-mini-tts")
        self.assertEqual(config.openai_tts_voice, "alloy")
        self.assertEqual(config.agent_instructions, "custom instructions")

    def test_from_env_uses_instruction_default(self) -> None:
        config = AgentConfig.from_env({})
        self.assertEqual(config.agent_instructions, DEFAULT_AGENT_INSTRUCTIONS)
        self.assertEqual(config.openai_stt_model, "gpt-4o-transcribe-diarize")

    def test_validate_console_requires_provider_keys(self) -> None:
        config = AgentConfig.from_env({})

        with self.assertRaises(ConfigError) as ctx:
            config.validate_for_command("console")

        self.assertEqual(
            str(ctx.exception),
            "Missing required environment variables for `console`: OPENAI_API_KEY",
        )

    def test_validate_dev_requires_livekit_credentials(self) -> None:
        config = AgentConfig.from_env(
            {
                "OPENAI_API_KEY": "openai-key",
            }
        )

        with self.assertRaises(ConfigError) as ctx:
            config.validate_for_command("dev")

        self.assertEqual(
            str(ctx.exception),
            "Missing required environment variables for `dev`: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET",
        )

    def test_validate_start_accepts_complete_configuration(self) -> None:
        config = AgentConfig.from_env(
            {
                "OPENAI_API_KEY": "openai-key",
                "LIVEKIT_URL": "wss://example.livekit.cloud",
                "LIVEKIT_API_KEY": "livekit-key",
                "LIVEKIT_API_SECRET": "livekit-secret",
            }
        )

        config.validate_for_command("start")

    def test_placeholder_values_are_treated_as_missing(self) -> None:
        config = AgentConfig.from_env(
            {
                "OPENAI_API_KEY": "your-openai-api-key",
            }
        )

        self.assertIsNone(config.openai_api_key)
