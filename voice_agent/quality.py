"""Telemetry quality evaluation for local voice-agent runs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
import json
from pathlib import Path
import sqlite3
from typing import Any


STATUSES = ("insufficient_data", "pass", "warn", "fail")


@dataclass(frozen=True)
class QualityThresholds:
    min_barge_in_turns: int = 3
    min_final_transcripts: int = 5
    turn_confirmation_pass: float = 0.90
    turn_confirmation_warn: float = 0.75
    false_candidate_pass: float = 0.10
    false_candidate_warn: float = 0.25
    immediate_mute_pass: float = 0.95
    immediate_mute_warn: float = 0.85
    average_overtalk_pass_seconds: float = 0.50
    average_overtalk_warn_seconds: float = 1.00
    max_overtalk_pass_seconds: float = 2.00
    max_overtalk_warn_seconds: float = 5.00
    llm_average_ttft_pass_seconds: float = 1.50
    llm_average_ttft_warn_seconds: float = 2.50
    llm_max_ttft_pass_seconds: float = 3.00
    llm_max_ttft_warn_seconds: float = 5.00
    tts_average_ttfb_pass_seconds: float = 1.50
    tts_average_ttfb_warn_seconds: float = 2.50
    tts_max_ttfb_pass_seconds: float = 3.00
    tts_max_ttfb_warn_seconds: float = 6.00
    final_fragmented_pass: float = 0.10
    final_fragmented_warn: float = 0.25

    @classmethod
    def for_profile(cls, profile: str) -> "QualityThresholds":
        if profile == "lab":
            return cls()
        if profile == "production":
            return cls(
                min_barge_in_turns=6,
                min_final_transcripts=7,
                turn_confirmation_pass=0.95,
                turn_confirmation_warn=0.90,
                false_candidate_pass=0.05,
                false_candidate_warn=0.10,
                immediate_mute_pass=0.98,
                immediate_mute_warn=0.95,
                average_overtalk_pass_seconds=0.25,
                average_overtalk_warn_seconds=0.50,
                max_overtalk_pass_seconds=1.00,
                max_overtalk_warn_seconds=2.00,
                llm_average_ttft_pass_seconds=0.90,
                llm_average_ttft_warn_seconds=1.50,
                llm_max_ttft_pass_seconds=2.00,
                llm_max_ttft_warn_seconds=3.00,
                tts_average_ttfb_pass_seconds=0.90,
                tts_average_ttfb_warn_seconds=1.50,
                tts_max_ttfb_pass_seconds=2.00,
                tts_max_ttfb_warn_seconds=3.00,
                final_fragmented_pass=0.05,
                final_fragmented_warn=0.10,
            )
        raise ValueError(f"Unknown quality threshold profile: {profile}")


@dataclass(frozen=True)
class QualityComponent:
    name: str
    status: str
    metrics: dict[str, float | int | None] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class QualityReport:
    status: str
    components: tuple[QualityComponent, ...]

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(reason for component in self.components for reason in component.reasons)

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "components": [
                {
                    "name": component.name,
                    "status": component.status,
                    "metrics": component.metrics,
                    "reasons": list(component.reasons),
                }
                for component in self.components
            ],
            "reasons": list(self.reasons),
        }


def evaluate_telemetry(
    *,
    voice_events: Iterable[dict[str, Any]] = (),
    barge_in_events: Iterable[dict[str, Any]] = (),
    thresholds: QualityThresholds | None = None,
) -> QualityReport:
    thresholds = thresholds or QualityThresholds()
    voice_event_list = list(voice_events)
    barge_event_list = list(barge_in_events)
    components = (
        _evaluate_barge_in(barge_event_list, thresholds),
        _evaluate_immediate_mute(barge_event_list, thresholds),
        _evaluate_overtalk(barge_event_list, thresholds),
        _evaluate_llm_latency(voice_event_list, thresholds),
        _evaluate_tts_latency(voice_event_list, thresholds),
        _evaluate_transcript_stability(voice_event_list, thresholds),
    )
    return QualityReport(status=_overall_status(components), components=components)


def load_voice_events_from_sqlite(path: str | Path, *, after_id: int = 0) -> list[dict[str, Any]]:
    return _load_payloads_from_sqlite(path, "voice_metric_events", after_id=after_id)


def load_barge_in_events_from_sqlite(path: str | Path, *, after_id: int = 0) -> list[dict[str, Any]]:
    return _load_payloads_from_sqlite(path, "barge_in_events", after_id=after_id)


def load_events_from_jsonl(path: str | Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            events.append(json.loads(stripped))
    return events


def _load_payloads_from_sqlite(
    path: str | Path,
    table: str,
    *,
    after_id: int = 0,
) -> list[dict[str, Any]]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            f"SELECT payload_json FROM {table} WHERE id > ? ORDER BY id",
            (after_id,),
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def _evaluate_barge_in(
    events: list[dict[str, Any]],
    thresholds: QualityThresholds,
) -> QualityComponent:
    snapshot = _latest_barge_snapshot(events)
    detected_turns = _to_int(snapshot.get("detected_turns"))
    confirmed_turns = _to_int(snapshot.get("confirmed_turns"))
    ignored_turns = _to_int(snapshot.get("ignored_turns"))
    if detected_turns < thresholds.min_barge_in_turns:
        return QualityComponent(
            "barge_in",
            "insufficient_data",
            {
                "detected_turns": detected_turns,
                "confirmed_turns": confirmed_turns,
                "ignored_turns": ignored_turns,
            },
            (f"Need at least {thresholds.min_barge_in_turns} detected turns.",),
        )

    confirmation_rate = _ratio(confirmed_turns, detected_turns)
    false_rate = _ratio(ignored_turns, detected_turns)
    confirmation_status = _min_status(
        confirmation_rate,
        pass_at=thresholds.turn_confirmation_pass,
        warn_at=thresholds.turn_confirmation_warn,
    )
    false_status = _max_status(
        false_rate,
        pass_at=thresholds.false_candidate_pass,
        warn_at=thresholds.false_candidate_warn,
    )
    status = _worst_status((confirmation_status, false_status))
    reasons: list[str] = []
    if confirmation_status != "pass":
        reasons.append(f"Turn confirmation rate is {confirmation_rate:.1%}.")
    if false_status != "pass":
        reasons.append(f"Turn false-candidate rate is {false_rate:.1%}.")

    return QualityComponent(
        "barge_in",
        status,
        {
            "detected_turns": detected_turns,
            "confirmed_turns": confirmed_turns,
            "ignored_turns": ignored_turns,
            "turn_confirmation_rate": confirmation_rate,
            "turn_false_candidate_rate": false_rate,
        },
        tuple(reasons),
    )


def _evaluate_immediate_mute(
    events: list[dict[str, Any]],
    thresholds: QualityThresholds,
) -> QualityComponent:
    attempts = [
        event for event in events
        if event.get("immediate_mute_attempted") is not None
    ]
    if not attempts:
        return QualityComponent(
            "immediate_mute",
            "insufficient_data",
            {"attempts": 0, "success_rate": None},
            ("No immediate mute attempts were recorded.",),
        )

    successes = sum(1 for event in attempts if bool(event.get("immediate_mute_success")))
    success_rate = _ratio(successes, len(attempts))
    status = _min_status(
        success_rate,
        pass_at=thresholds.immediate_mute_pass,
        warn_at=thresholds.immediate_mute_warn,
    )
    reasons = () if status == "pass" else (f"Immediate mute success rate is {success_rate:.1%}.",)
    return QualityComponent(
        "immediate_mute",
        status,
        {"attempts": len(attempts), "successes": successes, "success_rate": success_rate},
        reasons,
    )


def _evaluate_overtalk(
    events: list[dict[str, Any]],
    thresholds: QualityThresholds,
) -> QualityComponent:
    values = [_to_float(event.get("overtalk_seconds")) for event in events]
    values = [value for value in values if value is not None]
    if not values:
        return QualityComponent(
            "overtalk",
            "insufficient_data",
            {"average_overtalk_seconds": None, "max_overtalk_seconds": None},
            ("No overtalk measurements were recorded.",),
        )

    average = sum(values) / len(values)
    maximum = max(values)
    average_status = _max_status(
        average,
        pass_at=thresholds.average_overtalk_pass_seconds,
        warn_at=thresholds.average_overtalk_warn_seconds,
    )
    max_status = _max_status(
        maximum,
        pass_at=thresholds.max_overtalk_pass_seconds,
        warn_at=thresholds.max_overtalk_warn_seconds,
    )
    status = _worst_status((average_status, max_status))
    reasons: list[str] = []
    if average_status != "pass":
        reasons.append(f"Average overtalk is {average:.3f}s.")
    if max_status != "pass":
        reasons.append(f"Max overtalk is {maximum:.3f}s.")
    return QualityComponent(
        "overtalk",
        status,
        {"average_overtalk_seconds": average, "max_overtalk_seconds": maximum},
        tuple(reasons),
    )


def _evaluate_llm_latency(
    events: list[dict[str, Any]],
    thresholds: QualityThresholds,
) -> QualityComponent:
    values = [
        _to_float(event.get("ttft_seconds"))
        for event in events
        if event.get("type") == "llm_metrics"
    ]
    values = [value for value in values if value is not None]
    return _evaluate_latency(
        "llm_latency",
        values,
        average_pass=thresholds.llm_average_ttft_pass_seconds,
        average_warn=thresholds.llm_average_ttft_warn_seconds,
        max_pass=thresholds.llm_max_ttft_pass_seconds,
        max_warn=thresholds.llm_max_ttft_warn_seconds,
        metric_name="TTFT",
    )


def _evaluate_tts_latency(
    events: list[dict[str, Any]],
    thresholds: QualityThresholds,
) -> QualityComponent:
    values = [
        _to_float(event.get("ttfb_seconds"))
        for event in events
        if event.get("type") == "tts_metrics"
    ]
    values = [value for value in values if value is not None]
    return _evaluate_latency(
        "tts_latency",
        values,
        average_pass=thresholds.tts_average_ttfb_pass_seconds,
        average_warn=thresholds.tts_average_ttfb_warn_seconds,
        max_pass=thresholds.tts_max_ttfb_pass_seconds,
        max_warn=thresholds.tts_max_ttfb_warn_seconds,
        metric_name="TTFB",
    )


def _evaluate_transcript_stability(
    events: list[dict[str, Any]],
    thresholds: QualityThresholds,
) -> QualityComponent:
    finals = [
        event for event in events
        if event.get("type") == "user_transcript" and bool(event.get("is_final"))
    ]
    if len(finals) < thresholds.min_final_transcripts:
        return QualityComponent(
            "transcript_stability",
            "insufficient_data",
            {"final_transcripts": len(finals), "fragmented_rate": None},
            (f"Need at least {thresholds.min_final_transcripts} final transcripts.",),
        )

    fragmented = sum(1 for event in finals if bool(event.get("stt_fragmented_turn")))
    fragmented_rate = _ratio(fragmented, len(finals))
    status = _max_status(
        fragmented_rate,
        pass_at=thresholds.final_fragmented_pass,
        warn_at=thresholds.final_fragmented_warn,
    )
    reasons = () if status == "pass" else (f"Final transcript fragmented rate is {fragmented_rate:.1%}.",)
    return QualityComponent(
        "transcript_stability",
        status,
        {
            "final_transcripts": len(finals),
            "fragmented_final_transcripts": fragmented,
            "fragmented_rate": fragmented_rate,
        },
        reasons,
    )


def _evaluate_latency(
    name: str,
    values: list[float],
    *,
    average_pass: float,
    average_warn: float,
    max_pass: float,
    max_warn: float,
    metric_name: str,
) -> QualityComponent:
    if not values:
        return QualityComponent(
            name,
            "insufficient_data",
            {"average_seconds": None, "max_seconds": None},
            (f"No {metric_name} measurements were recorded.",),
        )

    average = sum(values) / len(values)
    maximum = max(values)
    average_status = _max_status(average, pass_at=average_pass, warn_at=average_warn)
    max_status = _max_status(maximum, pass_at=max_pass, warn_at=max_warn)
    status = _worst_status((average_status, max_status))
    reasons: list[str] = []
    if average_status != "pass":
        reasons.append(f"Average {metric_name} is {average:.3f}s.")
    if max_status != "pass":
        reasons.append(f"Max {metric_name} is {maximum:.3f}s.")
    return QualityComponent(
        name,
        status,
        {"average_seconds": average, "max_seconds": maximum, "measurements": len(values)},
        tuple(reasons),
    )


def _latest_barge_snapshot(events: list[dict[str, Any]]) -> dict[str, Any]:
    snapshots = [
        event for event in events
        if event.get("detected_turns") is not None
    ]
    return snapshots[-1] if snapshots else {}


def _overall_status(components: Iterable[QualityComponent]) -> str:
    statuses = [component.status for component in components]
    if any(status == "fail" for status in statuses):
        return "fail"
    if any(status == "warn" for status in statuses):
        return "warn"
    if statuses and all(status == "insufficient_data" for status in statuses):
        return "insufficient_data"
    return "pass"


def _worst_status(statuses: Iterable[str]) -> str:
    order = {"insufficient_data": 0, "pass": 1, "warn": 2, "fail": 3}
    return max(statuses, key=lambda status: order[status])


def _min_status(value: float, *, pass_at: float, warn_at: float) -> str:
    if value >= pass_at:
        return "pass"
    if value >= warn_at:
        return "warn"
    return "fail"


def _max_status(value: float, *, pass_at: float, warn_at: float) -> str:
    if value <= pass_at:
        return "pass"
    if value <= warn_at:
        return "warn"
    return "fail"


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _to_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
