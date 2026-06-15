from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aroll_subtitle_coverage_gate import audit_subtitle_coverage


class SubtitleCoverageWordLevelTest(unittest.TestCase):
    def test_missing_word_detection(self) -> None:
        report = audit_subtitle_coverage(
            [{"source_start_us": 0, "source_end_us": 3_000_000, "target_start_us": 0, "target_duration_us": 3_000_000}],
            [{"fragment_id": "s1", "source_start_us": 0, "source_end_us": 3_000_000, "word_ids": ["w1", "w2"]}],
            [
                {"word_id": "w1", "word_text": "A", "start_us": 0, "end_us": 1_000_000},
                {"word_id": "w2", "word_text": "B", "start_us": 1_000_000, "end_us": 2_000_000},
                {"word_id": "w3", "word_text": "C", "start_us": 2_000_000, "end_us": 3_000_000},
            ],
        )
        self.assertFalse(report["subtitle_coverage_gate_passed"])
        self.assertEqual(report["missing_word_count"], 1)
        self.assertIn("C", report["missing_word_text_samples"])

    def test_subtitle_word_coverage_ratio(self) -> None:
        report = audit_subtitle_coverage(
            [{"source_start_us": 0, "source_end_us": 2_000_000, "target_start_us": 0, "target_duration_us": 2_000_000}],
            [{"fragment_id": "s1", "source_start_us": 0, "source_end_us": 2_000_000, "word_ids": ["w1", "w2"]}],
            [
                {"word_id": "w1", "word_text": "A", "start_us": 0, "end_us": 1_000_000},
                {"word_id": "w2", "word_text": "B", "start_us": 1_000_000, "end_us": 2_000_000},
            ],
        )
        self.assertTrue(report["subtitle_coverage_gate_passed"])
        self.assertEqual(report["subtitle_word_coverage_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
