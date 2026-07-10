"""Durable, case-minimized evidence for FSM transition adherence."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .conversation_fsm import ConversationState, TurnEvent

EventWriter = Callable[[dict[str, Any]], object]


class FSMTraceRecorder:
    """Correlate each FSM decision with the next assistant message."""

    def __init__(
        self,
        *,
        jsonl_path: str | None = None,
        event_writer: EventWriter | None = None,
        call_id: str | None = None,
        id_factory: Callable[[], str] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._jsonl_path = jsonl_path
        self._event_writer = event_writer
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._call_id = call_id or f"call-{self._id_factory()}"
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._pending_turn_ids: deque[str] = deque()
        self._seen_conversation_item_ids: set[str] = set()
        self.events: list[dict[str, Any]] = []

    def record_opening(self, state: ConversationState) -> str:
        return self._record_transition(
            user_transcript="",
            event=state["event"],
            state=state,
        )

    def record_transition(
        self,
        *,
        user_transcript: str,
        event: TurnEvent,
        state: ConversationState,
    ) -> str:
        return self._record_transition(
            user_transcript=user_transcript.strip(),
            event=event,
            state=state,
        )

    def record_conversation_item(self, event: object) -> str | None:
        item = getattr(event, "item", None)
        if getattr(item, "type", None) != "message":
            return None
        if getattr(item, "role", None) != "assistant":
            return None
        item_id = str(getattr(item, "id", "") or "")
        if item_id and item_id in self._seen_conversation_item_ids:
            return None
        text = str(getattr(item, "text_content", "") or "").strip()
        if not text:
            return None
        if item_id:
            self._seen_conversation_item_ids.add(item_id)
        return self.record_assistant_response(text, conversation_item_id=item_id or None)

    def record_assistant_response(
        self,
        text: str,
        *,
        conversation_item_id: str | None = None,
    ) -> str:
        turn_id = (
            self._pending_turn_ids.popleft()
            if self._pending_turn_ids
            else f"orphan-{self._id_factory()}"
        )
        self._write(
            {
                "version": 1,
                "type": "assistant_response",
                "callId": self._call_id,
                "turnId": turn_id,
                "recordedAt": self._timestamp(),
                "assistantText": text.strip(),
                "conversationItemId": conversation_item_id,
            }
        )
        return turn_id

    def _record_transition(
        self,
        *,
        user_transcript: str,
        event: TurnEvent,
        state: ConversationState,
    ) -> str:
        transition = state["transition_history"][-1]
        turn_id = self._id_factory()
        self._pending_turn_ids.append(turn_id)
        self._write(
            {
                "version": 1,
                "type": "fsm_transition",
                "callId": self._call_id,
                "turnId": turn_id,
                "recordedAt": self._timestamp(),
                "userTranscript": user_transcript,
                "interpretedIntent": event["intent"],
                "fromPhase": transition["from_phase"],
                "toPhase": transition["to_phase"],
                "directive": transition["directive"],
                "guardReason": transition["guard_reason"],
                "identityVerified": state["identity_verified"],
                "refusalCount": state["refusal_count"],
                "resolutionType": state["resolution_type"],
                "shouldEnd": state["should_end"],
                "interpreter": event.get("evidence", {}).get("interpreter"),
            }
        )
        return turn_id

    def _write(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        if self._event_writer is not None:
            self._event_writer(event)
        if self._jsonl_path:
            path = Path(self._jsonl_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    def _timestamp(self) -> str:
        return self._now().astimezone(timezone.utc).isoformat()
