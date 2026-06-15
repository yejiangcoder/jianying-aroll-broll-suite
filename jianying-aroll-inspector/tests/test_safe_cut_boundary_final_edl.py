from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aroll_safe_cut_boundary_gate import audit_safe_cut_boundaries


class SafeCutBoundaryFinalEdlTest(unittest.TestCase):
    def test_final_edl_boundary_check_added(self) -> None:
        report = audit_safe_cut_boundaries(
            [{"word_id": "w1", "word_text": "A", "start_us": 100_000, "end_us": 300_000}],
            final_edl=[{"clip_id": "c1", "source_start_us": 180_000, "source_end_us": 500_000}],
        )
        self.assertFalse(report["safe_cut_boundary_gate_passed"])
        self.assertGreater(report["unsafe_final_edl_boundary_count"], 0)

    def test_cut_inside_word_detection(self) -> None:
        report = audit_safe_cut_boundaries(
            [{"word_id": "w1", "word_text": "A", "start_us": 100_000, "end_us": 300_000}],
            {"drop_decisions": [{"source_start_us": 180_000, "source_end_us": 500_000, "drop_text": "x"}]},
        )
        self.assertGreater(report["cut_inside_word_count"], 0)


if __name__ == "__main__":
    unittest.main()
