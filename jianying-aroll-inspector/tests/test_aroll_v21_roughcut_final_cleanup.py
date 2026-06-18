from __future__ import annotations

import unittest

from aroll_v21.compiler import RoughCutQualityNormalizer
from aroll_v21.ir import DecisionPlan
from aroll_v21.validate.rough_cut_quality import build_rough_cut_quality_metrics
from tests.test_aroll_v21_rough_cut_quality_normalizer import make_segment, make_source_graph, make_word


class ArollV21RoughCutFinalCleanupTests(unittest.TestCase):
    def test_convergence_removes_remaining_sub_300ms_and_one_char_segments(self) -> None:
        words = [
            make_word("w1", "这", 0, 80_000, "s1", 1),
            make_word("w2", "说明", 80_000, 420_000, "s1", 1),
            make_word("w3", "问题", 420_000, 820_000, "s1", 1),
        ]
        segments = [
            make_segment("seg1", "这", 0, 80_000, ["w1"]),
            make_segment("seg2", "说明", 80_000, 420_000, ["w2"]),
            make_segment("seg3", "问题", 420_000, 820_000, ["w3"]),
        ]

        normalized, blockers = RoughCutQualityNormalizer().normalize(
            segments,
            make_source_graph(words),
            DecisionPlan(decisions=[]),
        )
        captions = [
            type(
                "Caption",
                (),
                {
                    "text": segment.text,
                    "word_ids": segment.word_ids,
                    "timeline_segment_ids": [segment.segment_id],
                    "target_start_us": segment.target_start_us,
                    "target_end_us": segment.target_end_us,
                },
            )()
            for segment in normalized
        ]
        material_write_plan = {"materials": [{} for _ in captions], "segments": [{} for _ in captions]}
        metrics = build_rough_cut_quality_metrics(
            final_timeline=normalized,
            captions=captions,  # type: ignore[arg-type]
            material_write_plan=material_write_plan,
        )

        self.assertEqual(blockers, [])
        self.assertEqual(metrics["segments_lt_300ms"], 0)
        self.assertEqual(metrics["one_char_captions"], 0)
        self.assertEqual(metrics["target_gap_count"], 0)
        self.assertEqual(metrics["target_overlap_count"], 0)


if __name__ == "__main__":
    unittest.main()
