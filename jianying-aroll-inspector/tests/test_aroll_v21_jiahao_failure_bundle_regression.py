from __future__ import annotations

import unittest

from aroll_v21 import ArollEngine, ArollRunInput


class ArollV21JiahaoFailureBundleRegressionTests(unittest.TestCase):
    def test_failure_like_fragmented_cut_is_blocked_by_residual_micro_time_gap_diagnostic(self) -> None:
        report = ArollEngine().run(
            ArollRunInput(
                source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 3_000_000}],
                word_timeline=[
                    {"word_id": "w1", "word_text": "的", "start_us": 0, "end_us": 40_000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s1", "subtitle_index": 1},
                    {"word_id": "w2", "word_text": "豪", "start_us": 120_000, "end_us": 200_000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s2", "subtitle_index": 2},
                    {"word_id": "w3", "word_text": "家", "start_us": 1_900_000, "end_us": 1_980_000, "source_material_id": "main", "source_segment_id": "clip_b", "subtitle_uid": "s3", "subtitle_index": 3},
                ],
                subtitles=[
                    {"subtitle_uid": "s1", "subtitle_index": 1, "text": "的", "word_ids": ["w1"]},
                    {"subtitle_uid": "s2", "subtitle_index": 2, "text": "豪", "word_ids": ["w2"]},
                    {"subtitle_uid": "s3", "subtitle_index": 3, "text": "家", "word_ids": ["w3"]},
                ],
                text_materials=[
                    {"id": "caption_template", "type": "caption", "content": "{\"text\":\"字幕\",\"styles\":[{\"range\":{\"start\":0,\"end\":2},\"font_size\":42}]}"}
                ],
                text_segments=[{"id": "text_seg", "material_id": "caption_template", "type": "text"}],
                postwrite_mode="simulated",
            )
        )

        self.assertEqual(report.status, "blocked")
        residual_blockers = [
            blocker
            for blocker in report.blocker_report.blockers
            if blocker.code == "ROUGH_CUT_RESIDUAL_MICRO_SEGMENT_UNMERGEABLE"
        ]
        self.assertGreaterEqual(len(residual_blockers), 1)
        self.assertEqual(residual_blockers[0].context["text"], "的豪")
        self.assertEqual(residual_blockers[0].context["word_ids"], ["w1", "w2"])

    def test_normalized_phrase_cut_passes_rough_cut_quality_validator(self) -> None:
        report = ArollEngine().run(
            ArollRunInput(
                source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 1_000_000}],
                word_timeline=[
                    {"word_id": "w1", "word_text": "肆意的", "start_us": 100_000, "end_us": 400_000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s1", "subtitle_index": 1},
                    {"word_id": "w2", "word_text": "踩踏", "start_us": 400_000, "end_us": 900_000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s2", "subtitle_index": 2},
                ],
                subtitles=[
                    {"subtitle_uid": "s1", "subtitle_index": 1, "text": "肆意的", "word_ids": ["w1"]},
                    {"subtitle_uid": "s2", "subtitle_index": 2, "text": "踩踏", "word_ids": ["w2"]},
                ],
                text_materials=[
                    {"id": "caption_template", "type": "caption", "content": "{\"text\":\"字幕\",\"styles\":[{\"range\":{\"start\":0,\"end\":2},\"font_size\":42}]}"}
                ],
                text_segments=[{"id": "text_seg", "material_id": "caption_template", "type": "text"}],
                postwrite_mode="simulated",
            )
        )

        self.assertEqual(report.status, "ok")
        self.assertTrue(report.validator_report["rough_cut_quality_validator"]["rough_cut_quality_gate_passed"])


if __name__ == "__main__":
    unittest.main()
