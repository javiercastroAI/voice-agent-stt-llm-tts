from __future__ import annotations

import unittest

from voice_agent.echo_guard import EchoInputGuard


class EchoInputGuardTests(unittest.TestCase):
    def make_guard(self, *, now: float = 10.0) -> EchoInputGuard:
        return EchoInputGuard(post_speech_seconds=1.2, now=lambda: now)

    def test_suppresses_short_fragment_during_agent_playback(self) -> None:
        guard = self.make_guard()
        guard.on_agent_state_changed(old_state="thinking", new_state="speaking", created_at=1.0)

        decision = guard.evaluate("Mhm.")

        self.assertTrue(decision.suppress)
        self.assertEqual(decision.reason, "short_fragment_during_agent_playback")

    def test_suppresses_shared_agent_phrase(self) -> None:
        guard = self.make_guard()
        guard.on_agent_state_changed(old_state="thinking", new_state="speaking", created_at=1.0)
        guard.on_agent_text_delta("Tiene varias opciones para resolver este asunto.")

        decision = guard.evaluate("Hay dos opciones para resolverlo.")

        self.assertTrue(decision.suppress)
        self.assertEqual(decision.reason, "agent_playback_phrase_overlap")

    def test_allows_normal_turn_after_post_speech_window(self) -> None:
        guard = EchoInputGuard(post_speech_seconds=1.2, now=lambda: 3.0)
        guard.on_agent_state_changed(old_state="thinking", new_state="speaking", created_at=1.0)
        guard.on_agent_text_delta("Tiene varias opciones para resolver este asunto.")
        guard.on_agent_state_changed(old_state="speaking", new_state="listening", created_at=1.5)

        decision = guard.evaluate("Quiero hablar de otra cosa.")

        self.assertFalse(decision.suppress)

    def test_identifies_recent_playback_phrase_for_barge_in(self) -> None:
        guard = self.make_guard()
        guard.on_agent_state_changed(old_state="thinking", new_state="speaking", created_at=1.0)
        guard.on_agent_text_delta("La mensualidad de CloudX sigue pendiente.")

        self.assertTrue(guard.is_likely_playback_echo("mensualidad CloudX"))
