from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aroll_hidden_audio_repeat_gate import build_hidden_audio_repeat_report


class HiddenRepeatGenericTest(unittest.TestCase):
    def test_generic_repeated_island_detection(self) -> None:
        report = build_hidden_audio_repeat_report(
            {"issues": []},
            [{"fragment_id": "f1", "fragment_text": "visible text", "word_ids": ["w1", "w2", "w3", "w4"]}],
            [
                {"word_id": "w1", "word_text": "甲"},
                {"word_id": "w2", "word_text": "乙"},
                {"word_id": "w3", "word_text": "甲"},
                {"word_id": "w4", "word_text": "乙"},
            ],
        )
        self.assertFalse(report["hidden_audio_repeat_gate_passed"])
        self.assertGreater(report["word_timeline_repeated_island_count"], 0)
        self.assertGreater(len(report["blocking_issues"]), 0)
        self.assertGreater(len(report["issues"]), 0)
        self.assertTrue(report["word_timeline_hidden_repeat_supported"])

    def test_production_core_has_no_hardcoded_phrase_patch(self) -> None:
        source = (SRC / "aroll_hidden_audio_repeat_gate.py").read_text("utf-8")
        forbidden = "\u8bc4\u8bba\u533a"
        self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
