#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voice_agent.case_context import load_case_context  # noqa: E402
from voice_agent.config import AgentConfig  # noqa: E402
from voice_agent.fsm_adherence import (  # noqa: E402
    evaluate_scenario_pack,
    evaluate_trace,
    load_jsonl_events,
)
from voice_agent.soft_quality import judge_soft_quality  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay FSM scenarios and evaluate runtime adherence evidence."
    )
    parser.add_argument(
        "--case",
        default="examples/collections/al-corriente.case.json",
    )
    parser.add_argument(
        "--scenarios",
        default="specs/scenarios/fsm-adherence.json",
    )
    parser.add_argument("--trace", default=None)
    parser.add_argument("--scenario-only", action="store_true")
    parser.add_argument("--llm-judge", action="store_true")
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    case = load_case_context(ROOT / args.case)
    scenario_pack = json.loads((ROOT / args.scenarios).read_text(encoding="utf-8"))
    scenario_report = evaluate_scenario_pack(scenario_pack, case=case)
    output: dict[str, object] = {"scenarios": scenario_report.as_dict()}
    deterministic_statuses = [scenario_report.status]
    trace_events: list[dict[str, object]] = []

    if not args.scenario_only and args.trace:
        trace_events = load_jsonl_events(ROOT / args.trace)
        trace_report = evaluate_trace(trace_events, case=case)
        output["trace"] = trace_report.as_dict()
        deterministic_statuses.append(trace_report.status)
    elif not args.scenario_only:
        output["trace"] = {"status": "not_run", "reason": "No --trace supplied."}

    output["complianceStatus"] = (
        "fail" if "fail" in deterministic_statuses else (
            "warn" if "warn" in deterministic_statuses else "pass"
        )
    )

    if args.llm_judge:
        if not trace_events:
            raise SystemExit("--llm-judge requires a non-empty --trace")
        config = AgentConfig.from_env(load_dotenv_file=True)
        judgment = asyncio.run(
            judge_soft_quality(
                trace_events,
                api_key=config.openai_api_key or "",
                model=args.judge_model or config.openai_intent_model,
            )
        )
        output["softQuality"] = judgment.as_dict()

    if args.json:
        print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"FSM compliance: {output['complianceStatus']}")
        print(f"- scripted scenarios: {scenario_report.status}")
        if "trace" in output:
            print(f"- runtime trace: {output['trace']['status']}")
        if "softQuality" in output:
            print(f"- optional soft quality: {output['softQuality']['status']}")
    return 1 if output["complianceStatus"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
