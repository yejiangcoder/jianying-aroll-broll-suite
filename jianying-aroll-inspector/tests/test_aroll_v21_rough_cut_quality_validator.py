from __future__ import annotations

import unittest

from aroll_v21 import ArollEngine, ArollRunInput
from aroll_v21.validate.rough_cut_quality import build_rough_cut_quality_metrics


class ArollV21RoughCutQualityValidatorTests(unittest.TestCase):
    def test_unmergeable_one_char_fragments_are_blocked_by_source_time_gap(self) -> None:
        report = ArollEngine().run(
            ArollRunInput(
                source_segments=[
                    {"id": "clip_a", "material_id": "main", "source_start_us": 0, "source_end_us": 200_000},
                    {"id": "clip_b", "material_id": "main", "source_start_us": 2_000_000, "source_end_us": 2_200_000},
                ],
                word_timeline=[
                    {
                        "word_id": "w1",
                        "word_text": "的",
                        "start_us": 0,
                        "end_us": 120_000,
                        "source_material_id": "main",
                        "source_segment_id": "clip_a",
                        "subtitle_uid": "s1",
                        "subtitle_index": 1,
                    },
                    {
                        "word_id": "w2",
                        "word_text": "家",
                        "start_us": 2_000_000,
                        "end_us": 2_120_000,
                        "source_material_id": "main",
                        "source_segment_id": "clip_b",
                        "subtitle_uid": "s2",
                        "subtitle_index": 2,
                    },
                ],
                subtitles=[
                    {"subtitle_uid": "s1", "subtitle_index": 1, "text": "的", "word_ids": ["w1"]},
                    {"subtitle_uid": "s2", "subtitle_index": 2, "text": "家", "word_ids": ["w2"]},
                ],
                text_materials=[
                    {"id": "caption_template", "type": "caption", "content": "{\"text\":\"字幕\",\"styles\":[{\"range\":{\"start\":0,\"end\":2},\"font_size\":42}]}"}
                ],
                text_segments=[{"id": "text_seg", "material_id": "caption_template", "type": "text"}],
                postwrite_mode="simulated",
            )
        )

        self.assertEqual(report.status, "blocked")
        blocker_codes = [blocker.code for blocker in report.blocker_report.blockers]
        self.assertIn("ROUGH_CUT_RESIDUAL_MICRO_SEGMENT_UNMERGEABLE", blocker_codes)
        blocker = next(
            row for row in report.blocker_report.blockers if row.code == "ROUGH_CUT_RESIDUAL_MICRO_SEGMENT_UNMERGEABLE"
        )
        self.assertEqual(blocker.context["text"], "的")
        self.assertEqual(blocker.context["word_ids"], ["w1"])
        self.assertGreater(blocker.context["next_gap_us"], blocker.context["merge_policy"]["source_gap_merge_limit_us"])
        self.assertFalse(blocker.context["next"]["can_merge"])

    def test_failure_bundle_metrics_shape_fails_quality_gate(self) -> None:
        metrics = build_rough_cut_quality_metrics(
            final_timeline=[],
            captions=[],
            material_write_plan={"materials": [object()] * 163, "segments": [object()] * 168},
            visible_caption_track_count=2,
            old_subtitle_residue_track_count=1,
            overlapping_caption_segments_count=34,
        )

        self.assertFalse(metrics["rough_cut_quality_gate_passed"])
        self.assertEqual(metrics["visible_caption_track_count"], 2)
        self.assertEqual(metrics["old_subtitle_residue_track_count"], 1)
        self.assertEqual(metrics["overlapping_caption_segments_count"], 34)


if __name__ == "__main__":
    unittest.main()
