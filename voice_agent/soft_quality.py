"""Optional LLM judging for non-compliance qualities only."""

from __future__ import annotations

import json
from typing import Any, Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field


class SoftQualityJudgment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clarity: Literal["pass", "warn", "fail"]
    tone: Literal["pass", "warn", "fail"]
    concision: Literal["pass", "warn", "fail"]
    notes: list[str] = Field(default_factory=list, max_length=5)

    @property
    def status(self) -> str:
        values = {self.clarity, self.tone, self.concision}
        if "fail" in values:
            return "fail"
        if "warn" in values:
            return "warn"
        return "pass"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "clarity": self.clarity,
            "tone": self.tone,
            "concision": self.concision,
            "notes": list(self.notes),
        }


SOFT_JUDGE_INSTRUCTIONS = """Evaluate only clarity, respectful professional tone, and
concision of the assistant responses in this outbound contact-center trace. Do not judge
privacy, legal compliance, state transitions, termination behavior, or factual correctness;
those are checked deterministically. A response is concise when it normally uses one or two
short sentences and at most one concrete question. Return brief notes without quoting personal
data from the trace.
"""


async def judge_soft_quality(
    events: list[dict[str, Any]],
    *,
    api_key: str,
    model: str,
    client: Any | None = None,
) -> SoftQualityJudgment:
    transitions = {
        str(event.get("turnId")): event
        for event in events
        if event.get("type") == "fsm_transition"
    }
    turns = []
    for event in events:
        if event.get("type") != "assistant_response":
            continue
        turn_id = str(event.get("turnId"))
        transition = transitions.get(turn_id, {})
        turns.append(
            {
                "turnId": turn_id,
                "directive": transition.get("directive"),
                "userTranscript": transition.get("userTranscript"),
                "assistantText": event.get("assistantText"),
            }
        )
    if not turns:
        raise ValueError("No correlated assistant turns are available for soft judging")
    openai_client = client or AsyncOpenAI(api_key=api_key)
    response = await openai_client.responses.parse(
        model=model,
        instructions=SOFT_JUDGE_INSTRUCTIONS,
        input=json.dumps({"turns": turns[:30]}, ensure_ascii=False),
        text_format=SoftQualityJudgment,
        max_output_tokens=250,
        temperature=0,
        store=False,
    )
    if response.output_parsed is None:
        raise ValueError("Soft-quality judge returned no structured output")
    return response.output_parsed
