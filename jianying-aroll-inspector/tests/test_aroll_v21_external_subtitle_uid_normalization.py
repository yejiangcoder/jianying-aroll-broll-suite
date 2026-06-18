from __future__ import annotations

import unittest

from aroll_v21 import ArollEngine, ArollRunInput
from tests.test_aroll_v21_caption_template_round5_position_y_minus_073 import (
    _round5_caption_material,
    _round5_caption_segment,
)


class ArollV21ExternalSubtitleUidNormalizationTests(unittest.TestCase):
    def test_engine_external_sub_uid_reaches_writer_without_template_not_found(self) -> None:
        material = _round5_caption_material("real_text_uuid")
        report = ArollEngine().run(
            ArollRunInput(
                source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 1000000}],
                word_timeline=[
                    {
                        "word_id": "w1",
                        "word_text": "字幕可达",
                        "source_start_us": 0,
                        "source_end_us": 400000,
                        "source_material_id": "main",
                        "source_segment_id": "clip",
                        "subtitle_uid": "sub_000001",
                        "subtitle_index": 1,
                    }
                ],
                subtitles=[
                    {
                        "subtitle_uid": "real_subtitle_uuid",
                        "subtitle_index": 1,
                        "text": "字幕可达",
                        "word_ids": ["w1"],
                        "text_material_id": "real_text_uuid",
                    }
                ],
                text_materials=[material],
                text_segments=[_round5_caption_segment("real_text_uuid")],
                postwrite_mode="simulated",
            )
        )

        self.assertNotIn("CAPTION_TEMPLATE_NOT_FOUND", [blocker.code for blocker in report.blocker_report.blockers])
        self.assertTrue(report.material_write_plan["materials"])
        self.assertEqual(report.material_write_plan["writer_fallback_count"], 0)


if __name__ == "__main__":
    unittest.main()
