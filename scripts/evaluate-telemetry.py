#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voice_agent.quality import (  # noqa: E402
    evaluate_telemetry,
    load_barge_in_events_from_sqlite,
    load_events_from_jsonl,
    load_voice_events_from_sqlite,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate local voice-agent telemetry quality.")
    parser.add_argument("--voice", default="logs/voice-metrics-telemetry.sqlite3")
    parser.add_argument("--barge-in", default="logs/barge-in-telemetry.sqlite3")
    parser.add_argument("--voice-after-id", type=int, default=0)
    parser.add_argument("--barge-after-id", type=int, default=0)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    voice_path = ROOT / args.voice
    barge_path = ROOT / args.barge_in
    voice_events = _load_events(voice_path, voice=True, after_id=args.voice_after_id)
    barge_events = _load_events(barge_path, voice=False, after_id=args.barge_after_id)
    report = evaluate_telemetry(voice_events=voice_events, barge_in_events=barge_events)

    if args.json:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        print(f"Telemetry quality: {report.status}")
        for component in report.components:
            print(f"- {component.name}: {component.status}")
            for reason in component.reasons:
                print(f"  {reason}")

    return 1 if report.status == "fail" else 0


def _load_events(path: Path, *, voice: bool, after_id: int = 0) -> list[dict[str, object]]:
    if not path.exists():
        return []
    if path.suffix == ".jsonl":
        events = load_events_from_jsonl(path)
        if after_id <= 0:
            return events
        return events[after_id:]
    if voice:
        return load_voice_events_from_sqlite(path, after_id=after_id)
    return load_barge_in_events_from_sqlite(path, after_id=after_id)


if __name__ == "__main__":
    raise SystemExit(main())
