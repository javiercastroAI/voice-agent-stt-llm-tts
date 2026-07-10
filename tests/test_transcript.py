from __future__ import annotations

import unittest

from livekit.agents.llm import ChatMessage
from livekit.agents.voice.events import (
    ConversationItemAddedEvent,
    UserInputTranscribedEvent,
    UserStateChangedEvent,
)

from voice_agent.diarized_stt import DiarizedTranscript, DiarizedTranscriptSegment
from voice_agent.transcript import ConversationTraceLogger


class ConversationTraceLoggerTests(unittest.TestCase):
    def test_prints_diarized_user_segments(self) -> None:
        writes: list[str] = []
        logger = ConversationTraceLogger(write=writes.append)

        logger.on_user_diarized(
            DiarizedTranscript(
                text="Hello there.",
                segments=(
                    DiarizedTranscriptSegment(speaker="A", text="Hello", start=0.0, end=0.5),
                    DiarizedTranscriptSegment(
                        speaker="B", text="there.", start=0.5, end=1.0
                    ),
                ),
            )
        )

        self.assertEqual(len(writes), 1)
        self.assertIn("--- Conversation Diarization ---", writes[0])
        self.assertIn("A [0.0s-0.5s]: Hello", writes[0])
        self.assertIn("B [0.5s-1.0s]: there.", writes[0])

    def test_skips_duplicate_final_user_line_when_diarization_already_printed(self) -> None:
        writes: list[str] = []
        logger = ConversationTraceLogger(write=writes.append)
        logger.on_user_diarized(
            DiarizedTranscript(
                text="Hello there.",
                segments=(DiarizedTranscriptSegment(speaker="A", text="Hello there.", start=0.0, end=1.0),),
            )
        )

        logger.on_user_input_transcribed(
            UserInputTranscribedEvent(
                transcript="Hello there.",
                is_final=True,
                speaker_id="A",
            )
        )

        self.assertEqual(len(writes), 1)

    def test_prints_assistant_messages_once(self) -> None:
        writes: list[str] = []
        logger = ConversationTraceLogger(write=writes.append)
        event = ConversationItemAddedEvent(
            item=ChatMessage(role="assistant", content=["Hi, I can help."])
        )

        logger.on_conversation_item_added(event)
        logger.on_conversation_item_added(event)

        self.assertEqual(len(writes), 1)
        self.assertIn("Agent: Hi, I can help.", writes[0])

    def test_marks_when_user_starts_speaking(self) -> None:
        writes: list[str] = []
        logger = ConversationTraceLogger(write=writes.append)

        logger.on_user_state_changed(
            UserStateChangedEvent(old_state="listening", new_state="speaking")
        )

        self.assertEqual(writes, ["\nYou: [speaking...]\n"])


class ConversationTraceLoggerStreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_streams_agent_text_and_skips_duplicate_final_message(self) -> None:
        writes: list[str] = []
        logger = ConversationTraceLogger(write=writes.append)
        output = logger.build_agent_text_output()

        await output.capture_text("Hi")
        await output.capture_text(", there.")
        output.flush()

        logger.on_conversation_item_added(
            ConversationItemAddedEvent(
                item=ChatMessage(role="assistant", content=["Hi, there."])
            )
        )

        self.assertEqual(writes, ["\nAgent: ", "Hi", ", there.", "\n"])

    async def test_reports_finalized_streamed_text_to_callback(self) -> None:
        finalized: list[str] = []
        logger = ConversationTraceLogger(
            write=lambda _text: None,
            on_agent_text_finalized=finalized.append,
        )
        output = logger.build_agent_text_output()

        await output.capture_text("Final farewell.")
        output.flush()
        output.flush()

        self.assertEqual(finalized, ["Final farewell."])
