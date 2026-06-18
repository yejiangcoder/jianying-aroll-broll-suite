from __future__ import annotations

import unittest

from aroll_v21 import ArollEngine, ArollRunInput


class ArollV21RoughCutMicroSegmentMergeTests(unittest.TestCase):
    def test_two_char_split_fragments_merge_back_into_phrase(self) -> None:
        report = ArollEngine().run(
            ArollRunInput(
                source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 1_000_000}],
                word_timeline=[
                    {"word_id": "w1", "word_text": "交配", "start_us": 0, "end_us": 220_000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s1", "subtitle_index": 1},
                    {"word_id": "w2", "word_text": "权", "start_us": 220_000, "end_us": 360_000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s2", "subtitle_index": 2},
                ],
                subtitles=[
                    {"subtitle_uid": "s1", "subtitle_index": 1, "text": "交配", "word_ids": ["w1"]},
                    {"subtitle_uid": "s2", "subtitle_index": 2, "text": "权", "word_ids": ["w2"]},
                ],
                text_materials=[
                    {"id": "caption_template", "type": "caption", "content": "{\"text\":\"字幕\",\"styles\":[{\"range\":{\"start\":0,\"end\":2},\"font_size\":42}]}"}
                ],
                text_segments=[{"id": "text_seg", "material_id": "caption_template", "type": "text"}],
                postwrite_mode="simulated",
            )
        )

        self.assertEqual(report.status, "ok")
        self.assertEqual(len(report.final_timeline), 1)
        self.assertEqual(report.final_timeline[0].text, "交配权")
        self.assertEqual(report.validator_report["rough_cut_quality_validator"]["segments_lt_300ms"], 0)


if __name__ == "__main__":
    unittest.main()
