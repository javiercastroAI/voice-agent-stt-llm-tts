#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from voice_agent.conversation_fsm import render_business_graph


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs/generated/fsm-business-graph.md"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the business FSM graph from the executable registry."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the committed graph differs from the generated graph.",
    )
    args = parser.parse_args()
    rendered = render_business_graph()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print(f"{OUTPUT.relative_to(ROOT)} is stale; regenerate it.")
            return 1
        print("Generated FSM business graph is current.")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
