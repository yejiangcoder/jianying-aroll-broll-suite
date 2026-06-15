from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aroll_downstream_repair_pipeline import run_downstream_repair_pipeline
from aroll_gate_runner import run_downstream_gates


def make_words(tokens: list[str]) -> list[dict]:
    out = []
    for idx, token in enumerate(tokens, start=1):
        start = idx * 100_000
        out.append(
            {
                "word_id": f"w{idx}",
                "word_text": token,
                "subtitle_index": 1,
                "subtitle_uid": "sub1",
                "start_us": start,
                "end_us": start + 80_000,
            }
        )
    return out


class DownstreamRepairPipelineTest(unittest.TestCase):
    def test_pipeline_regate_passes_hidden_repeat(self) -> None:
        words = make_words(["甲", "乙", "甲", "乙", "丙"])
        edl = [{"clip_id": "c1", "source_start_us": 100_000, "source_end_us": 580_000, "target_start_us": 0, "target_duration_us": 480_000}]
        display = [{"fragment_id": "d1", "fragment_text": "甲乙甲乙丙", "word_ids": ["w1", "w2", "w3", "w4", "w5"], "source_start_us": 100_000, "source_end_us": 580_000, "target_start_us": 0, "target_duration_us": 480_000}]
        with tempfile.TemporaryDirectory() as td:
            repaired_edl, repaired_subs, report = run_downstream_repair_pipeline(
                final_edl=edl,
                display_subtitle_plan=display,
                word_timeline=words,
                run_dir=Path(td),
                max_iterations=2,
            )
            final_gate = run_downstream_gates(
                final_edl=repaired_edl,
                display_subtitle_plan=repaired_subs,
                word_timeline=words,
                run_dir=Path(td) / "verify",
            )
        self.assertTrue(report["final_gate_passed"])
        self.assertTrue(final_gate["all_gates_passed"])
        self.assertEqual(final_gate["raw_reports"]["hidden_repeat"]["word_timeline_repeated_island_count"], 0)

    def test_pipeline_blocks_unrepairable_repeat(self) -> None:
        words = make_words(["甲", "乙", "丙", "丁", "甲", "乙", "丙", "丁"])
        edl = [{"clip_id": "c1", "source_start_us": 100_000, "source_end_us": 880_000, "target_start_us": 0, "target_duration_us": 780_000}]
        display = [
            {"fragment_id": "d1", "fragment_text": "甲乙丙丁", "word_ids": ["w1", "w2", "w3", "w4"], "source_start_us": 100_000, "source_end_us": 480_000, "target_start_us": 0, "target_duration_us": 380_000},
            {"fragment_id": "d2", "fragment_text": "甲乙丙丁", "word_ids": ["w5", "w6", "w7", "w8"], "source_start_us": 500_000, "source_end_us": 880_000, "target_start_us": 400_000, "target_duration_us": 380_000},
        ]
        with tempfile.TemporaryDirectory() as td:
            _edl, _subs, report = run_downstream_repair_pipeline(
                final_edl=edl,
                display_subtitle_plan=display,
                word_timeline=words,
                run_dir=Path(td),
                max_iterations=2,
            )
        self.assertFalse(report["final_gate_passed"])
        self.assertTrue(report["remaining_blockers"])


if __name__ == "__main__":
    unittest.main()
