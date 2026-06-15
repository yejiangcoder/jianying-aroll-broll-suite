from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aroll_repair_applier import apply_repair_proposals
from aroll_repair_proposal import RepairProposal


class RepairApplierTest(unittest.TestCase):
    def test_apply_remove_word_ids(self) -> None:
        edl = [{"clip_id": "c1", "source_start_us": 0, "source_end_us": 600_000, "target_start_us": 0, "target_duration_us": 600_000}]
        words = [
            {"word_id": "w1", "word_text": "A", "start_us": 100_000, "end_us": 180_000},
            {"word_id": "w2", "word_text": "B", "start_us": 200_000, "end_us": 280_000},
        ]
        proposal = RepairProposal(
            proposal_id="p1",
            repair_type="remove_duplicate_word_island",
            source_gate="hidden_audio_repeat_gate",
            confidence="high",
            reason="test",
            remove_word_ids=["w1"],
        )
        repaired, report = apply_repair_proposals(final_edl=edl, display_subtitle_plan=[], word_timeline=words, proposals=[proposal])
        self.assertTrue(report["applier_passed"])
        self.assertEqual(report["applied_count"], 1)
        self.assertEqual(report["remove_range_count"], 1)
        self.assertFalse(any(row["source_start_us"] < 180_000 and row["source_end_us"] > 100_000 for row in repaired))

    def test_unmapped_proposal_blocks(self) -> None:
        edl = [{"clip_id": "c1", "source_start_us": 0, "source_end_us": 600_000, "target_start_us": 0, "target_duration_us": 600_000}]
        proposal = RepairProposal(
            proposal_id="p1",
            repair_type="remove_duplicate_word_island",
            source_gate="hidden_audio_repeat_gate",
            confidence="high",
            reason="test",
            remove_word_ids=["missing"],
        )
        _repaired, report = apply_repair_proposals(final_edl=edl, display_subtitle_plan=[], word_timeline=[], proposals=[proposal])
        self.assertFalse(report["applier_passed"])
        self.assertEqual(report["blocked_count"], 1)


if __name__ == "__main__":
    unittest.main()
