from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aroll_final_target_repeat_repair import propose_final_target_repeat_repairs


def word_rows(tokens: list[str]) -> list[dict]:
    rows = []
    for idx, token in enumerate(tokens, start=1):
        rows.append(
            {
                "word_id": f"w{idx}",
                "word_text": token,
                "subtitle_index": idx,
                "subtitle_uid": f"sub{idx}",
                "start_us": idx * 100_000,
                "end_us": idx * 100_000 + 80_000,
            }
        )
    return rows


class FinalTargetRepeatProposalTest(unittest.TestCase):
    def test_drop_contained_short_phrase(self) -> None:
        words = word_rows(["甲", "乙", "甲", "乙", "丙"])
        display = [
            {"fragment_id": "d1", "fragment_text": "甲乙", "source_start_us": 100_000, "word_ids": ["w1", "w2"]},
            {"fragment_id": "d2", "fragment_text": "甲乙丙", "source_start_us": 300_000, "word_ids": ["w3", "w4", "w5"]},
        ]
        gate = {
            "final_target_repeat_candidates": [
                {"cluster_id": "tc1", "confidence": "medium", "items": [{"subtitle_index": 1}, {"subtitle_index": 2}]}
            ]
        }
        proposals, report = propose_final_target_repeat_repairs(
            final_repeat_gate_report=gate,
            display_subtitle_plan=display,
            word_timeline=words,
        )
        self.assertEqual(report["drop_contained_count"], 1)
        self.assertEqual(proposals[0].repair_type, "drop_contained_final_repeat")
        self.assertEqual(proposals[0].remove_word_ids, ["w1", "w2"])

    def test_suffix_prefix_overlap_merge(self) -> None:
        words = word_rows(["甲", "乙", "丙", "丙", "丁"])
        display = [
            {"fragment_id": "d1", "fragment_text": "甲乙丙", "source_start_us": 100_000, "word_ids": ["w1", "w2", "w3"]},
            {"fragment_id": "d2", "fragment_text": "丙丁", "source_start_us": 400_000, "word_ids": ["w4", "w5"]},
        ]
        gate = {
            "final_target_repeat_candidates": [
                {"cluster_id": "tc2", "confidence": "medium", "items": [{"subtitle_index": 1}, {"subtitle_index": 2}]}
            ]
        }
        proposals, report = propose_final_target_repeat_repairs(
            final_repeat_gate_report=gate,
            display_subtitle_plan=display,
            word_timeline=words,
        )
        self.assertEqual(report["overlap_merge_count"], 0)
        self.assertEqual(report["block_count"], 1)

        words2 = word_rows(["甲", "乙", "丙", "乙", "丙", "丁"])
        display2 = [
            {"fragment_id": "d1", "fragment_text": "甲乙丙", "source_start_us": 100_000, "word_ids": ["w1", "w2", "w3"]},
            {"fragment_id": "d2", "fragment_text": "乙丙丁", "source_start_us": 400_000, "word_ids": ["w4", "w5", "w6"]},
        ]
        proposals2, report2 = propose_final_target_repeat_repairs(
            final_repeat_gate_report=gate,
            display_subtitle_plan=display2,
            word_timeline=words2,
        )
        self.assertEqual(report2["overlap_merge_count"], 1)
        self.assertEqual(proposals2[0].repair_type, "overlap_merge_final_repeat")
        self.assertEqual(proposals2[0].remove_word_ids, ["w4", "w5"])
        self.assertEqual(proposals2[0].merged_text, "甲乙丙丁")


if __name__ == "__main__":
    unittest.main()

