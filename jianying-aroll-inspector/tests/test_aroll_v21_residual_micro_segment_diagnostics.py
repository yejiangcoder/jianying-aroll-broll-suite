from __future__ import annotations

import unittest
from dataclasses import replace

from aroll_v21.compiler import RoughCutQualityNormalizer
from aroll_v21.ir import DecisionPlan
from aroll_v21.validate.rough_cut_quality import build_rough_cut_quality_metrics
from tests.test_aroll_v21_rough_cut_quality_normalizer import make_segment, make_source_graph, make_word


def _caption_rows(segments):
    return [
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
        for segment in segments
    ]


class ArollV21ResidualMicroSegmentDiagnosticsTests(unittest.TestCase):
    def test_same_source_segment_legal_gap_residual_is_merged_and_metrics_clear(self) -> None:
        words = [
            make_word("w1", "这", 0, 80_000, "s1", 1),
            make_word("w2", "说明问题", 120_000, 620_000, "s2", 2),
        ]
        segments = [
            make_segment("seg1", "这", 0, 80_000, ["w1"]),
            make_segment("seg2", "说明问题", 120_000, 620_000, ["w2"]),
        ]

        normalized, blockers = RoughCutQualityNormalizer().normalize(
            segments,
            make_source_graph(words),
            DecisionPlan(decisions=[]),
        )
        captions = _caption_rows(normalized)
        metrics = build_rough_cut_quality_metrics(
            final_timeline=normalized,
            captions=captions,  # type: ignore[arg-type]
            material_write_plan={"materials": [{} for _ in captions], "segments": [{} for _ in captions]},
        )

        self.assertEqual(blockers, [])
        self.assertEqual([segment.text for segment in normalized], ["这说明问题"])
        self.assertEqual(metrics["segments_lt_300ms"], 0)
        self.assertEqual(metrics["one_char_captions"], 0)

    def test_legacy_different_source_segment_residual_can_merge_by_time_continuity(self) -> None:
        words = [
            make_word("w1", "前文", 0, 500_000, "s1", 1),
            replace(make_word("w2", "这", 600_000, 800_000, "s2", 2), source_segment_id="clip_002"),
        ]
        segments = [
            make_segment("seg1", "前文", 0, 500_000, ["w1"]),
            replace(make_segment("seg2", "这", 600_000, 800_000, ["w2"]), source_segment_id="clip_002"),
        ]

        normalized, blockers = RoughCutQualityNormalizer().normalize(
            segments,
            make_source_graph(words, source_end_us=1_000_000),
            DecisionPlan(decisions=[]),
        )

        self.assertEqual(blockers, [])
        self.assertEqual([segment.text for segment in normalized], ["前文这"])

    def test_illegal_source_gap_residual_blocks_without_cross_gap_merge(self) -> None:
        words = [
            make_word("w1", "前文", 0, 500_000, "s1", 1),
            make_word("w2", "这", 2_100_000, 2_300_000, "s2", 2),
        ]
        segments = [
            make_segment("seg1", "前文", 0, 500_000, ["w1"]),
            make_segment("seg2", "这", 2_100_000, 2_300_000, ["w2"]),
        ]

        _normalized, blockers = RoughCutQualityNormalizer().normalize(
            segments,
            make_source_graph(words, source_end_us=2_500_000),
            DecisionPlan(decisions=[]),
        )

        self.assertEqual([blocker.code for blocker in blockers], ["ROUGH_CUT_RESIDUAL_MICRO_SEGMENT_UNMERGEABLE"])
        context = blockers[0].context
        self.assertEqual(context["prev_gap_us"], 1_600_000)
        self.assertEqual(context["merge_policy"]["source_gap_merge_limit_us"], 1_500_000)
        self.assertFalse(context["prev"]["can_merge"])


if __name__ == "__main__":
    unittest.main()
