"""Deterministic guard against agent-playback echo entering the FSM."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re
import time
import unicodedata


_MEANINGLESS_TOKENS = frozenset({"a", "al", "de", "el", "en", "la", "lo", "los", "las", "por", "que", "un", "una", "y"})


@dataclass(frozen=True)
class EchoGuardDecision:
    suppress: bool
    reason: str | None = None


class EchoInputGuard:
    """Reject likely playback echo only while agent audio is active or just ended."""

    def __init__(
        self,
        *,
        post_speech_seconds: float,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._post_speech_seconds = post_speech_seconds
        self._now = now or time.time
        self._agent_speaking = False
        self._last_speech_ended_at: float | None = None
        self._agent_text = ""

    def on_agent_state_changed(self, *, old_state: str, new_state: str, created_at: float) -> None:
        if new_state == "speaking" and old_state != "speaking":
            self._agent_speaking = True
            self._agent_text = ""
        elif old_state == "speaking" and new_state != "speaking":
            self._agent_speaking = False
            self._last_speech_ended_at = created_at

    def on_agent_text_delta(self, text: str) -> None:
        if text:
            self._agent_text = (self._agent_text + text)[-1600:]

    def evaluate(self, transcript: str) -> EchoGuardDecision:
        if not self._is_echo_window_active():
            return EchoGuardDecision(False)

        candidate_words = _words(transcript)
        if len(candidate_words) < 3:
            return EchoGuardDecision(True, "short_fragment_during_agent_playback")

        candidate_content = _content_words(candidate_words)
        agent_content = _content_words(_words(self._agent_text))
        if _has_shared_phrase(candidate_content, agent_content):
            return EchoGuardDecision(True, "agent_playback_phrase_overlap")
        return EchoGuardDecision(False)

    def is_likely_playback_echo(self, transcript: str) -> bool:
        """Identify echo phrases without rejecting an ordinary short caller turn."""

        if not self._is_echo_window_active():
            return False
        candidate_content = _content_words(_words(transcript))
        agent_content = _content_words(_words(self._agent_text))
        if len(candidate_content) == 1:
            return candidate_content[0] in agent_content
        return _has_shared_phrase(candidate_content, agent_content)

    def _is_echo_window_active(self) -> bool:
        if self._agent_speaking:
            return True
        if self._last_speech_ended_at is None:
            return False
        return (self._now() - self._last_speech_ended_at) <= self._post_speech_seconds


def _words(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", text.lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.findall(r"[a-z0-9]+", normalized)


def _content_words(words: list[str]) -> list[str]:
    return [word for word in words if len(word) >= 3 and word not in _MEANINGLESS_TOKENS]


def _has_shared_phrase(candidate: list[str], agent: list[str]) -> bool:
    if len(candidate) < 2 or len(agent) < 2:
        return False
    agent_pairs = set(zip(agent, agent[1:]))
    return any(pair in agent_pairs for pair in zip(candidate, candidate[1:]))
