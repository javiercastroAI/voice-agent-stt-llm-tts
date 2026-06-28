from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from voice_agent.config import AgentConfig, ConfigError, DEFAULT_AGENT_INSTRUCTIONS


class AgentConfigTests(unittest.TestCase):
    def test_from_env_applies_defaults_and_strips_values(self) -> None:
        config = AgentConfig.from_env(
            {
                "OPENAI_API_KEY": " openai-key ",
                "OPENAI_MODEL": " gpt-4o-mini ",
                "OPENAI_MAX_COMPLETION_TOKENS": " 40 ",
                "OPENAI_LLM_TEMPERATURE": " 0.1 ",
                "VOICE_PIPELINE_MODE": " controlled_fast ",
                "OPENAI_STT_MODEL": " gpt-4o-mini-transcribe ",
                "OPENAI_FAST_STT_MODEL": " gpt-4o-mini-transcribe ",
                "OPENAI_FAST_STT_REALTIME": " true ",
                "OPENAI_FAST_STT_TURN_SILENCE_MS": " 200 ",
                "OPENAI_FAST_STT_PREFIX_PADDING_MS": " 250 ",
                "OPENAI_FAST_STT_VAD_THRESHOLD": " 0.45 ",
                "OPENAI_STT_LANGUAGE": " es ",
                "OPENAI_TTS_MODEL": " gpt-4o-mini-tts ",
                "OPENAI_TTS_VOICE": " alloy ",
                "OPENAI_TTS_RESPONSE_FORMAT": " pcm ",
                "OPENAI_TTS_SPEED": " 1.1 ",
                "OPENAI_TTS_INSTRUCTIONS": " speak in Spain Spanish ",
                "AGENT_INSTRUCTIONS": " custom instructions ",
            }
        )

        self.assertEqual(config.openai_api_key, "openai-key")
        self.assertEqual(config.openai_model, "gpt-4o-mini")
        self.assertEqual(config.openai_max_completion_tokens, 40)
        self.assertEqual(config.openai_llm_temperature, 0.1)
        self.assertEqual(config.voice_pipeline_mode, "controlled_fast")
        self.assertEqual(config.openai_stt_model, "gpt-4o-mini-transcribe")
        self.assertEqual(config.openai_fast_stt_model, "gpt-4o-mini-transcribe")
        self.assertTrue(config.openai_fast_stt_realtime)
        self.assertEqual(config.openai_fast_stt_turn_silence_ms, 200)
        self.assertEqual(config.openai_fast_stt_prefix_padding_ms, 250)
        self.assertEqual(config.openai_fast_stt_vad_threshold, 0.45)
        self.assertEqual(config.openai_stt_language, "es")
        self.assertEqual(config.openai_tts_model, "gpt-4o-mini-tts")
        self.assertEqual(config.openai_tts_voice, "alloy")
        self.assertEqual(config.openai_tts_response_format, "pcm")
        self.assertEqual(config.openai_tts_speed, 1.1)
        self.assertEqual(config.openai_tts_instructions, "speak in Spain Spanish")
        self.assertEqual(config.agent_instructions, "custom instructions")

    def test_from_env_uses_instruction_default(self) -> None:
        config = AgentConfig.from_env({})
        self.assertEqual(config.agent_instructions, DEFAULT_AGENT_INSTRUCTIONS)
        self.assertEqual(config.openai_max_completion_tokens, 60)
        self.assertEqual(config.openai_llm_temperature, 0.2)
        self.assertIn("recobro amistoso", config.agent_instructions)
        self.assertIn("Cada turno debe avanzar", config.agent_instructions)
        self.assertIn("No uses preguntas vacías", config.agent_instructions)
        self.assertIn("incidencia administrativa con un pago", config.agent_instructions)
        self.assertIn("sin dar producto, importe", config.agent_instructions)
        self.assertIn("menor dato posible", config.agent_instructions)
        self.assertIn("No pidas DNI", config.agent_instructions)
        self.assertIn("MacroHard", config.agent_instructions)
        self.assertIn("Al Corriente S.L.", config.agent_instructions)
        self.assertIn("CloudX", config.agent_instructions)
        self.assertIn("1.527 euros", config.agent_instructions)
        self.assertIn("Veo una mensualidad de CloudX", config.agent_instructions)
        self.assertIn("resolver ahora", config.agent_instructions)
        self.assertIn("clasifica la objeción", config.agent_instructions)
        self.assertIn("Lo reviso un momento... ya lo tengo", config.agent_instructions)
        self.assertIn("nunca te quedes en silencio", config.agent_instructions)
        self.assertIn("No propongas agendar otra llamada", config.agent_instructions)
        self.assertIn("No dejes escapar al cliente", config.agent_instructions)
        self.assertIn("Si el cliente rechaza dos veces", config.agent_instructions)
        self.assertIn("no dejes frases a medias", config.agent_instructions)
        self.assertIn("No inventes vencimientos", config.agent_instructions)
        self.assertIn("máximo 8 palabras", config.agent_instructions)
        self.assertEqual(config.voice_pipeline_mode, "controlled_fast")
        self.assertEqual(config.openai_stt_model, "gpt-4o-transcribe-diarize")
        self.assertEqual(config.openai_fast_stt_model, "gpt-4o-mini-transcribe")
        self.assertTrue(config.openai_fast_stt_realtime)
        self.assertEqual(config.openai_fast_stt_turn_silence_ms, 150)
        self.assertEqual(config.openai_fast_stt_prefix_padding_ms, 300)
        self.assertEqual(config.openai_fast_stt_vad_threshold, 0.5)
        self.assertEqual(config.openai_stt_language, "es")
        self.assertIn("Spanish from Spain", config.openai_tts_instructions)
        self.assertEqual(config.openai_tts_response_format, "pcm")
        self.assertEqual(config.openai_tts_speed, 1.05)
        self.assertTrue(config.barge_in_enabled)
        self.assertIsNone(config.barge_in_turn_detection_mode)
        self.assertEqual(config.barge_in_endpointing_mode, "dynamic")
        self.assertEqual(config.barge_in_interruption_mode, "vad")
        self.assertEqual(config.barge_in_min_speech_seconds, 0.20)
        self.assertEqual(config.barge_in_min_words, 2)
        self.assertEqual(config.barge_in_false_interruption_timeout_seconds, 1.2)
        self.assertTrue(config.barge_in_resume_false_interruption)
        self.assertEqual(config.barge_in_min_endpointing_delay_seconds, 0.20)
        self.assertEqual(config.barge_in_max_endpointing_delay_seconds, 0.55)
        self.assertEqual(config.barge_in_min_consecutive_speech_delay_seconds, 0.10)
        self.assertFalse(config.barge_in_preemptive_generation)
        self.assertEqual(config.barge_in_user_away_timeout_seconds, 30.0)
        self.assertEqual(config.barge_in_confirmation_grace_seconds, 6.0)
        self.assertTrue(config.barge_in_immediate_mute_enabled)
        self.assertIsNone(config.barge_in_telemetry_path)
        self.assertIsNone(config.barge_in_sqlite_path)
        self.assertIsNone(config.voice_metrics_telemetry_path)
        self.assertIsNone(config.voice_metrics_sqlite_path)

    def test_from_env_loads_instruction_file(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            prompt_path = Path(tmp_dir) / "prompt.md"
            prompt_path.write_text("custom file instructions", encoding="utf-8")

            config = AgentConfig.from_env(
                {
                    "AGENT_INSTRUCTIONS_FILE": str(prompt_path),
                }
            )

        self.assertEqual(config.agent_instructions, "custom file instructions")

    def test_direct_instructions_override_instruction_file(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            prompt_path = Path(tmp_dir) / "prompt.md"
            prompt_path.write_text("file instructions", encoding="utf-8")

            config = AgentConfig.from_env(
                {
                    "AGENT_INSTRUCTIONS": "direct instructions",
                    "AGENT_INSTRUCTIONS_FILE": str(prompt_path),
                }
            )

        self.assertEqual(config.agent_instructions, "direct instructions")

    def test_from_env_accepts_barge_in_overrides(self) -> None:
        config = AgentConfig.from_env(
            {
                "BARGE_IN_ENABLED": "false",
                "BARGE_IN_TURN_DETECTION_MODE": "vad",
                "BARGE_IN_ENDPOINTING_MODE": "fixed",
                "BARGE_IN_INTERRUPTION_MODE": "vad",
                "BARGE_IN_MIN_SPEECH_SECONDS": "0.5",
                "BARGE_IN_MIN_WORDS": "2",
                "BARGE_IN_FALSE_INTERRUPTION_TIMEOUT_SECONDS": "none",
                "BARGE_IN_RESUME_FALSE_INTERRUPTION": "no",
                "BARGE_IN_MIN_ENDPOINTING_DELAY_SECONDS": "0.4",
                "BARGE_IN_MAX_ENDPOINTING_DELAY_SECONDS": "0.3",
                "BARGE_IN_MIN_CONSECUTIVE_SPEECH_DELAY_SECONDS": "0.2",
                "BARGE_IN_PREEMPTIVE_GENERATION": "true",
                "BARGE_IN_USER_AWAY_TIMEOUT_SECONDS": "none",
                "BARGE_IN_CONFIRMATION_GRACE_SECONDS": "2.5",
                "BARGE_IN_IMMEDIATE_MUTE_ENABLED": "false",
                "BARGE_IN_TELEMETRY_PATH": "logs/test.jsonl",
                "BARGE_IN_SQLITE_PATH": "logs/test.sqlite3",
                "VOICE_METRICS_TELEMETRY_PATH": "logs/voice.jsonl",
                "VOICE_METRICS_SQLITE_PATH": "logs/voice.sqlite3",
            }
        )

        self.assertFalse(config.barge_in_enabled)
        self.assertEqual(config.barge_in_turn_detection_mode, "vad")
        self.assertEqual(config.barge_in_endpointing_mode, "fixed")
        self.assertEqual(config.barge_in_interruption_mode, "vad")
        self.assertEqual(config.barge_in_min_speech_seconds, 0.5)
        self.assertEqual(config.barge_in_min_words, 2)
        self.assertIsNone(config.barge_in_false_interruption_timeout_seconds)
        self.assertFalse(config.barge_in_resume_false_interruption)
        self.assertEqual(config.barge_in_min_endpointing_delay_seconds, 0.4)
        self.assertEqual(config.barge_in_max_endpointing_delay_seconds, 0.4)
        self.assertEqual(config.barge_in_min_consecutive_speech_delay_seconds, 0.2)
        self.assertTrue(config.barge_in_preemptive_generation)
        self.assertIsNone(config.barge_in_user_away_timeout_seconds)
        self.assertEqual(config.barge_in_confirmation_grace_seconds, 2.5)
        self.assertFalse(config.barge_in_immediate_mute_enabled)
        self.assertEqual(config.barge_in_telemetry_path, "logs/test.jsonl")
        self.assertEqual(config.barge_in_sqlite_path, "logs/test.sqlite3")
        self.assertEqual(config.voice_metrics_telemetry_path, "logs/voice.jsonl")
        self.assertEqual(config.voice_metrics_sqlite_path, "logs/voice.sqlite3")

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
