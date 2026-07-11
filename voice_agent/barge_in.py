"""Barge-in policy, session options, and observability helpers."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Callable, Protocol

from livekit.agents.voice.events import (
    AgentFalseInterruptionEvent,
    AgentStateChangedEvent,
    UserInputTranscribedEvent,
    UserStateChangedEvent,
)

from .config import AgentConfig


class BargeInStore(Protocol):
    def set_barge_in_state(self, state: dict[str, object]) -> None: ...

    def add_barge_in_event(self, event: dict[str, object]) -> None: ...

    def set_metric_panel(
        self,
        *,
        panel_id: str,
        title: str,
        items: list[dict[str, str]],
    ) -> None: ...


ImmediateMuteCallback = Callable[[float], tuple[bool, str | None]]
OutputControlCallback = Callable[[float], tuple[bool, str | None]]
OutputActiveCallback = Callable[[], bool]
PlaybackEchoCallback = Callable[[str], bool]

_EXPLICIT_ONE_WORD_STOP_COMMANDS = frozenset(
    {"para", "pare", "alto", "espera", "basta", "stop", "silencio"}
)


@dataclass(frozen=True)
class BargeTurnDecision:
    """Whether a completed transcript may receive FSM authority."""

    accepted: bool
    reason: str


@dataclass(frozen=True)
class BargeInPolicy:
    """Contact-center defaults for natural but conservative interruption."""

    enabled: bool
    turn_detection_mode: str | None
    endpointing_mode: str
    interruption_mode: str
    min_speech_seconds: float
    min_words: int
    false_interruption_timeout_seconds: float | None
    resume_false_interruption: bool
    min_endpointing_delay_seconds: float
    max_endpointing_delay_seconds: float
    min_consecutive_speech_delay_seconds: float
    preemptive_generation: bool
    user_away_timeout_seconds: float | None
    confirmation_grace_seconds: float
    immediate_mute_enabled: bool
    native_interruption_enabled: bool
    soft_pause_enabled: bool
    soft_recovery_delay_seconds: float
    telemetry_path: str | None
    sqlite_path: str | None

    @classmethod
    def from_config(cls, config: AgentConfig) -> "BargeInPolicy":
        return cls(
            enabled=config.barge_in_enabled,
            turn_detection_mode=config.barge_in_turn_detection_mode,
            endpointing_mode=config.barge_in_endpointing_mode,
            interruption_mode=config.barge_in_interruption_mode,
            min_speech_seconds=config.barge_in_min_speech_seconds,
            min_words=config.barge_in_min_words,
            false_interruption_timeout_seconds=(
                config.barge_in_false_interruption_timeout_seconds
            ),
            resume_false_interruption=config.barge_in_resume_false_interruption,
            min_endpointing_delay_seconds=config.barge_in_min_endpointing_delay_seconds,
            max_endpointing_delay_seconds=config.barge_in_max_endpointing_delay_seconds,
            min_consecutive_speech_delay_seconds=(
                config.barge_in_min_consecutive_speech_delay_seconds
            ),
            preemptive_generation=config.barge_in_preemptive_generation,
            user_away_timeout_seconds=config.barge_in_user_away_timeout_seconds,
            confirmation_grace_seconds=config.barge_in_confirmation_grace_seconds,
            immediate_mute_enabled=config.barge_in_immediate_mute_enabled,
            native_interruption_enabled=config.barge_in_native_interruption_enabled,
            soft_pause_enabled=config.barge_in_soft_pause_enabled,
            soft_recovery_delay_seconds=config.barge_in_soft_recovery_delay_seconds,
            telemetry_path=config.barge_in_telemetry_path,
            sqlite_path=config.barge_in_sqlite_path,
        )

    def session_options(self) -> dict[str, object]:
        turn_handling: dict[str, object] = {
            "endpointing": {
                "mode": self.endpointing_mode,
                "min_delay": self.min_endpointing_delay_seconds,
                "max_delay": self.max_endpointing_delay_seconds,
            },
            "interruption": {
                "enabled": self.native_interruption_enabled,
                "mode": self.interruption_mode,
                "discard_audio_if_uninterruptible": True,
                "min_duration": self.min_speech_seconds,
                "min_words": self.min_words,
                "false_interruption_timeout": self.false_interruption_timeout_seconds,
                "resume_false_interruption": self.resume_false_interruption,
            },
        }
        if self.turn_detection_mode is not None:
            turn_handling["turn_detection"] = self.turn_detection_mode

        return {
            "turn_handling": turn_handling,
            "min_consecutive_speech_delay": self.min_consecutive_speech_delay_seconds,
            "preemptive_generation": self.preemptive_generation,
            "user_away_timeout": self.user_away_timeout_seconds,
        }


@dataclass
class BargeInStats:
    detected: int = 0
    confirmed: int = 0
    ignored: int = 0
    false_interruptions: int = 0
    resumed_false_interruptions: int = 0
    backchannel_confirmed: int = 0
    command_confirmed: int = 0
    stt_language_mismatches: int = 0
    late_transcripts_after_ignored: int = 0
    turns_without_interruption: int = 0
    immediate_mute_attempts: int = 0
    immediate_mute_successes: int = 0
    immediate_mute_failures: int = 0
    soft_pause_attempts: int = 0
    soft_pause_successes: int = 0
    soft_pause_failures: int = 0
    soft_resume_attempts: int = 0
    soft_resume_successes: int = 0
    soft_resume_failures: int = 0
    confirmed_cancel_attempts: int = 0
    confirmed_cancel_successes: int = 0
    confirmed_cancel_failures: int = 0


@dataclass
class BargeInKpis:
    confirmation_rate: float = 0.0
    turn_confirmation_rate: float = 0.0
    false_candidate_rate: float = 0.0
    turn_false_candidate_rate: float = 0.0
    ghost_interruption_rate: float = 0.0
    backchannel_rate: float = 0.0
    command_interruption_rate: float = 0.0
    average_confirmation_delay_seconds: float | None = None
    max_confirmation_delay_seconds: float | None = None
    average_pending_transcript_seconds: float | None = None
    max_pending_transcript_seconds: float | None = None
    late_transcript_after_ignored_rate: float = 0.0
    average_overtalk_seconds: float | None = None
    max_overtalk_seconds: float | None = None
    average_mute_latency_seconds: float | None = None
    max_mute_latency_seconds: float | None = None
    immediate_mute_success_rate: float = 0.0
    average_cancel_latency_seconds: float | None = None
    max_cancel_latency_seconds: float | None = None
    average_recovery_seconds: float | None = None
    max_recovery_seconds: float | None = None
    language_mismatch_rate: float = 0.0
    detected_turns: int = 0
    confirmed_turns: int = 0
    ignored_turns: int = 0
    turns_without_interruption: int = 0
    interrupted_tts_duration_seconds: float | None = None


class BargeInController:
    """Tracks barge-in state and metrics around LiveKit's native interruption engine."""

    def __init__(
        self,
        policy: BargeInPolicy,
        *,
        store: BargeInStore | None = None,
        on_immediate_mute: ImmediateMuteCallback | None = None,
        on_soft_pause: OutputControlCallback | None = None,
        on_soft_resume: OutputControlCallback | None = None,
        on_confirmed_interrupt: OutputControlCallback | None = None,
        is_agent_output_active: OutputActiveCallback | None = None,
        is_playback_echo: PlaybackEchoCallback | None = None,
        call_id: str | None = None,
    ) -> None:
        self._policy = policy
        self._store = store
        self._on_immediate_mute = on_immediate_mute
        self._on_soft_pause = on_soft_pause
        self._on_soft_resume = on_soft_resume
        self._on_confirmed_interrupt = on_confirmed_interrupt
        self._is_agent_output_active = is_agent_output_active
        self._is_playback_echo = is_playback_echo
        self._call_id = call_id
        self._stats = BargeInStats()
        self._agent_state = "initializing"
        self._user_state = "listening"
        self._state = "disabled" if not policy.enabled else "monitoring"
        self._candidate_active = False
        self._candidate_has_transcript = False
        self._candidate_started_at: float | None = None
        self._candidate_ended_at: float | None = None
        self._candidate_agent_speaking_ended_at: float | None = None
        self._candidate_muted_at: float | None = None
        self._candidate_resumed_at: float | None = None
        self._candidate_overtalk_recorded = False
        self._candidate_soft_paused = False
        self._candidate_confirmed_interrupt_requested = False
        self._soft_recovery_handle: asyncio.TimerHandle | None = None
        self._turn_decisions: deque[tuple[str, BargeTurnDecision]] = deque(maxlen=24)
        self._awaiting_accepted_final = False
        self._agent_speech_started_at: float | None = None
        self._last_confirmed_at: float | None = None
        self._last_ignored_at: float | None = None
        self._last_ignored_reason_code: str | None = None
        self._last_ignored_candidate_turn_id: int | None = None
        self._pending_recovery = False
        self._agent_turn_id = 0
        self._candidate_turn_id: int | None = None
        self._turn_had_candidate = False
        self._detected_turn_ids: set[int] = set()
        self._confirmed_turn_ids: set[int] = set()
        self._ignored_turn_ids: set[int] = set()
        self._confirmation_delays: list[float] = []
        self._pending_transcript_delays: list[float] = []
        self._recent_pending_transcript_delays: deque[float] = deque(maxlen=8)
        self._overtalk_durations: list[float] = []
        self._mute_latencies: list[float] = []
        self._cancel_latencies: list[float] = []
        self._recovery_durations: list[float] = []
        self._last_reason = (
            "Barge-in disabled"
            if not policy.enabled
            else "Waiting for user speech while agent is speaking"
        )
        self._publish()

    @property
    def policy(self) -> BargeInPolicy:
        return self._policy

    @property
    def stats(self) -> BargeInStats:
        return BargeInStats(**self._stats.__dict__)

    @property
    def kpis(self) -> BargeInKpis:
        return self._build_kpis()

    def consume_user_turn_decision(self, transcript: str) -> BargeTurnDecision | None:
        """Return and consume the barge decision for this completed STT turn."""

        normalized = self._normalize_transcript(transcript)
        for index, (recorded, decision) in enumerate(self._turn_decisions):
            if recorded == normalized:
                del self._turn_decisions[index]
                return decision
        return None

    def on_agent_state_changed(self, event: AgentStateChangedEvent) -> None:
        self._expire_pending_candidate(event.created_at)
        old_agent_state = self._agent_state
        self._agent_state = event.new_state
        if not self._policy.enabled:
            self._publish()
            return

        if event.new_state == "speaking" and old_agent_state != "speaking":
            self._agent_turn_id += 1
            self._agent_speech_started_at = event.created_at
            self._turn_had_candidate = False
            if self._pending_recovery and self._last_confirmed_at is not None:
                self._recovery_durations.append(
                    max(0.0, event.created_at - self._last_confirmed_at)
                )
                self._pending_recovery = False

        if old_agent_state == "speaking" and event.new_state != "speaking":
            if self._candidate_started_at is not None:
                self._candidate_agent_speaking_ended_at = event.created_at
                self._record_candidate_overtalk(event.created_at)
            if not self._turn_had_candidate:
                self._stats.turns_without_interruption += 1
                self._record_event(
                    "turn_without_interruption",
                    created_at=event.created_at,
                    reason="Agent turn ended without a barge-in candidate",
                    agent_turn_id=self._agent_turn_id,
                )
            self._agent_speech_started_at = None

        if event.new_state == "speaking" and not self._candidate_active:
            self._state = "monitoring"
            self._last_reason = "Agent speech can be interrupted by qualified user speech"
        elif event.new_state in {"idle", "listening", "thinking"} and not self._candidate_active:
            self._state = "monitoring"

        self._publish()

    def on_user_state_changed(self, event: UserStateChangedEvent) -> None:
        self._expire_pending_candidate(event.created_at)
        self._user_state = event.new_state
        if not self._policy.enabled:
            self._publish()
            return

        if event.new_state == "speaking" and self._agent_output_is_active():
            self._candidate_active = True
            self._candidate_has_transcript = False
            self._candidate_started_at = event.created_at
            self._candidate_ended_at = None
            self._candidate_agent_speaking_ended_at = None
            self._candidate_muted_at = None
            self._candidate_resumed_at = None
            self._candidate_overtalk_recorded = False
            self._candidate_soft_paused = False
            self._candidate_confirmed_interrupt_requested = False
            self._awaiting_accepted_final = False
            self._candidate_turn_id = self._agent_turn_id
            self._turn_had_candidate = True
            self._detected_turn_ids.add(self._agent_turn_id)
            self._stats.detected += 1
            self._state = "candidate"
            self._last_reason = (
                "User speech detected during agent speech; waiting for policy thresholds"
            )
            mute_result = self._attempt_immediate_mute(event.created_at)
            pause_result = self._attempt_soft_pause(event.created_at)
            if mute_result["immediate_mute_success"] or pause_result["soft_pause_success"]:
                self._state = "agent_audio_paused"
                self._last_reason = (
                    "User speech detected during agent speech; agent audio paused pending STT confirmation"
                )
            self._record_event(
                "candidate_detected",
                created_at=event.created_at,
                reason=self._last_reason,
                agent_turn_id=self._candidate_turn_id,
                **mute_result,
                **pause_result,
            )
        elif event.new_state != "speaking" and self._candidate_active:
            if not self._candidate_has_transcript:
                self._state = "pending_transcript"
                self._candidate_ended_at = event.created_at
                self._last_reason = (
                    "Candidate speech ended; holding audio for bounded STT recovery"
                )
                self._record_event(
                    "candidate_pending_transcript",
                    created_at=event.created_at,
                    reason=self._last_reason,
                    agent_turn_id=self._candidate_turn_id,
                )
                self._schedule_soft_recovery()
            else:
                self._candidate_ended_at = event.created_at
            self._candidate_active = False

        self._publish()

    def on_user_input_transcribed(self, event: UserInputTranscribedEvent) -> None:
        self._expire_pending_candidate(event.created_at)
        if not self._policy.enabled:
            self._publish()
            return

        transcript = event.transcript.strip()
        if not transcript:
            return

        word_count = self._word_count(transcript)
        if not self._has_open_candidate(event.created_at):
            if event.is_final and self._awaiting_accepted_final:
                self._record_turn_decision(
                    transcript, accepted=True, reason="qualified_barge_in"
                )
                self._awaiting_accepted_final = False
                self._publish()
                return
            if self._record_late_transcript_after_ignored(
                event=event,
                transcript=transcript,
                word_count=word_count,
            ):
                self._publish()
            return

        qualified, rejection_reason = self._qualify_transcript(transcript, word_count)
        if not qualified:
            if event.is_final and not self._candidate_active:
                self._ignore_candidate(
                    created_at=event.created_at,
                    reason=(
                        "Candidate transcript matched recent agent playback"
                        if rejection_reason == "playback_echo"
                        else "Transcript did not meet the qualified interruption threshold"
                    ),
                    reason_code=rejection_reason or "below_min_words",
                    user_transcript=transcript,
                )
            self._publish()
            return

        if not self._candidate_has_transcript:
            self._candidate_has_transcript = True
            self._stats.confirmed += 1
            if self._candidate_turn_id is not None:
                self._confirmed_turn_ids.add(self._candidate_turn_id)

        confirmation_delay = self._confirmation_delay(event.created_at)
        if confirmation_delay is not None:
            self._confirmation_delays.append(confirmation_delay)
            self._cancel_latencies.append(confirmation_delay)
        pending_delay = self._pending_delay(event.created_at)
        if pending_delay is not None:
            self._pending_transcript_delays.append(pending_delay)
            self._recent_pending_transcript_delays.append(pending_delay)
        transcript_class = self._classify_transcript(transcript)
        if transcript_class == "backchannel":
            self._stats.backchannel_confirmed += 1
        else:
            self._stats.command_confirmed += 1
        language_mismatch = self._is_language_mismatch(transcript, event.language)
        if language_mismatch:
            self._stats.stt_language_mismatches += 1

        self._state = "interrupted"
        self._last_reason = "Qualified user transcript confirmed the interruption"
        self._cancel_soft_recovery()
        if event.is_final:
            self._record_turn_decision(transcript, accepted=True, reason="qualified_barge_in")
        else:
            self._awaiting_accepted_final = True
        cancel_result = self._attempt_confirmed_interrupt(event.created_at)
        self._record_event(
            "candidate_confirmed",
            created_at=event.created_at,
            reason=self._last_reason,
            agent_turn_id=self._candidate_turn_id,
            transcript=transcript,
            transcript_class=transcript_class,
            language=event.language,
            language_mismatch=language_mismatch,
            word_count=word_count,
            is_final=event.is_final,
            confirmation_delay_seconds=confirmation_delay,
            pending_transcript_seconds=pending_delay,
            overtalk_seconds=self._current_overtalk(event.created_at),
            **cancel_result,
        )
        self._record_candidate_overtalk(event.created_at)
        self._last_confirmed_at = event.created_at
        self._pending_recovery = True
        self._candidate_active = False
        self._candidate_started_at = None
        self._candidate_ended_at = None
        self._candidate_agent_speaking_ended_at = None
        self._candidate_muted_at = None
        self._candidate_resumed_at = None
        self._candidate_soft_paused = False
        self._candidate_confirmed_interrupt_requested = False
        self._publish()

    def on_agent_false_interruption(self, event: AgentFalseInterruptionEvent) -> None:
        self._expire_pending_candidate(event.created_at)
        if not self._policy.enabled:
            self._publish()
            return

        self._stats.false_interruptions += 1
        if event.resumed:
            self._stats.resumed_false_interruptions += 1

        resume_result = self._attempt_soft_resume(event.created_at)
        self._cancel_soft_recovery()
        self._candidate_active = False
        self._candidate_has_transcript = False
        self._candidate_started_at = None
        self._candidate_ended_at = None
        self._candidate_agent_speaking_ended_at = None
        self._candidate_muted_at = None
        self._candidate_resumed_at = None
        self._candidate_overtalk_recorded = False
        self._candidate_soft_paused = False
        self._candidate_confirmed_interrupt_requested = False
        self._state = "false_interruption_resumed" if event.resumed else "false_interruption"
        self._last_reason = (
            "False interruption resumed automatically"
            if event.resumed
            else "False interruption detected without automatic resume"
        )
        self._record_event(
            "false_interruption",
            created_at=event.created_at,
            reason=self._last_reason,
            agent_turn_id=self._candidate_turn_id,
            resumed=event.resumed,
            **resume_result,
        )
        self._publish()

    def _has_open_candidate(self, created_at: float) -> bool:
        if self._candidate_active:
            return True
        if self._candidate_ended_at is None:
            return False
        return (created_at - self._candidate_ended_at) <= self._policy.confirmation_grace_seconds

    def _agent_output_is_active(self) -> bool:
        """Include native-paused output, which LiveKit reports as listening."""

        if self._agent_state == "speaking":
            return True
        if self._is_agent_output_active is None:
            return False
        try:
            return bool(self._is_agent_output_active())
        except Exception:
            return False

    def _qualify_transcript(self, transcript: str, word_count: int) -> tuple[bool, str | None]:
        if self._is_playback_echo is not None:
            try:
                if self._is_playback_echo(transcript):
                    return False, "playback_echo"
            except Exception:
                pass
        if word_count >= self._policy.min_words:
            return True, None
        normalized = self._normalized_words(transcript)
        if len(normalized) == 1 and normalized[0] in _EXPLICIT_ONE_WORD_STOP_COMMANDS:
            return True, None
        return False, "below_qualified_word_threshold"

    def _expire_pending_candidate(self, created_at: float) -> None:
        if self._candidate_ended_at is None or self._candidate_has_transcript:
            return
        if (created_at - self._candidate_ended_at) <= self._policy.confirmation_grace_seconds:
            return
        self._ignore_candidate(
            created_at=created_at,
            reason="Candidate interruption expired before STT confirmation",
            reason_code="expired_before_stt",
        )

    def _ignore_candidate(
        self,
        *,
        created_at: float,
        reason: str,
        reason_code: str,
        user_transcript: str | None = None,
    ) -> None:
        self._cancel_soft_recovery()
        if user_transcript:
            self._record_turn_decision(
                user_transcript,
                accepted=False,
                reason=f"rejected_barge_in:{reason_code}",
            )
        self._stats.ignored += 1
        if self._candidate_turn_id is not None:
            self._ignored_turn_ids.add(self._candidate_turn_id)
        self._state = "monitoring"
        self._last_reason = reason
        self._last_ignored_at = created_at
        self._last_ignored_reason_code = reason_code
        self._last_ignored_candidate_turn_id = self._candidate_turn_id
        self._record_event(
            "candidate_ignored",
            created_at=created_at,
            reason=reason,
            ignore_reason_code=reason_code,
            agent_turn_id=self._candidate_turn_id,
            confirmation_delay_seconds=self._confirmation_delay(created_at),
            pending_transcript_seconds=self._pending_delay(created_at),
            overtalk_seconds=self._current_overtalk(created_at),
            **self._attempt_soft_resume(created_at),
        )
        self._record_candidate_overtalk(created_at)
        self._candidate_active = False
        self._candidate_has_transcript = False
        self._candidate_started_at = None
        self._candidate_ended_at = None
        self._candidate_agent_speaking_ended_at = None
        self._candidate_muted_at = None
        self._candidate_resumed_at = None
        self._candidate_overtalk_recorded = False
        self._candidate_soft_paused = False
        self._candidate_confirmed_interrupt_requested = False

    def _attempt_immediate_mute(self, created_at: float) -> dict[str, object]:
        if not self._policy.immediate_mute_enabled:
            return {
                "immediate_mute_enabled": False,
                "immediate_mute_attempted": False,
                "immediate_mute_success": False,
                "immediate_mute_latency_seconds": None,
                "immediate_mute_method": None,
            }

        if self._on_immediate_mute is None:
            return {
                "immediate_mute_enabled": True,
                "immediate_mute_attempted": False,
                "immediate_mute_success": False,
                "immediate_mute_latency_seconds": None,
                "immediate_mute_method": None,
                "immediate_mute_error": "No immediate mute callback configured",
            }

        self._stats.immediate_mute_attempts += 1
        try:
            success, method_or_error = self._on_immediate_mute(created_at)
        except Exception as exc:
            self._stats.immediate_mute_failures += 1
            return {
                "immediate_mute_enabled": True,
                "immediate_mute_attempted": True,
                "immediate_mute_success": False,
                "immediate_mute_latency_seconds": None,
                "immediate_mute_method": None,
                "immediate_mute_error": f"{exc.__class__.__name__}: {exc}",
            }

        if not success:
            self._stats.immediate_mute_failures += 1
            return {
                "immediate_mute_enabled": True,
                "immediate_mute_attempted": True,
                "immediate_mute_success": False,
                "immediate_mute_latency_seconds": None,
                "immediate_mute_method": None,
                "immediate_mute_error": method_or_error,
            }

        self._stats.immediate_mute_successes += 1
        self._candidate_muted_at = created_at
        self._mute_latencies.append(0.0)
        return {
            "immediate_mute_enabled": True,
            "immediate_mute_attempted": True,
            "immediate_mute_success": True,
            "immediate_mute_latency_seconds": 0.0,
            "immediate_mute_method": method_or_error,
        }

    def _attempt_soft_pause(self, created_at: float) -> dict[str, object]:
        if not self._policy.soft_pause_enabled:
            return self._control_result("soft_pause", enabled=False)
        result = self._run_control_callback(
            kind="soft_pause",
            callback=self._on_soft_pause,
            created_at=created_at,
        )
        if result["soft_pause_success"]:
            self._candidate_soft_paused = True
            self._candidate_muted_at = created_at
            self._mute_latencies.append(0.0)
        return result

    def _attempt_soft_resume(self, created_at: float) -> dict[str, object]:
        if not self._candidate_soft_paused:
            return self._control_result("soft_resume", enabled=self._policy.soft_pause_enabled)
        result = self._run_control_callback(
            kind="soft_resume",
            callback=self._on_soft_resume,
            created_at=created_at,
        )
        if result["soft_resume_success"]:
            self._candidate_soft_paused = False
            self._candidate_resumed_at = created_at
        return result

    def _schedule_soft_recovery(self) -> None:
        self._cancel_soft_recovery()
        if not self._candidate_soft_paused:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._soft_recovery_handle = loop.call_later(
            self._adaptive_soft_recovery_delay(),
            self._recover_soft_paused_candidate,
        )

    def _adaptive_soft_recovery_delay(self) -> float:
        if not self._recent_pending_transcript_delays:
            return self._policy.soft_recovery_delay_seconds
        average_delay = sum(self._recent_pending_transcript_delays) / len(
            self._recent_pending_transcript_delays
        )
        return min(2.50, max(self._policy.soft_recovery_delay_seconds, average_delay + 0.25))

    def _cancel_soft_recovery(self) -> None:
        if self._soft_recovery_handle is not None:
            self._soft_recovery_handle.cancel()
            self._soft_recovery_handle = None

    def _recover_soft_paused_candidate(self) -> None:
        self._soft_recovery_handle = None
        if self._candidate_ended_at is None or self._candidate_has_transcript:
            return
        created_at = time.time()
        result = self._attempt_soft_resume(created_at)
        if not result["soft_resume_success"]:
            return
        self._last_reason = "Soft pause recovered after bounded STT wait"
        self._record_event(
            "candidate_soft_recovered",
            created_at=created_at,
            reason=self._last_reason,
            agent_turn_id=self._candidate_turn_id,
            recovery_delay_seconds=self._adaptive_soft_recovery_delay(),
            **result,
        )
        self._publish()

    def _attempt_confirmed_interrupt(self, created_at: float) -> dict[str, object]:
        if self._candidate_confirmed_interrupt_requested:
            return self._control_result("confirmed_cancel", enabled=True)
        result = self._run_control_callback(
            kind="confirmed_cancel",
            callback=self._on_confirmed_interrupt,
            created_at=created_at,
        )
        self._candidate_confirmed_interrupt_requested = bool(
            result["confirmed_cancel_success"]
        )
        return result

    def _run_control_callback(
        self,
        *,
        kind: str,
        callback: OutputControlCallback | None,
        created_at: float,
    ) -> dict[str, object]:
        if callback is None:
            return self._control_result(kind, enabled=True, error="No output control callback configured")
        attempts = f"{kind}_attempts"
        successes = f"{kind}_successes"
        failures = f"{kind}_failures"
        setattr(self._stats, attempts, getattr(self._stats, attempts) + 1)
        try:
            success, method_or_error = callback(created_at)
        except Exception as exc:
            setattr(self._stats, failures, getattr(self._stats, failures) + 1)
            return self._control_result(
                kind,
                enabled=True,
                attempted=True,
                error=f"{exc.__class__.__name__}: {exc}",
            )
        if not success:
            setattr(self._stats, failures, getattr(self._stats, failures) + 1)
            return self._control_result(
                kind, enabled=True, attempted=True, error=method_or_error
            )
        setattr(self._stats, successes, getattr(self._stats, successes) + 1)
        return self._control_result(
            kind, enabled=True, attempted=True, success=True, method=method_or_error
        )

    @staticmethod
    def _control_result(
        kind: str,
        *,
        enabled: bool,
        attempted: bool = False,
        success: bool = False,
        method: str | None = None,
        error: str | None = None,
    ) -> dict[str, object]:
        return {
            f"{kind}_enabled": enabled,
            f"{kind}_attempted": attempted,
            f"{kind}_success": success,
            f"{kind}_method": method,
            f"{kind}_error": error,
        }

    def _record_candidate_overtalk(self, created_at: float) -> None:
        if self._candidate_overtalk_recorded:
            return
        overtalk = self._current_overtalk(created_at)
        if overtalk is None:
            return
        self._overtalk_durations.append(overtalk)
        if self._candidate_muted_at is None:
            self._mute_latencies.append(overtalk)
        self._candidate_overtalk_recorded = True

    def _record_late_transcript_after_ignored(
        self,
        *,
        event: UserInputTranscribedEvent,
        transcript: str,
        word_count: int,
    ) -> bool:
        if self._last_ignored_at is None:
            return False
        if self._last_ignored_reason_code != "expired_before_stt":
            return False
        if word_count < self._policy.min_words:
            return False
        if (event.created_at - self._last_ignored_at) > 1.0:
            return False

        self._stats.late_transcripts_after_ignored += 1
        self._last_reason = "STT transcript arrived after candidate expiry"
        self._record_event(
            "late_transcript_after_ignored_candidate",
            created_at=event.created_at,
            reason=self._last_reason,
            agent_turn_id=self._last_ignored_candidate_turn_id,
            transcript=transcript,
            word_count=word_count,
            language=event.language,
            is_final=event.is_final,
        )
        self._last_ignored_at = None
        self._last_ignored_reason_code = None
        self._last_ignored_candidate_turn_id = None
        return True

    def _confirmation_delay(self, created_at: float) -> float | None:
        if self._candidate_started_at is None:
            return None
        return max(0.0, created_at - self._candidate_started_at)

    def _pending_delay(self, created_at: float) -> float | None:
        if self._candidate_ended_at is None:
            return None
        return max(0.0, created_at - self._candidate_ended_at)

    def _current_overtalk(self, created_at: float) -> float | None:
        if self._candidate_started_at is None:
            return None
        if self._candidate_muted_at is None:
            ended_at = self._candidate_agent_speaking_ended_at
            if ended_at is None and self._agent_state == "speaking":
                ended_at = created_at
            return None if ended_at is None else max(0.0, ended_at - self._candidate_started_at)
        if self._candidate_resumed_at is None:
            return 0.0
        ended_at = self._candidate_agent_speaking_ended_at
        if ended_at is None and self._agent_state == "speaking":
            ended_at = created_at
        return None if ended_at is None else max(0.0, ended_at - self._candidate_resumed_at)

    def _record_turn_decision(self, transcript: str, *, accepted: bool, reason: str) -> None:
        normalized = self._normalize_transcript(transcript)
        if normalized:
            self._turn_decisions.append((normalized, BargeTurnDecision(accepted, reason)))

    @staticmethod
    def _normalize_transcript(text: str) -> str:
        return " ".join(text.lower().split())

    def _record_event(
        self,
        event_type: str,
        *,
        created_at: float,
        reason: str,
        **extra: object,
    ) -> None:
        event: dict[str, object] = {
            "type": event_type,
            "callId": self._call_id,
            "created_at": created_at,
            "recorded_at": time.time(),
            "state": self._state,
            "reason": reason,
            "agent_state": self._agent_state,
            "user_state": self._user_state,
            "detected": self._stats.detected,
            "confirmed": self._stats.confirmed,
            "ignored": self._stats.ignored,
            "false_interruptions": self._stats.false_interruptions,
            "resumed_false_interruptions": self._stats.resumed_false_interruptions,
            "backchannel_confirmed": self._stats.backchannel_confirmed,
            "command_confirmed": self._stats.command_confirmed,
            "stt_language_mismatches": self._stats.stt_language_mismatches,
            "late_transcripts_after_ignored": self._stats.late_transcripts_after_ignored,
            "immediate_mute_attempts": self._stats.immediate_mute_attempts,
            "immediate_mute_successes": self._stats.immediate_mute_successes,
            "immediate_mute_failures": self._stats.immediate_mute_failures,
            "soft_pause_attempts": self._stats.soft_pause_attempts,
            "soft_pause_successes": self._stats.soft_pause_successes,
            "soft_pause_failures": self._stats.soft_pause_failures,
            "soft_resume_attempts": self._stats.soft_resume_attempts,
            "soft_resume_successes": self._stats.soft_resume_successes,
            "soft_resume_failures": self._stats.soft_resume_failures,
            "confirmed_cancel_attempts": self._stats.confirmed_cancel_attempts,
            "confirmed_cancel_successes": self._stats.confirmed_cancel_successes,
            "confirmed_cancel_failures": self._stats.confirmed_cancel_failures,
            "detected_turns": len(self._detected_turn_ids),
            "confirmed_turns": len(self._confirmed_turn_ids),
            "ignored_turns": len(self._ignored_turn_ids),
            "turns_without_interruption": self._stats.turns_without_interruption,
            **extra,
        }
        event["kpis"] = self._kpis_to_dict(self._build_kpis())
        if self._store is not None:
            self._store.add_barge_in_event(event)
        if self._policy.telemetry_path:
            path = Path(self._policy.telemetry_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
        if self._policy.sqlite_path:
            self._write_sqlite_event(event)

    def _write_sqlite_event(self, event: dict[str, object]) -> None:
        path = Path(self._policy.sqlite_path or "")
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS barge_in_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    type TEXT NOT NULL,
                    state TEXT,
                    agent_state TEXT,
                    user_state TEXT,
                    agent_turn_id INTEGER,
                    detected INTEGER,
                    confirmed INTEGER,
                    ignored INTEGER,
                    detected_turns INTEGER,
                    confirmed_turns INTEGER,
                    ignored_turns INTEGER,
                    confirmation_delay_seconds REAL,
                    pending_transcript_seconds REAL,
                    overtalk_seconds REAL,
                    immediate_mute_attempted INTEGER,
                    immediate_mute_success INTEGER,
                    immediate_mute_latency_seconds REAL,
                    immediate_mute_method TEXT,
                    transcript TEXT,
                    transcript_class TEXT,
                    language TEXT,
                    payload_json TEXT NOT NULL
                )
                """
            )
            existing_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(barge_in_events)")
            }
            for column_name, column_type in {
                "immediate_mute_attempted": "INTEGER",
                "immediate_mute_success": "INTEGER",
                "immediate_mute_latency_seconds": "REAL",
                "immediate_mute_method": "TEXT",
            }.items():
                if column_name not in existing_columns:
                    conn.execute(
                        f"ALTER TABLE barge_in_events ADD COLUMN {column_name} {column_type}"
                    )
            conn.execute(
                """
                INSERT INTO barge_in_events (
                    recorded_at,
                    created_at,
                    type,
                    state,
                    agent_state,
                    user_state,
                    agent_turn_id,
                    detected,
                    confirmed,
                    ignored,
                    detected_turns,
                    confirmed_turns,
                    ignored_turns,
                    confirmation_delay_seconds,
                    pending_transcript_seconds,
                    overtalk_seconds,
                    immediate_mute_attempted,
                    immediate_mute_success,
                    immediate_mute_latency_seconds,
                    immediate_mute_method,
                    transcript,
                    transcript_class,
                    language,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.get("recorded_at"),
                    event.get("created_at"),
                    event.get("type"),
                    event.get("state"),
                    event.get("agent_state"),
                    event.get("user_state"),
                    event.get("agent_turn_id"),
                    event.get("detected"),
                    event.get("confirmed"),
                    event.get("ignored"),
                    event.get("detected_turns"),
                    event.get("confirmed_turns"),
                    event.get("ignored_turns"),
                    event.get("confirmation_delay_seconds"),
                    event.get("pending_transcript_seconds"),
                    event.get("overtalk_seconds"),
                    event.get("immediate_mute_attempted"),
                    event.get("immediate_mute_success"),
                    event.get("immediate_mute_latency_seconds"),
                    event.get("immediate_mute_method"),
                    event.get("transcript"),
                    event.get("transcript_class"),
                    event.get("language"),
                    json.dumps(event, sort_keys=True),
                ),
            )

    def _publish(self) -> None:
        if self._store is None:
            return

        kpis = self._build_kpis()
        self._store.set_barge_in_state(
            {
                "enabled": self._policy.enabled,
                "state": self._state,
                "last_reason": self._last_reason,
                "agent_state": self._agent_state,
                "user_state": self._user_state,
                "detected": self._stats.detected,
                "confirmed": self._stats.confirmed,
                "ignored": self._stats.ignored,
                "false_interruptions": self._stats.false_interruptions,
                "resumed_false_interruptions": self._stats.resumed_false_interruptions,
                "backchannel_confirmed": self._stats.backchannel_confirmed,
                "command_confirmed": self._stats.command_confirmed,
                "stt_language_mismatches": self._stats.stt_language_mismatches,
                "late_transcripts_after_ignored": self._stats.late_transcripts_after_ignored,
                "immediate_mute_enabled": self._policy.immediate_mute_enabled,
                "native_interruption_enabled": self._policy.native_interruption_enabled,
                "soft_pause_enabled": self._policy.soft_pause_enabled,
                "immediate_mute_attempts": self._stats.immediate_mute_attempts,
                "immediate_mute_successes": self._stats.immediate_mute_successes,
                "immediate_mute_failures": self._stats.immediate_mute_failures,
                "soft_pause_attempts": self._stats.soft_pause_attempts,
                "soft_pause_successes": self._stats.soft_pause_successes,
                "soft_pause_failures": self._stats.soft_pause_failures,
                "soft_resume_attempts": self._stats.soft_resume_attempts,
                "soft_resume_successes": self._stats.soft_resume_successes,
                "soft_resume_failures": self._stats.soft_resume_failures,
                "confirmed_cancel_attempts": self._stats.confirmed_cancel_attempts,
                "confirmed_cancel_successes": self._stats.confirmed_cancel_successes,
                "confirmed_cancel_failures": self._stats.confirmed_cancel_failures,
                "detected_turns": len(self._detected_turn_ids),
                "confirmed_turns": len(self._confirmed_turn_ids),
                "ignored_turns": len(self._ignored_turn_ids),
                "turns_without_interruption": self._stats.turns_without_interruption,
                "turn_detection_mode": self._policy.turn_detection_mode or "auto",
                "endpointing_mode": self._policy.endpointing_mode,
                "interruption_mode": self._policy.interruption_mode,
                "min_speech_seconds": self._policy.min_speech_seconds,
                "min_words": self._policy.min_words,
                "confirmation_grace_seconds": self._policy.confirmation_grace_seconds,
                "telemetry_path": self._policy.telemetry_path,
                "sqlite_path": self._policy.sqlite_path,
                "kpis": self._kpis_to_dict(kpis),
            }
        )
        self._store.set_metric_panel(
            panel_id="barge_in",
            title="Barge-in Metrics",
            items=[
                {"label": "State", "value": self._state},
                {"label": "Detected", "value": str(self._stats.detected)},
                {"label": "Confirmed", "value": str(self._stats.confirmed)},
                {"label": "Ignored", "value": str(self._stats.ignored)},
                {"label": "Confirm Rate", "value": self._format_percent(kpis.confirmation_rate)},
                {"label": "Turn Confirm Rate", "value": self._format_percent(kpis.turn_confirmation_rate)},
                {"label": "Detected Turns", "value": str(kpis.detected_turns)},
                {"label": "Confirmed Turns", "value": str(kpis.confirmed_turns)},
                {"label": "False Candidate Rate", "value": self._format_percent(kpis.false_candidate_rate)},
                {"label": "Turn False Rate", "value": self._format_percent(kpis.turn_false_candidate_rate)},
                {"label": "Avg STT Confirm Delay", "value": self._format_seconds(kpis.average_confirmation_delay_seconds)},
                {"label": "Max STT Confirm Delay", "value": self._format_seconds(kpis.max_confirmation_delay_seconds)},
                {"label": "Avg Pending STT", "value": self._format_seconds(kpis.average_pending_transcript_seconds)},
                {"label": "Late STT After Expiry", "value": self._format_percent(kpis.late_transcript_after_ignored_rate)},
                {"label": "Avg Overtalk", "value": self._format_seconds(kpis.average_overtalk_seconds)},
                {"label": "Max Overtalk", "value": self._format_seconds(kpis.max_overtalk_seconds)},
                {"label": "Avg Mute Latency", "value": self._format_seconds(kpis.average_mute_latency_seconds)},
                {"label": "Soft Pause", "value": f"{self._stats.soft_pause_successes}/{self._stats.soft_pause_attempts}"},
                {"label": "Soft Resume", "value": f"{self._stats.soft_resume_successes}/{self._stats.soft_resume_attempts}"},
                {"label": "Confirmed Cancel", "value": f"{self._stats.confirmed_cancel_successes}/{self._stats.confirmed_cancel_attempts}"},
                {"label": "Avg Cancel Latency", "value": self._format_seconds(kpis.average_cancel_latency_seconds)},
                {"label": "Avg Recovery", "value": self._format_seconds(kpis.average_recovery_seconds)},
                {"label": "Backchannel Rate", "value": self._format_percent(kpis.backchannel_rate)},
                {"label": "Language Mismatch", "value": self._format_percent(kpis.language_mismatch_rate)},
                {"label": "False", "value": str(self._stats.false_interruptions)},
                {
                    "label": "Resumed False",
                    "value": str(self._stats.resumed_false_interruptions),
                },
                {
                    "label": "Min Speech",
                    "value": f"{self._policy.min_speech_seconds:.2f}s",
                },
                {"label": "Min Words", "value": str(self._policy.min_words)},
                {"label": "Grace", "value": f"{self._policy.confirmation_grace_seconds:.2f}s"},
                {"label": "Mute Attempts", "value": str(self._stats.immediate_mute_attempts)},
                {"label": "Mute Success", "value": str(self._stats.immediate_mute_successes)},
                {"label": "Mode", "value": self._policy.interruption_mode},
                {"label": "Endpoint", "value": self._policy.endpointing_mode},
                {"label": "Interrupted TTS", "value": "N/A"},
            ],
        )

    @staticmethod
    def _word_count(text: str) -> int:
        return len([word for word in text.split() if word.strip()])

    @staticmethod
    def _normalized_words(text: str) -> list[str]:
        return re.findall(r"[a-záéíóúüñ]+", text.lower())

    def _build_kpis(self) -> BargeInKpis:
        detected = self._stats.detected
        confirmed = self._stats.confirmed
        detected_turns = len(self._detected_turn_ids)
        confirmed_turns = len(self._confirmed_turn_ids)
        ignored_turns = len(self._ignored_turn_ids)
        return BargeInKpis(
            confirmation_rate=self._ratio(confirmed, detected),
            turn_confirmation_rate=self._ratio(confirmed_turns, detected_turns),
            false_candidate_rate=self._ratio(self._stats.ignored, detected),
            turn_false_candidate_rate=self._ratio(ignored_turns, detected_turns),
            ghost_interruption_rate=self._ratio(self._stats.ignored, detected),
            backchannel_rate=self._ratio(self._stats.backchannel_confirmed, confirmed),
            command_interruption_rate=self._ratio(self._stats.command_confirmed, confirmed),
            average_confirmation_delay_seconds=self._average(self._confirmation_delays),
            max_confirmation_delay_seconds=self._maximum(self._confirmation_delays),
            average_pending_transcript_seconds=self._average(self._pending_transcript_delays),
            max_pending_transcript_seconds=self._maximum(self._pending_transcript_delays),
            late_transcript_after_ignored_rate=self._ratio(
                self._stats.late_transcripts_after_ignored,
                self._stats.ignored,
            ),
            average_overtalk_seconds=self._average(self._overtalk_durations),
            max_overtalk_seconds=self._maximum(self._overtalk_durations),
            average_mute_latency_seconds=self._average(self._mute_latencies),
            max_mute_latency_seconds=self._maximum(self._mute_latencies),
            immediate_mute_success_rate=self._ratio(
                self._stats.immediate_mute_successes,
                self._stats.immediate_mute_attempts,
            ),
            average_cancel_latency_seconds=self._average(self._cancel_latencies),
            max_cancel_latency_seconds=self._maximum(self._cancel_latencies),
            average_recovery_seconds=self._average(self._recovery_durations),
            max_recovery_seconds=self._maximum(self._recovery_durations),
            language_mismatch_rate=self._ratio(self._stats.stt_language_mismatches, confirmed),
            detected_turns=detected_turns,
            confirmed_turns=confirmed_turns,
            ignored_turns=ignored_turns,
            turns_without_interruption=self._stats.turns_without_interruption,
            interrupted_tts_duration_seconds=None,
        )

    @staticmethod
    def _kpis_to_dict(kpis: BargeInKpis) -> dict[str, object]:
        return {
            "confirmation_rate": kpis.confirmation_rate,
            "turn_confirmation_rate": kpis.turn_confirmation_rate,
            "false_candidate_rate": kpis.false_candidate_rate,
            "turn_false_candidate_rate": kpis.turn_false_candidate_rate,
            "ghost_interruption_rate": kpis.ghost_interruption_rate,
            "backchannel_rate": kpis.backchannel_rate,
            "command_interruption_rate": kpis.command_interruption_rate,
            "average_confirmation_delay_seconds": kpis.average_confirmation_delay_seconds,
            "max_confirmation_delay_seconds": kpis.max_confirmation_delay_seconds,
            "average_pending_transcript_seconds": kpis.average_pending_transcript_seconds,
            "max_pending_transcript_seconds": kpis.max_pending_transcript_seconds,
            "late_transcript_after_ignored_rate": kpis.late_transcript_after_ignored_rate,
            "average_overtalk_seconds": kpis.average_overtalk_seconds,
            "max_overtalk_seconds": kpis.max_overtalk_seconds,
            "average_mute_latency_seconds": kpis.average_mute_latency_seconds,
            "max_mute_latency_seconds": kpis.max_mute_latency_seconds,
            "immediate_mute_success_rate": kpis.immediate_mute_success_rate,
            "average_cancel_latency_seconds": kpis.average_cancel_latency_seconds,
            "max_cancel_latency_seconds": kpis.max_cancel_latency_seconds,
            "average_recovery_seconds": kpis.average_recovery_seconds,
            "max_recovery_seconds": kpis.max_recovery_seconds,
            "language_mismatch_rate": kpis.language_mismatch_rate,
            "detected_turns": kpis.detected_turns,
            "confirmed_turns": kpis.confirmed_turns,
            "ignored_turns": kpis.ignored_turns,
            "turns_without_interruption": kpis.turns_without_interruption,
            "interrupted_tts_duration_seconds": kpis.interrupted_tts_duration_seconds,
        }

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return numerator / denominator

    @staticmethod
    def _average(values: list[float]) -> float | None:
        if not values:
            return None
        return sum(values) / len(values)

    @staticmethod
    def _maximum(values: list[float]) -> float | None:
        if not values:
            return None
        return max(values)

    @staticmethod
    def _format_percent(value: float) -> str:
        return f"{value * 100:.1f}%"

    @staticmethod
    def _format_seconds(value: float | None) -> str:
        if value is None:
            return "N/A"
        return f"{value:.3f}s"

    @staticmethod
    def _classify_transcript(text: str) -> str:
        normalized = re.sub(r"[^\wáéíóúüñ]+", " ", text.lower()).strip()
        words = [word for word in normalized.split() if word]
        if not words:
            return "unknown"
        backchannels = {
            "si",
            "sí",
            "vale",
            "ok",
            "okay",
            "aja",
            "ajá",
            "claro",
            "ya",
            "bien",
            "correcto",
            "entiendo",
        }
        if all(word in backchannels for word in words):
            return "backchannel"
        return "command"

    @staticmethod
    def _is_language_mismatch(text: str, language: str | None) -> bool:
        if not language:
            return False
        if language.lower().startswith("es"):
            return False
        lowered = text.lower()
        spanish_markers = {
            "que",
            "qué",
            "dime",
            "mira",
            "vale",
            "espera",
            "para",
            "factura",
            "llamada",
            "necesito",
            "escucha",
            "sí",
            "no",
        }
        has_spanish_marker = any(marker in lowered.split() for marker in spanish_markers)
        has_spanish_character = any(character in lowered for character in "áéíóúüñ¿¡")
        return has_spanish_marker or has_spanish_character
