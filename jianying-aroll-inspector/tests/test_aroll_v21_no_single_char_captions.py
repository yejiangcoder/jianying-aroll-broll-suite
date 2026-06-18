from __future__ import annotations

import unittest

from aroll_v21 import ArollEngine, ArollRunInput


class ArollV21NoSingleCharCaptionsTests(unittest.TestCase):
    def test_short_fragments_are_grouped_into_multi_char_captions(self) -> None:
        report = ArollEngine().run(
            ArollRunInput(
                source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 1_000_000}],
                word_timeline=[
                    {"word_id": "w1", "word_text": "这", "start_us": 0, "end_us": 80_000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s1", "subtitle_index": 1},
                    {"word_id": "w2", "word_text": "这说明", "start_us": 80_000, "end_us": 520_000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s2", "subtitle_index": 2},
                ],
                subtitles=[
                    {"subtitle_uid": "s1", "subtitle_index": 1, "text": "这", "word_ids": ["w1"]},
                    {"subtitle_uid": "s2", "subtitle_index": 2, "text": "这说明", "word_ids": ["w2"]},
                ],
                text_materials=[
                    {"id": "caption_template", "type": "caption", "content": "{\"text\":\"字幕\",\"styles\":[{\"range\":{\"start\":0,\"end\":2},\"font_size\":42}]}"}
                ],
                text_segments=[{"id": "text_seg", "material_id": "caption_template", "type": "text"}],
                postwrite_mode="simulated",
            )
        )

        self.assertEqual(report.status, "ok")
        self.assertEqual(len(report.captions), 1)
        self.assertEqual(report.captions[0].text, "这说明")
        self.assertEqual(report.validator_report["rough_cut_quality_validator"]["one_char_captions"], 0)


if __name__ == "__main__":
    unittest.main()
