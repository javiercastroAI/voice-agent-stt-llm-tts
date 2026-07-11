#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voice_agent.audio_adherence import combine_audio_evidence  # noqa: E402
from voice_agent.case_context import load_case_context  # noqa: E402
from voice_agent.fsm_adherence import evaluate_trace, load_jsonl_events  # noqa: E402
from voice_agent.quality import (  # noqa: E402
    QualityThresholds,
    evaluate_telemetry,
    load_barge_in_events_from_sqlite,
    load_events_from_jsonl,
    load_voice_events_from_sqlite,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Combine real-audio telemetry with deterministic FSM adherence."
    )
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument(
        "--audio-scenarios",
        default="specs/scenarios/fsm-audio-adherence.json",
    )
    parser.add_argument(
        "--case",
        default="examples/collections/al-corriente.case.json",
    )
    parser.add_argument("--trace", default="logs/fsm-adherence.jsonl")
    parser.add_argument("--voice", default="logs/voice-metrics-telemetry.sqlite3")
    parser.add_argument("--barge-in", default="logs/barge-in-telemetry.sqlite3")
    parser.add_argument("--voice-after-id", type=int, default=0)
    parser.add_argument("--barge-after-id", type=int, default=0)
    parser.add_argument(
        "--manual-verdict",
        choices=("pass", "warn", "fail", "unknown"),
        default="unknown",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    audio_pack = json.loads((ROOT / args.audio_scenarios).read_text(encoding="utf-8"))
    scenario_ids = {item.get("id") for item in audio_pack.get("scenarios", [])}
    if args.scenario_id not in scenario_ids:
        raise SystemExit(f"Unknown audio scenario: {args.scenario_id}")

    case = load_case_context(ROOT / args.case)
    adherence = evaluate_trace(load_jsonl_events(ROOT / args.trace), case=case)
    voice_events = _load_events(ROOT / args.voice, voice=True, after_id=args.voice_after_id)
    barge_events = _load_events(
        ROOT / args.barge_in,
        voice=False,
        after_id=args.barge_after_id,
    )
    quality = evaluate_telemetry(
        voice_events=voice_events,
        barge_in_events=barge_events,
        thresholds=QualityThresholds.for_profile("production"),
    )
    report = combine_audio_evidence(
        scenario_id=args.scenario_id,
        adherence=adherence,
        voice_quality=quality,
        manual_verdict=args.manual_verdict,
    )
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        print(f"Real-audio FSM evidence: {report.status}")
        print(f"- scenario: {report.scenario_id}")
        print(f"- FSM adherence: {adherence.status}")
        print(f"- voice quality: {quality.status}")
        print(f"- manual verdict: {args.manual_verdict}")
    return 1 if report.status == "fail" else 0


def _load_events(path: Path, *, voice: bool, after_id: int):
    if not path.exists():
        return []
    if path.suffix == ".jsonl":
        events = load_events_from_jsonl(path)
        return events[after_id:] if after_id > 0 else events
    if voice:
        return load_voice_events_from_sqlite(path, after_id=after_id)
    return load_barge_in_events_from_sqlite(path, after_id=after_id)


if __name__ == "__main__":
    raise SystemExit(main())
