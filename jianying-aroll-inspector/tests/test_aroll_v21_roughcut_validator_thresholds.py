from __future__ import annotations

import unittest

from aroll_v21.ir import CaptionRenderUnit
from aroll_v21.validate.rough_cut_quality import build_rough_cut_quality_metrics
from tests.test_aroll_v21_rough_cut_quality_normalizer import make_segment


def _caption(index: int, text: str, word_ids: list[str], start: int, end: int) -> CaptionRenderUnit:
    return CaptionRenderUnit(
        caption_id=f"cap_{index:06d}",
        timeline_segment_ids=[f"seg{index}"],
        word_ids=word_ids,
        text=text,
        target_start_us=start,
        target_end_us=end,
        source_subtitle_uids=[f"s{index}"],
        style_template_id="tmpl",
    )


class ArollV21RoughcutValidatorThresholdTests(unittest.TestCase):
    def test_missing_handles_and_containment_repeat_are_metrics_not_hard_blockers(self) -> None:
        final_timeline = [
            make_segment("seg1", "甲乙丙丁", 0, 400_000, ["w1"]),
            make_segment("seg2", "过渡内容", 400_000, 900_000, ["w2"]),
            make_segment("seg3", "甲乙丙丁扩展", 900_000, 1_500_000, ["w3"]),
        ]
        captions = [
            _caption(1, "甲乙丙丁", ["w1"], 0, 400_000),
            _caption(2, "过渡内容", ["w2"], 400_000, 900_000),
            _caption(3, "甲乙丙丁扩展", ["w3"], 900_000, 1_500_000),
        ]

        metrics = build_rough_cut_quality_metrics(
            final_timeline=final_timeline,
            captions=captions,
            material_write_plan={"materials": [{}, {}, {}], "segments": [{}, {}, {}]},
        )

        self.assertGreater(metrics["segments_with_no_lead_handle"], 0)
        self.assertGreater(metrics["segments_with_no_tail_handle"], 0)
        self.assertGreater(metrics["containment_repeat_count"], 0)
        self.assertTrue(metrics["rough_cut_quality_gate_passed"])

    def test_adjacent_duplicate_and_caption_track_residue_are_hard_blockers(self) -> None:
        final_timeline = [
            make_segment("seg1", "兄弟健个身", 0, 500_000, ["w1"]),
            make_segment("seg2", "兄弟健个身", 500_000, 1_000_000, ["w2"]),
        ]
        captions = [
            _caption(1, "兄弟健个身", ["w1"], 0, 500_000),
            _caption(2, "兄弟健个身", ["w2"], 500_000, 1_000_000),
        ]

        metrics = build_rough_cut_quality_metrics(
            final_timeline=final_timeline,
            captions=captions,
            material_write_plan={"materials": [{}, {}], "segments": [{}, {}]},
            visible_caption_track_count=2,
            old_subtitle_residue_track_count=1,
        )

        self.assertEqual(metrics["adjacent_duplicate_text_count"], 1)
        self.assertFalse(metrics["rough_cut_quality_gate_passed"])


if __name__ == "__main__":
    unittest.main()
