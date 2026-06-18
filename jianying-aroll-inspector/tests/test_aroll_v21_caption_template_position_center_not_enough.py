from __future__ import annotations

import unittest

from aroll_v21.ingest import DraftIngest
from aroll_v21.ir import CaptionRenderUnit
from aroll_v21.writer import CaptionMaterialWriter
from tests.test_aroll_v21_caption_template_round5_position_y_minus_073 import (
    _round5_caption_material,
    _round5_caption_segment,
)


class ArollV21CaptionTemplatePositionCenterNotEnoughTests(unittest.TestCase):
    def test_horizontal_center_x_zero_does_not_reject_safe_bottom_subtitle(self) -> None:
        material = _round5_caption_material()
        segment = _round5_caption_segment()
        segment["clip"]["transform"]["x"] = 0.0
        graph = DraftIngest().build_source_graph(
            word_timeline=[
                {"word_id": "w001", "word_text": "字幕", "start_us": 0, "end_us": 100000, "subtitle_uid": "s001", "subtitle_index": 1}
            ],
            subtitles=[{"subtitle_uid": "s001", "subtitle_index": 1, "text": "字幕", "word_ids": ["w001"], "text_material_id": material["id"]}],
            source_segments=[{"id": "clip", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000000}],
            text_materials=[material],
            text_segments=[segment],
        )

        plan, blockers = CaptionMaterialWriter().build_write_plan(
            graph,
            [
                CaptionRenderUnit(
                    caption_id="cap",
                    timeline_segment_ids=["timeline"],
                    word_ids=["w001"],
                    text="字幕",
                    target_start_us=0,
                    target_end_us=1000000,
                    source_subtitle_uids=["s001"],
                    style_template_id="canonical_caption_template",
                )
            ],
        )

        self.assertEqual(blockers, [])
        self.assertEqual(plan["template_report"]["rejection_summary"]["title_like"], 0)
        self.assertEqual(plan["template_report"]["title_like_reasons"]["position_center_title_like"], 0)
        self.assertEqual(plan["writer_fallback_count"], 0)

    def test_true_giant_title_is_still_rejected(self) -> None:
        material = _round5_caption_material()
        segment = _round5_caption_segment()
        material["font_size"] = 180
        material["scale"] = {"x": 5.0, "y": 5.0}
        graph = DraftIngest().build_source_graph(
            word_timeline=[
                {"word_id": "w001", "word_text": "字幕", "start_us": 0, "end_us": 100000, "subtitle_uid": "s001", "subtitle_index": 1}
            ],
            subtitles=[{"subtitle_uid": "s001", "subtitle_index": 1, "text": "字幕", "word_ids": ["w001"], "text_material_id": material["id"]}],
            source_segments=[{"id": "clip", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000000}],
            text_materials=[material],
            text_segments=[segment],
        )

        plan, blockers = CaptionMaterialWriter().build_write_plan(
            graph,
            [
                CaptionRenderUnit(
                    caption_id="cap",
                    timeline_segment_ids=["timeline"],
                    word_ids=["w001"],
                    text="字幕",
                    target_start_us=0,
                    target_end_us=1000000,
                    source_subtitle_uids=["s001"],
                    style_template_id="canonical_caption_template",
                )
            ],
        )

        self.assertTrue(blockers)
        self.assertEqual(blockers[0].code, "CAPTION_TEMPLATE_NOT_FOUND")
        self.assertEqual(plan["template_report"]["rejection_summary"]["giant_style"], 1)
        self.assertEqual(plan["writer_fallback_count"], 0)


if __name__ == "__main__":
    unittest.main()
