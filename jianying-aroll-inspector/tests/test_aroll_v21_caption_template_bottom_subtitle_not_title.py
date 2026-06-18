from __future__ import annotations

import unittest

from aroll_v21.ingest import DraftIngest
from aroll_v21.ir import CaptionRenderUnit
from aroll_v21.writer import CaptionMaterialWriter
from tests.test_aroll_v21_caption_template_round5_position_y_minus_073 import (
    _round5_caption_material,
    _round5_caption_segment,
)


class ArollV21CaptionTemplateBottomSubtitleNotTitleTests(unittest.TestCase):
    def test_117_round5_bottom_subtitle_materials_form_one_template_group(self) -> None:
        materials: list[dict] = []
        segments: list[dict] = []
        subtitles: list[dict] = []
        words: list[dict] = []
        captions: list[CaptionRenderUnit] = []
        for index in range(1, 118):
            material_id = f"round5_text_{index:03d}"
            subtitle_uid = f"s{index:03d}"
            word_id = f"w{index:03d}"
            material = _round5_caption_material(material_id)
            segment = _round5_caption_segment(material_id)
            materials.append(material)
            segments.append(segment)
            subtitles.append(
                {
                    "subtitle_uid": subtitle_uid,
                    "subtitle_index": index,
                    "text": "底部字幕",
                    "word_ids": [word_id],
                    "text_material_id": material_id,
                }
            )
            words.append(
                {
                    "word_id": word_id,
                    "word_text": "字",
                    "start_us": index * 100000,
                    "end_us": index * 100000 + 50000,
                    "subtitle_uid": subtitle_uid,
                    "subtitle_index": index,
                }
            )
            captions.append(
                CaptionRenderUnit(
                    caption_id=f"cap_{index:03d}",
                    timeline_segment_ids=[f"timeline_{index:03d}"],
                    word_ids=[word_id],
                    text="底部字幕",
                    target_start_us=index * 100000,
                    target_end_us=index * 100000 + 50000,
                    source_subtitle_uids=[subtitle_uid],
                    style_template_id="canonical_caption_template",
                )
            )
        graph = DraftIngest().build_source_graph(
            word_timeline=words,
            subtitles=subtitles,
            source_segments=[{"id": "clip", "material_id": "main_video", "source_start_us": 0, "source_end_us": 20000000}],
            text_materials=materials,
            text_segments=segments,
        )

        plan, blockers = CaptionMaterialWriter().build_write_plan(graph, captions)

        self.assertEqual(blockers, [])
        report = plan["template_report"]
        self.assertEqual(report["candidate_count"], 117)
        self.assertEqual(report["fingerprint_group_count"], 1)
        self.assertEqual(report["rejected_count"], 0)
        self.assertEqual(report["title_like_reasons"]["bottom_subtitle_position"], 117)
        self.assertEqual(report["title_like_reasons"]["subtitle_bound_position_risk_downgraded"], 117)
        self.assertTrue(plan["materials"])
        self.assertTrue(plan["segments"])
        self.assertEqual(plan["writer_fallback_count"], 0)


if __name__ == "__main__":
    unittest.main()
