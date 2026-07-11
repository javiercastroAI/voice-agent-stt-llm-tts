"""Combined FSM and voice-telemetry verdict for one real-audio run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .fsm_adherence import AdherenceReport
from .quality import QualityReport


@dataclass(frozen=True)
class AudioAdherenceReport:
    scenario_id: str
    status: str
    manual_verdict: str
    adherence: AdherenceReport
    voice_quality: QualityReport

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenarioId": self.scenario_id,
            "status": self.status,
            "manualVerdict": self.manual_verdict,
            "fsmAdherence": self.adherence.as_dict(),
            "voiceQuality": self.voice_quality.as_dict(),
        }


def combine_audio_evidence(
    *,
    scenario_id: str,
    adherence: AdherenceReport,
    voice_quality: QualityReport,
    manual_verdict: str,
) -> AudioAdherenceReport:
    if manual_verdict not in {"pass", "warn", "fail", "unknown"}:
        raise ValueError(f"Unknown manual verdict: {manual_verdict}")
    statuses = {adherence.status, voice_quality.status, manual_verdict}
    if "fail" in statuses:
        status = "fail"
    elif statuses == {"pass"}:
        status = "pass"
    else:
        status = "warn"
    return AudioAdherenceReport(
        scenario_id=scenario_id,
        status=status,
        manual_verdict=manual_verdict,
        adherence=adherence,
        voice_quality=voice_quality,
    )
