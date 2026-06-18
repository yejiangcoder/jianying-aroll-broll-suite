from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from aroll_v21.ingest import DraftIngest
from aroll_v21.ir import CaptionRenderUnit
from aroll_v21.writer import CaptionMaterialWriter


ROOT = Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text("utf-8"))


def _caption(uid: str = "s001") -> CaptionRenderUnit:
    return CaptionRenderUnit(
        caption_id=f"cap_{uid}",
        timeline_segment_ids=[f"timeline_{uid}"],
        word_ids=["w001"],
        text="输出字幕",
        target_start_us=0,
        target_end_us=1000000,
        source_subtitle_uids=[uid],
        style_template_id="canonical_caption_template",
    )


class ArollV21CaptionTemplateSubtitleBoundNotTitleLikeTests(unittest.TestCase):
    def test_subtitle_bound_title_like_marker_is_not_direct_rejection(self) -> None:
        fixture = _load("fixtures/real_materials/normal_caption_template.json")
        material = copy.deepcopy(fixture["material"])
        segment = copy.deepcopy(fixture["segment"])
        material["role"] = "title"
        material["name"] = "center title marker from real subtitle track"
        segment["type"] = "title"
        graph = DraftIngest().build_source_graph(
            word_timeline=[
                {"word_id": "w001", "word_text": "字幕", "start_us": 0, "end_us": 100000, "subtitle_uid": "s001", "subtitle_index": 1}
            ],
            subtitles=[{"subtitle_uid": "s001", "subtitle_index": 1, "text": "字幕", "word_ids": ["w001"], "text_material_id": material["id"]}],
            source_segments=[{"id": "clip", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000000}],
            text_materials=[material],
            text_segments=[segment],
        )

        plan, blockers = CaptionMaterialWriter().build_write_plan(graph, [_caption()])

        self.assertEqual(blockers, [])
        report = plan["template_report"]
        self.assertEqual(report["candidate_count"], 1)
        self.assertEqual(report["rejection_summary"]["title_like"], 0)
        self.assertEqual(report["title_like_reasons"]["position_center_title_like"], 1)
        self.assertEqual(plan["writer_fallback_count"], 0)

    def test_giant_title_bound_to_subtitle_is_still_rejected(self) -> None:
        fixture = _load("fixtures/real_materials/giant_title_material.json")
        graph = DraftIngest().build_source_graph(
            word_timeline=[
                {"word_id": "w001", "word_text": "字幕", "start_us": 0, "end_us": 100000, "subtitle_uid": "s001", "subtitle_index": 1}
            ],
            subtitles=[
                {"subtitle_uid": "s001", "subtitle_index": 1, "text": "字幕", "word_ids": ["w001"], "text_material_id": fixture["material"]["id"]}
            ],
            source_segments=[{"id": "clip", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000000}],
            text_materials=[fixture["material"]],
            text_segments=[fixture["segment"]],
        )

        plan, blockers = CaptionMaterialWriter().build_write_plan(graph, [_caption()])

        self.assertTrue(blockers)
        self.assertEqual(blockers[0].code, "CAPTION_TEMPLATE_NOT_FOUND")
        self.assertEqual(plan["template_report"]["rejection_summary"]["giant_style"], 1)
        self.assertEqual(plan["writer_fallback_count"], 0)


if __name__ == "__main__":
    unittest.main()
