from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from voice_agent.quality import (
    evaluate_telemetry,
    load_barge_in_events_from_sqlite,
    load_voice_events_from_sqlite,
)


class TelemetryQualityTests(unittest.TestCase):
    def test_good_run_passes_with_noisy_interim_transcripts(self) -> None:
        report = evaluate_telemetry(
            voice_events=_voice_events(),
            barge_in_events=_barge_events(),
        )

        self.assertEqual(report.status, "pass")
        transcript = _component(report, "transcript_stability")
        self.assertEqual(transcript.status, "pass")
        self.assertEqual(transcript.metrics["fragmented_final_transcripts"], 0)

    def test_genuinely_fragmented_final_transcripts_fail(self) -> None:
        voice_events = _voice_events(final_fragmented=True)

        report = evaluate_telemetry(
            voice_events=voice_events,
            barge_in_events=_barge_events(),
        )

        self.assertEqual(report.status, "fail")
        self.assertEqual(_component(report, "transcript_stability").status, "fail")

    def test_high_overtalk_fails(self) -> None:
        report = evaluate_telemetry(
            voice_events=_voice_events(),
            barge_in_events=_barge_events(overtalk=[0.2, 6.2, 0.3]),
        )

        self.assertEqual(report.status, "fail")
        self.assertEqual(_component(report, "overtalk").status, "fail")

    def test_tts_tail_latency_fails(self) -> None:
        voice_events = _voice_events(tts_ttfb=[0.7, 0.8, 6.7])

        report = evaluate_telemetry(
            voice_events=voice_events,
            barge_in_events=_barge_events(),
        )

        self.assertEqual(report.status, "fail")
        self.assertEqual(_component(report, "tts_latency").status, "fail")

    def test_false_candidate_spike_fails(self) -> None:
        report = evaluate_telemetry(
            voice_events=_voice_events(),
            barge_in_events=_barge_events(detected_turns=8, confirmed_turns=5, ignored_turns=3),
        )

        self.assertEqual(report.status, "fail")
        self.assertEqual(_component(report, "barge_in").status, "fail")

    def test_insufficient_data_is_explicit(self) -> None:
        report = evaluate_telemetry(voice_events=[], barge_in_events=[])

        self.assertEqual(report.status, "insufficient_data")
        self.assertTrue(all(component.status == "insufficient_data" for component in report.components))

    def test_loads_sqlite_telemetry_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            voice_path = Path(tmp_dir) / "voice.sqlite3"
            barge_path = Path(tmp_dir) / "barge.sqlite3"
            _write_payload_table(voice_path, "voice_metric_events", _voice_events())
            _write_payload_table(barge_path, "barge_in_events", _barge_events())

            report = evaluate_telemetry(
                voice_events=load_voice_events_from_sqlite(voice_path),
                barge_in_events=load_barge_in_events_from_sqlite(barge_path),
            )

        self.assertEqual(report.status, "pass")

    def test_loads_sqlite_telemetry_payloads_after_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            voice_path = Path(tmp_dir) / "voice.sqlite3"
            barge_path = Path(tmp_dir) / "barge.sqlite3"
            stale_voice_events = _voice_events(final_fragmented=True)
            stale_barge_events = _barge_events(detected_turns=8, confirmed_turns=5, ignored_turns=3)
            _write_payload_table(voice_path, "voice_metric_events", stale_voice_events + _voice_events())
            _write_payload_table(barge_path, "barge_in_events", stale_barge_events + _barge_events())

            report = evaluate_telemetry(
                voice_events=load_voice_events_from_sqlite(
                    voice_path,
                    after_id=len(stale_voice_events),
                ),
                barge_in_events=load_barge_in_events_from_sqlite(
                    barge_path,
                    after_id=len(stale_barge_events),
                ),
            )

        self.assertEqual(report.status, "pass")


def _component(report, name: str):
    for component in report.components:
        if component.name == name:
            return component
    raise AssertionError(f"Missing component {name}")


def _voice_events(
    *,
    final_fragmented: bool = False,
    tts_ttfb: list[float] | None = None,
) -> list[dict[str, object]]:
    tts_values = tts_ttfb or [0.7, 0.9, 1.0]
    events: list[dict[str, object]] = []
    events.extend(
        {"type": "llm_metrics", "ttft_seconds": value}
        for value in [0.8, 1.0, 1.2]
    )
    events.extend(
        {"type": "tts_metrics", "ttfb_seconds": value}
        for value in tts_values
    )
    for index in range(6):
        events.append(
            {
                "type": "user_transcript",
                "transcript": "No",
                "is_final": False,
                "word_count": 1,
                "stt_fragmented_turn": True,
                "stt_rapid_partial_update": False,
            }
        )
        events.append(
            {
                "type": "user_transcript",
                "transcript": "No me parece mala oferta",
                "is_final": True,
                "word_count": 5,
                "stt_fragmented_turn": final_fragmented,
                "stt_rapid_partial_update": True,
            }
        )
    return events


def _barge_events(
    *,
    detected_turns: int = 6,
    confirmed_turns: int = 6,
    ignored_turns: int = 0,
    overtalk: list[float] | None = None,
) -> list[dict[str, object]]:
    overtalk_values = overtalk or [0.0, 0.2, 0.3]
    events: list[dict[str, object]] = []
    for value in overtalk_values:
        events.append(
            {
                "type": "candidate_confirmed",
                "detected_turns": detected_turns,
                "confirmed_turns": confirmed_turns,
                "ignored_turns": ignored_turns,
                "overtalk_seconds": value,
                "immediate_mute_attempted": True,
                "immediate_mute_success": True,
            }
        )
    events.append(
        {
            "type": "turn_without_interruption",
            "detected_turns": detected_turns,
            "confirmed_turns": confirmed_turns,
            "ignored_turns": ignored_turns,
        }
    )
    return events


def _write_payload_table(path: Path, table: str, events: list[dict[str, object]]) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            f"""
            CREATE TABLE {table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.executemany(
            f"INSERT INTO {table} (payload_json) VALUES (?)",
            [(json.dumps(event, sort_keys=True),) for event in events],
        )
