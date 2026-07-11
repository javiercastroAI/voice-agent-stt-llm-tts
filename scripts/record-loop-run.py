#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voice_agent.quality import (  # noqa: E402
    QualityThresholds,
    evaluate_telemetry,
    load_barge_in_events_from_sqlite,
    load_events_from_jsonl,
    load_voice_events_from_sqlite,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record one manual production-readiness loop run after a call ends."
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--operator", default="manual-tester")
    parser.add_argument(
        "--scenario-pack",
        default="specs/scenarios/production-readiness.json",
    )
    parser.add_argument("--voice", default="logs/voice-metrics-telemetry.sqlite3")
    parser.add_argument("--barge-in", default="logs/barge-in-telemetry.sqlite3")
    parser.add_argument("--voice-after-id", type=int, default=0)
    parser.add_argument("--barge-after-id", type=int, default=0)
    parser.add_argument(
        "--profile",
        choices=("lab", "production"),
        default="production",
    )
    parser.add_argument(
        "--manual-verdict",
        choices=("pass", "warn", "fail", "unknown"),
        default="unknown",
    )
    parser.add_argument("--notes", default="")
    parser.add_argument("--output-dir", default="logs/loop-runs")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    run_id = args.run_id or _default_run_id()
    scenario_pack_path = ROOT / args.scenario_pack
    voice_path = ROOT / args.voice
    barge_path = ROOT / args.barge_in
    scenario_pack = _read_json(scenario_pack_path)
    voice_events = _load_events(voice_path, voice=True, after_id=args.voice_after_id)
    barge_events = _load_events(barge_path, voice=False, after_id=args.barge_after_id)
    report = evaluate_telemetry(
        voice_events=voice_events,
        barge_in_events=barge_events,
        thresholds=QualityThresholds.for_profile(args.profile),
    )

    record = {
        "runId": run_id,
        "recordedAt": datetime.now(timezone.utc).isoformat(),
        "operator": args.operator,
        "qualityProfile": args.profile,
        "manualVerdict": args.manual_verdict,
        "manualNotes": args.notes,
        "commit": _git_output("rev-parse", "HEAD"),
        "workingTreeStatus": _git_output("status", "--short"),
        "configHash": _file_sha256(ROOT / ".env"),
        "scenarioPack": {
            "path": args.scenario_pack,
            "id": scenario_pack.get("id"),
            "version": scenario_pack.get("version"),
            "scenarioIds": [
                scenario.get("id")
                for scenario in scenario_pack.get("scenarios", [])
            ],
        },
        "telemetry": {
            "voicePath": args.voice,
            "bargeInPath": args.barge_in,
            "voiceAfterId": args.voice_after_id,
            "bargeAfterId": args.barge_after_id,
            "voiceEndId": _max_sqlite_id(voice_path, "voice_metric_events"),
            "bargeEndId": _max_sqlite_id(barge_path, "barge_in_events"),
            "voiceEventsEvaluated": len(voice_events),
            "bargeInEventsEvaluated": len(barge_events),
        },
        "qualityReport": report.as_dict(),
        "readyForProduction": (
            report.status == "pass" and args.manual_verdict == "pass"
        ),
    }

    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{run_id}.json"
    output_path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")

    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
    else:
        print(f"Loop run recorded: {output_path.relative_to(ROOT)}")
        print(f"Telemetry quality ({args.profile}): {report.status}")
        print(f"Manual verdict: {args.manual_verdict}")
        print(f"Ready for production: {record['readyForProduction']}")
        if report.reasons:
            print("Reasons:")
            for reason in report.reasons:
                print(f"- {reason}")

    return 0 if report.status != "fail" else 1


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Scenario pack not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_events(path: Path, *, voice: bool, after_id: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.suffix == ".jsonl":
        events = load_events_from_jsonl(path)
        return events[after_id:] if after_id > 0 else events
    if voice:
        return load_voice_events_from_sqlite(path, after_id=after_id)
    return load_barge_in_events_from_sqlite(path, after_id=after_id)


def _max_sqlite_id(path: Path, table: str) -> int | None:
    if not path.exists() or path.suffix != ".sqlite3":
        return None
    with sqlite3.connect(path) as conn:
        row = conn.execute(f"SELECT MAX(id) FROM {table}").fetchone()
    value = row[0] if row else None
    return int(value) if value is not None else 0


def _file_sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_output(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
