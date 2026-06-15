from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aroll_hidden_repeat_repair import propose_hidden_repeat_repairs


def words(tokens: list[str]) -> list[dict]:
    out = []
    for idx, token in enumerate(tokens, start=1):
        out.append(
            {
                "word_id": f"w{idx}",
                "word_text": token,
                "subtitle_index": 1,
                "subtitle_uid": "sub1",
                "start_us": idx * 100_000,
                "end_us": idx * 100_000 + 80_000,
            }
        )
    return out


class HiddenRepeatProposalTest(unittest.TestCase):
    def test_hidden_repeat_a_a_suffix_outputs_proposal(self) -> None:
        word_timeline = words(["甲", "乙", "甲", "乙", "丙"])
        display = [{"fragment_id": "f1", "fragment_text": "甲乙甲乙丙", "word_ids": ["w1", "w2", "w3", "w4", "w5"]}]
        proposals, report = propose_hidden_repeat_repairs(
            hidden_repeat_report={"word_timeline_repeated_island_count": 1},
            display_subtitle_plan=display,
            word_timeline=word_timeline,
        )
        self.assertEqual(report["proposal_count"], 1)
        self.assertEqual(proposals[0].repair_type, "remove_duplicate_word_island")
        self.assertEqual(proposals[0].keep_word_ids, ["w1", "w2"])
        self.assertEqual(proposals[0].remove_word_ids, ["w3", "w4"])
        self.assertTrue(proposals[0].preserve_suffix)


if __name__ == "__main__":
    unittest.main()

