from __future__ import annotations

import unittest

from aroll_v21 import ArollEngine, ArollRunInput


class ArollV21CompilerRespectsSubtitleBoundariesTests(unittest.TestCase):
    def test_small_gap_different_subtitles_do_not_merge(self) -> None:
        report = ArollEngine().run(
            ArollRunInput(
                source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 1000000}],
                word_timeline=[
                    {"word_id": "w1", "word_text": "就国南", "start_us": 100000, "end_us": 480000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s1", "subtitle_index": 1},
                    {"word_id": "w2", "word_text": "能不能不要规训", "start_us": 500000, "end_us": 980000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s2", "subtitle_index": 2},
                    {"word_id": "w3", "word_text": "自己人呐", "start_us": 1000000, "end_us": 1500000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s3", "subtitle_index": 3},
                ],
                subtitles=[
                    {"subtitle_uid": "s1", "subtitle_index": 1, "text": "就国南", "word_ids": ["w1"]},
                    {"subtitle_uid": "s2", "subtitle_index": 2, "text": "能不能不要规训", "word_ids": ["w2"]},
                    {"subtitle_uid": "s3", "subtitle_index": 3, "text": "自己人呐", "word_ids": ["w3"]},
                ],
                text_materials=[
                    {"id": "caption_template", "type": "caption", "content": "{\"text\":\"字幕\",\"styles\":[{\"range\":{\"start\":0,\"end\":2},\"font_size\":42}]}"}
                ],
                text_segments=[{"id": "text_seg", "material_id": "caption_template", "type": "text"}],
                postwrite_mode="simulated",
            )
        )

        self.assertEqual([segment.text for segment in report.final_timeline[:3]], ["就国南", "能不能不要规训", "自己人呐"])

    def test_same_subtitle_small_gap_can_merge(self) -> None:
        report = ArollEngine().run(
            ArollRunInput(
                source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 1000000}],
                word_timeline=[
                    {"word_id": "w1", "word_text": "就", "start_us": 100000, "end_us": 420000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s1", "subtitle_index": 1},
                    {"word_id": "w2", "word_text": "国南", "start_us": 440000, "end_us": 860000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s1", "subtitle_index": 1},
                ],
                subtitles=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": "就国南", "word_ids": ["w1", "w2"]}],
                text_materials=[
                    {"id": "caption_template", "type": "caption", "content": "{\"text\":\"字幕\",\"styles\":[{\"range\":{\"start\":0,\"end\":2},\"font_size\":42}]}"}
                ],
                text_segments=[{"id": "text_seg", "material_id": "caption_template", "type": "text"}],
                postwrite_mode="simulated",
            )
        )

        self.assertEqual(report.final_timeline[0].text, "就国南")


if __name__ == "__main__":
    unittest.main()
