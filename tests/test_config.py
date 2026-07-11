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
                "OPENAI_INTENT_MODEL": " gpt-4o-mini ",
                "FSM_INTENT_TIMEOUT_SECONDS": " 1.5 ",
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
                "FSM_ENABLED": " false ",
                "FSM_AUTO_OPENING_ENABLED": " false ",
                "CASE_CONTEXT_FILE": " examples/collections/custom.json ",
                "FSM_TRACE_PATH": " logs/custom-fsm.jsonl ",
            }
        )

        self.assertEqual(config.openai_api_key, "openai-key")
        self.assertEqual(config.openai_model, "gpt-4o-mini")
        self.assertEqual(config.openai_intent_model, "gpt-4o-mini")
        self.assertEqual(config.fsm_intent_timeout_seconds, 1.5)
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
        self.assertFalse(config.fsm_enabled)
        self.assertFalse(config.fsm_auto_opening_enabled)
        self.assertEqual(
            config.case_context_file,
            "examples/collections/custom.json",
        )
        self.assertEqual(config.fsm_trace_path, "logs/custom-fsm.jsonl")

    def test_from_env_uses_instruction_default(self) -> None:
        config = AgentConfig.from_env({})
        self.assertEqual(config.agent_instructions, DEFAULT_AGENT_INSTRUCTIONS)
        self.assertEqual(config.openai_max_completion_tokens, 40)
        self.assertEqual(config.openai_llm_temperature, 0.2)
        self.assertIn("recobro amistoso", config.agent_instructions)
        self.assertIn("Cada turno debe avanzar", config.agent_instructions)
        self.assertIn("No uses preguntas vacías", config.agent_instructions)
        self.assertIn("RUNTIME FSM CONTROL", config.agent_instructions)
        self.assertIn("Si el bloque no contiene un objeto `case`", config.agent_instructions)
        self.assertIn("Antes de verificar identidad", config.agent_instructions)
        self.assertIn("verification_fields", config.agent_instructions)
        self.assertIn("No pidas DNI", config.agent_instructions)
        self.assertNotIn("MacroHard", config.agent_instructions)
        self.assertNotIn("Al Corriente S.L.", config.agent_instructions)
        self.assertNotIn("CloudX", config.agent_instructions)
        self.assertNotIn("1.527 euros", config.agent_instructions)
        self.assertIn("available_resolution_types", config.agent_instructions)
        self.assertIn("No simules acceso a sistemas", config.agent_instructions)
        self.assertIn("No propongas agendar otra llamada", config.agent_instructions)
        self.assertIn("no dejes frases a medias", config.agent_instructions)
        self.assertIn("No inventes vencimientos", config.agent_instructions)
        self.assertIn("máximo 8 palabras", config.agent_instructions)
        self.assertEqual(config.openai_intent_model, "gpt-4o-mini")
        self.assertEqual(config.fsm_intent_timeout_seconds, 5.0)
        self.assertTrue(config.fsm_enabled)
        self.assertTrue(config.fsm_auto_opening_enabled)
        self.assertEqual(
            config.case_context_file,
            "examples/collections/al-corriente.case.json",
        )
        self.assertIsNone(config.fsm_trace_path)
        self.assertEqual(config.voice_pipeline_mode, "controlled_fast")
        self.assertEqual(config.openai_stt_model, "gpt-4o-transcribe-diarize")
        self.assertEqual(config.openai_fast_stt_model, "gpt-4o-mini-transcribe")
        self.assertTrue(config.openai_fast_stt_realtime)
        self.assertEqual(config.openai_fast_stt_turn_silence_ms, 400)
        self.assertEqual(config.openai_fast_stt_prefix_padding_ms, 300)
        self.assertEqual(config.openai_fast_stt_vad_threshold, 0.70)
        self.assertEqual(config.openai_stt_language, "es")
        self.assertIn("Spanish from Spain", config.openai_tts_instructions)
        self.assertEqual(config.openai_tts_response_format, "pcm")
        self.assertEqual(config.openai_tts_speed, 1.05)
        self.assertTrue(config.barge_in_enabled)
        self.assertIsNone(config.barge_in_turn_detection_mode)
        self.assertEqual(config.barge_in_endpointing_mode, "dynamic")
        self.assertEqual(config.barge_in_interruption_mode, "vad")
        self.assertEqual(config.silero_vad_activation_threshold, 0.70)
        self.assertEqual(config.silero_vad_deactivation_threshold, 0.50)
        self.assertEqual(config.silero_vad_min_speech_seconds, 0.40)
        self.assertEqual(config.silero_vad_min_silence_seconds, 0.65)
        self.assertEqual(config.silero_vad_prefix_padding_seconds, 0.30)
        self.assertEqual(config.barge_in_min_speech_seconds, 0.50)
        self.assertEqual(config.barge_in_min_words, 2)
        self.assertEqual(config.barge_in_false_interruption_timeout_seconds, 2.0)
        self.assertTrue(config.barge_in_resume_false_interruption)
        self.assertEqual(config.barge_in_min_endpointing_delay_seconds, 0.40)
        self.assertEqual(config.barge_in_max_endpointing_delay_seconds, 1.20)
        self.assertEqual(config.barge_in_min_consecutive_speech_delay_seconds, 0.20)
        self.assertFalse(config.barge_in_preemptive_generation)
        self.assertEqual(config.barge_in_user_away_timeout_seconds, 30.0)
        self.assertEqual(config.barge_in_confirmation_grace_seconds, 6.0)
        self.assertFalse(config.barge_in_immediate_mute_enabled)
        self.assertTrue(config.barge_in_native_interruption_enabled)
        self.assertTrue(config.barge_in_soft_pause_enabled)
        self.assertEqual(config.barge_in_soft_recovery_delay_seconds, 1.50)
        self.assertEqual(config.aec_warmup_seconds, 8.0)
        self.assertEqual(config.echo_guard_post_speech_seconds, 1.2)
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
                "SILERO_VAD_ACTIVATION_THRESHOLD": "0.8",
                "SILERO_VAD_DEACTIVATION_THRESHOLD": "0.9",
                "SILERO_VAD_MIN_SPEECH_SECONDS": "0.55",
                "SILERO_VAD_MIN_SILENCE_SECONDS": "0.75",
                "SILERO_VAD_PREFIX_PADDING_SECONDS": "0.25",
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
        self.assertEqual(config.silero_vad_activation_threshold, 0.8)
        self.assertEqual(config.silero_vad_deactivation_threshold, 0.8)
        self.assertEqual(config.silero_vad_min_speech_seconds, 0.55)
        self.assertEqual(config.silero_vad_min_silence_seconds, 0.75)
        self.assertEqual(config.silero_vad_prefix_padding_seconds, 0.25)
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

    def test_validate_rejects_missing_case_context_file(self) -> None:
        config = AgentConfig.from_env(
            {
                "OPENAI_API_KEY": "openai-key",
                "CASE_CONTEXT_FILE": "examples/collections/does-not-exist.json",
            }
        )

        with self.assertRaises(ConfigError) as ctx:
            config.validate_for_command("console")

        self.assertIn("Case context file not found", str(ctx.exception))
