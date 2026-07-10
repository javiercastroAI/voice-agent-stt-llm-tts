"""Console transcript and diarization rendering."""

from __future__ import annotations

from collections.abc import Callable
import sys
from typing import TYPE_CHECKING

from livekit.agents.voice import io
from livekit.agents.voice.events import (
    AgentStateChangedEvent,
    ConversationItemAddedEvent,
    UserInputTranscribedEvent,
    UserStateChangedEvent,
)

from .diarized_stt import DiarizedTranscript

if TYPE_CHECKING:
    from .web import TranscriptStore

Writer = Callable[[str], object]


class ConversationTraceLogger:
    """Prints speaker-labeled transcript lines in the console."""

    def __init__(
        self,
        *,
        write: Writer | None = None,
        store: TranscriptStore | None = None,
        on_agent_text_finalized: Writer | None = None,
    ) -> None:
        self._write = write or self._default_write
        self._store = store
        self._on_agent_text_finalized = on_agent_text_finalized
        self._seen_assistant_ids: set[str] = set()
        self._last_diarized_user_text: str | None = None
        self._streaming_agent_text = ""
        self._last_streamed_agent_text: str | None = None

    def on_user_diarized(self, transcript: DiarizedTranscript) -> None:
        if not transcript.segments:
            return

        self._last_diarized_user_text = self._normalize(transcript.text)
        lines = ["", "--- Conversation Diarization ---"]
        for segment in transcript.segments:
            lines.append(
                f"{segment.speaker} [{segment.start:.1f}s-{segment.end:.1f}s]: {segment.text}"
            )
        lines.append("-------------------------------")
        lines.append("")
        self._write("\n".join(lines))
        if self._store is not None:
            self._store.add_user_diarized(transcript)

    def on_user_state_changed(self, event: UserStateChangedEvent) -> None:
        if self._store is not None:
            self._store.set_user_state(event.new_state)

        if event.new_state != "speaking" or event.old_state == "speaking":
            return

        self._write("\nYou: [speaking...]\n")

    def on_agent_state_changed(self, event: AgentStateChangedEvent) -> None:
        if self._store is not None:
            self._store.set_agent_state(event.new_state)

    def on_user_input_transcribed(self, event: UserInputTranscribedEvent) -> None:
        if event.transcript.strip() and self._store is not None:
            if event.is_final:
                self._store.add_user_text(
                    event.transcript.strip(),
                    speaker=event.speaker_id or "You",
                )
            else:
                self._store.set_live_user_text(
                    event.transcript.strip(),
                    speaker=event.speaker_id or "You",
                )

        if not event.is_final or not event.transcript.strip():
            return

        normalized = self._normalize(event.transcript)
        if self._last_diarized_user_text == normalized:
            self._last_diarized_user_text = None
            if self._store is not None:
                self._store.clear_live_user_text()
            return

        speaker = event.speaker_id or "User"
        self._write(f"\n{speaker}: {event.transcript.strip()}\n")

    def on_conversation_item_added(self, event: ConversationItemAddedEvent) -> None:
        item = event.item
        if getattr(item, "type", None) != "message":
            return
        if getattr(item, "role", None) != "assistant":
            return
        if item.id in self._seen_assistant_ids:
            return

        text = item.text_content
        if not text:
            return

        normalized = self._normalize(text)
        if self._last_streamed_agent_text == normalized:
            self._seen_assistant_ids.add(item.id)
            return

        self._seen_assistant_ids.add(item.id)
        self._write(f"\nAgent: {text.strip()}\n")
        if self._store is not None:
            self._store.add_agent_text(text.strip())

    def build_agent_text_output(self) -> io.TextOutput:
        return _ConsoleAgentTextOutput(self)

    def on_agent_text_delta(self, text: str) -> None:
        if not text:
            return

        if not self._streaming_agent_text:
            self._write("\nAgent: ")

        self._streaming_agent_text += text
        self._write(text)
        if self._store is not None:
            self._store.append_agent_delta(text)

    def on_agent_text_flush(self) -> None:
        if not self._streaming_agent_text:
            return

        finalized_text = self._streaming_agent_text.strip()
        self._last_streamed_agent_text = self._normalize(finalized_text)
        self._streaming_agent_text = ""
        self._write("\n")
        if self._store is not None:
            self._store.finalize_agent_stream()
        if self._on_agent_text_finalized is not None and finalized_text:
            self._on_agent_text_finalized(finalized_text)

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.split())

    @staticmethod
    def _default_write(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()


class _ConsoleAgentTextOutput(io.TextOutput):
    def __init__(self, logger: ConversationTraceLogger) -> None:
        super().__init__(label="ConversationTrace", next_in_chain=None)
        self._logger = logger

    async def capture_text(self, text: str) -> None:
        self._logger.on_agent_text_delta(text)

    def flush(self) -> None:
        self._logger.on_agent_text_flush()
