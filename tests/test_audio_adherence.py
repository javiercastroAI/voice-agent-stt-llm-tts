from __future__ import annotations

import unittest

from voice_agent.audio_adherence import combine_audio_evidence
from voice_agent.fsm_adherence import AdherenceReport
from voice_agent.quality import QualityReport


class AudioAdherenceTests(unittest.TestCase):
    def report(self, adherence: str, quality: str, manual: str):
        return combine_audio_evidence(
            scenario_id="normal-latency-path",
            adherence=AdherenceReport(adherence, 1, ()),
            voice_quality=QualityReport(quality, ()),
            manual_verdict=manual,
        )

    def test_requires_all_evidence_to_pass(self) -> None:
        self.assertEqual(self.report("pass", "pass", "pass").status, "pass")
        self.assertEqual(self.report("pass", "warn", "pass").status, "warn")
        self.assertEqual(self.report("fail", "pass", "pass").status, "fail")
        self.assertEqual(self.report("pass", "pass", "unknown").status, "warn")


if __name__ == "__main__":
    unittest.main()
