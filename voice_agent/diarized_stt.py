"""OpenAI speech-to-text adapter with diarization support."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import httpx
import openai
from livekit import rtc
from livekit.agents import (
    APIConnectionError,
    APIConnectOptions,
    APIStatusError,
    APITimeoutError,
    LanguageCode,
    stt,
)
from livekit.agents.types import NOT_GIVEN, NotGivenOr
from livekit.agents.utils import is_given
from livekit.plugins import openai as openai_plugin
from openai.types.audio import TranscriptionDiarized

DIARIZED_STT_MODEL = "gpt-4o-transcribe-diarize"


@dataclass(frozen=True)
class DiarizedTranscriptSegment:
    speaker: str
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class DiarizedTranscript:
    text: str
    segments: tuple[DiarizedTranscriptSegment, ...]


class OpenAIDiarizedSTT(openai_plugin.STT):
    """Extends the LiveKit OpenAI STT wrapper with diarized output support."""

    def __init__(
        self,
        *,
        model: str = DIARIZED_STT_MODEL,
        on_diarization: Callable[[DiarizedTranscript], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(model=model, **kwargs)
        self._on_diarization = on_diarization
        self._capabilities.diarization = model == DIARIZED_STT_MODEL

    async def _recognize_impl(
        self,
        buffer,
        *,
        language: NotGivenOr[str] = NOT_GIVEN,
        conn_options: APIConnectOptions,
    ):
        if self._opts.model != DIARIZED_STT_MODEL:
            return await super()._recognize_impl(
                buffer,
                language=language,
                conn_options=conn_options,
            )

        try:
            if is_given(language):
                self._opts.language = LanguageCode(language)

            data = rtc.combine_audio_frames(buffer).to_wav_bytes()
            response = await self._client.audio.transcriptions.create(
                file=("file.wav", data, "audio/wav"),
                model=self._opts.model,
                language=self._opts.language.language if self._opts.language else "",
                response_format="diarized_json",
                chunking_strategy="auto",
                timeout=httpx.Timeout(30, connect=conn_options.timeout),
            )

            if isinstance(response, TranscriptionDiarized):
                diarized = self._to_diarized_transcript(response)
                if self._on_diarization is not None:
                    self._on_diarization(diarized)

                primary_speaker = self._primary_speaker(diarized.segments)
                speech_data = stt.SpeechData(
                    text=diarized.text,
                    language=self._opts.language,
                    speaker_id=primary_speaker,
                )
                return stt.SpeechEvent(
                    type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                    alternatives=[speech_data],
                )

            return await super()._recognize_impl(
                buffer,
                language=language,
                conn_options=conn_options,
            )

        except openai.APITimeoutError:
            raise APITimeoutError() from None
        except openai.APIStatusError as exc:
            raise APIStatusError(
                exc.message,
                status_code=exc.status_code,
                request_id=exc.request_id,
                body=exc.body,
            ) from None
        except Exception as exc:
            raise APIConnectionError() from exc

    @staticmethod
    def _to_diarized_transcript(response: TranscriptionDiarized) -> DiarizedTranscript:
        segments = tuple(
            DiarizedTranscriptSegment(
                speaker=segment.speaker,
                text=segment.text.strip(),
                start=segment.start,
                end=segment.end,
            )
            for segment in response.segments
            if segment.text.strip()
        )
        return DiarizedTranscript(text=response.text.strip(), segments=segments)

    @staticmethod
    def _primary_speaker(segments: Sequence[DiarizedTranscriptSegment]) -> str | None:
        if not segments:
            return None

        speakers = {segment.speaker for segment in segments}
        if len(speakers) == 1:
            return segments[0].speaker
        return None
