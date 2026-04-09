# This file is generated from contracts/interface.schema.json.
# Do not edit it manually. Run `python3 scripts/generate-contract-artifacts.py` after changing the schema.

from __future__ import annotations

from typing import Any, Dict, TypedDict
import json

INTERFACE_CONTRACT_SCHEMA = {
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.local/voice-agents-stt-llm-tts-spec-driven/contracts/interface.schema.json",
  "title": "Voice agents STT-LLM-TTS (Spec driven) Interface Contract",
  "description": "Replace this baseline schema with the real cross-domain contract. Keep a top-level type + payload envelope unless you intentionally redesign the generator.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "type",
    "payload"
  ],
  "properties": {
    "type": {
      "type": "string",
      "description": "Replace with a domain-specific event, command, or message type."
    },
    "payload": {
      "type": "object",
      "description": "Replace with the real payload contract."
    }
  }
}
REQUIRED_KEYS = ["type", "payload"]


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
