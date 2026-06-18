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


def _caption(source_uid: str = "s001") -> CaptionRenderUnit:
    return CaptionRenderUnit(
        caption_id="cap_1",
        timeline_segment_ids=["seg_1"],
        word_ids=["w1"],
        text="输出字幕",
        target_start_us=0,
        target_end_us=1000000,
        source_subtitle_uids=[source_uid],
        style_template_id="canonical_caption_template",
    )


def _graph(materials: list[dict], segments: list[dict], subtitles: list[dict]):
    return DraftIngest().build_source_graph(
        word_timeline=[
            {"word_id": "w1", "word_text": "字幕", "start_us": 0, "end_us": 100000, "subtitle_uid": subtitles[0]["subtitle_uid"], "subtitle_index": 1}
        ],
        subtitles=subtitles,
        source_segments=[{"id": "clip_1", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000000}],
        text_materials=materials,
        text_segments=segments,
    )


class ArollV21CaptionTemplateRealSubtitleMaterialsTests(unittest.TestCase):
    def test_many_real_subtitle_materials_same_fingerprint_select_one_group(self) -> None:
        fixture = _load("fixtures/real_materials/normal_caption_template.json")
        materials = []
        segments = []
        subtitles = []
        for index in range(1, 118):
            material = copy.deepcopy(fixture["material"])
            segment = copy.deepcopy(fixture["segment"])
            material["id"] = f"sub_{index:03d}"
            segment["id"] = f"seg_{index:03d}"
            segment["material_id"] = material["id"]
            materials.append(material)
            segments.append(segment)
            subtitles.append(
                {
                    "subtitle_uid": f"s{index:03d}",
                    "subtitle_index": index,
                    "text": "字幕",
                    "word_ids": ["w1"] if index == 1 else [],
                    "text_material_id": material["id"],
                }
            )
        graph = _graph(materials, segments, subtitles)

        plan, blockers = CaptionMaterialWriter().build_write_plan(graph, [_caption("s001")])

        self.assertEqual(blockers, [])
        template = plan["canonical_caption_template"]
        self.assertEqual(template["candidate_count"], 1)
        self.assertEqual(template["fingerprint_group_count"], 1)
        self.assertEqual(template["selection_reason"], "single_safe_fingerprint_group")
        self.assertEqual(plan["writer_fallback_count"], 0)

    def test_without_caption_filter_many_subtitle_materials_same_fingerprint_all_group(self) -> None:
        fixture = _load("fixtures/real_materials/normal_caption_template.json")
        materials = []
        segments = []
        subtitles = []
        for index in range(1, 6):
            material = copy.deepcopy(fixture["material"])
            segment = copy.deepcopy(fixture["segment"])
            material["id"] = f"sub_{index:03d}"
            segment["id"] = f"seg_{index:03d}"
            segment["material_id"] = material["id"]
            materials.append(material)
            segments.append(segment)
            subtitles.append({"subtitle_uid": f"s{index:03d}", "subtitle_index": index, "text_material_id": material["id"], "text": "字幕"})
        detector_graph = _graph(materials, segments, subtitles)

        material, segment, report = CaptionMaterialWriter().template_detector.detect(detector_graph, captions=[])

        self.assertIsNotNone(material)
        self.assertIsNotNone(segment)
        self.assertEqual(report["candidate_count"], 5)
        self.assertEqual(report["fingerprint_group_count"], 1)

    def test_title_callout_giant_still_rejected_when_related_to_subtitle(self) -> None:
        giant = _load("fixtures/real_materials/giant_title_material.json")
        graph = _graph(
            [giant["material"]],
            [giant["segment"]],
            [{"subtitle_uid": "s001", "subtitle_index": 1, "text": "字幕", "word_ids": ["w1"], "text_material_id": giant["material"]["id"]}],
        )

        plan, blockers = CaptionMaterialWriter().build_write_plan(graph, [_caption()])

        self.assertTrue(blockers)
        self.assertEqual(blockers[0].code, "CAPTION_TEMPLATE_NOT_FOUND")
        self.assertGreater(plan["template_report"]["rejection_summary"]["title_like"] + plan["template_report"]["rejection_summary"]["giant_style"], 0)


if __name__ == "__main__":
    unittest.main()
