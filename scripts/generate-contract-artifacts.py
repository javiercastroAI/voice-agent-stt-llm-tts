#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parent.parent
schema_path = root / "contracts" / "interface.schema.json"
output_path = root / "shared" / "generated" / "interface_contract.py"
check_mode = "--check" in sys.argv

schema = json.loads(schema_path.read_text(encoding="utf-8"))
required = schema.get("required", ["type", "payload"])

generated = f"""# This file is generated from contracts/interface.schema.json.
# Do not edit it manually. Run `python3 scripts/generate-contract-artifacts.py` after changing the schema.

from __future__ import annotations

from typing import Any, Dict, TypedDict
import json

INTERFACE_CONTRACT_SCHEMA = {json.dumps(schema, indent=2)}
REQUIRED_KEYS = {json.dumps(required)}


class InterfaceEnvelope(TypedDict):
    type: str
    payload: Dict[str, Any]


def is_interface_envelope(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return (
        all(key in value for key in REQUIRED_KEYS)
        and isinstance(value.get("type"), str)
        and isinstance(value.get("payload"), dict)
    )


def parse_interface_envelope(raw: str) -> InterfaceEnvelope | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if is_interface_envelope(payload) else None
"""

output_path.parent.mkdir(parents=True, exist_ok=True)
current = output_path.read_text(encoding="utf-8") if output_path.exists() else None

if check_mode:
    if current != generated:
        raise SystemExit("shared/generated/interface_contract.py is out of date. Run python3 scripts/generate-contract-artifacts.py.")
else:
    if current != generated:
        output_path.write_text(generated, encoding="utf-8")
        print("Updated shared/generated/interface_contract.py")

