from __future__ import annotations

import json
import unittest
from pathlib import Path

from aroll_v21 import ArollRunInput
from aroll_v21.ingest import DraftIngest
from aroll_v21.ir import CaptionRenderUnit
from aroll_v21.writer import CaptionMaterialWriter


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: str):
    return json.loads((ROOT / path).read_text("utf-8"))


def normal_caption():
    payload = load_json("fixtures/real_materials/normal_caption_template.json")
    return payload["material"], payload["segment"]


def build_graph(text_materials, text_segments):
    return DraftIngest().build_source_graph(
        word_timeline=[
            {
                "word_id": "w001",
                "word_text": "测试字幕",
                "start_us": 100000,
                "end_us": 500000,
                "subtitle_index": 1,
                "subtitle_uid": "s001",
            }
        ],
        subtitles=[{"subtitle_uid": "s001", "subtitle_index": 1, "text": "测试字幕", "word_ids": ["w001"]}],
        source_segments=[{"id": "clip", "material_id": "main_video_a", "source_start_us": 0, "source_end_us": 1000000}],
        text_materials=text_materials,
        text_segments=text_segments,
    )


def caption(text="更新字幕"):
    return CaptionRenderUnit(
        caption_id="cap001",
        timeline_segment_ids=["seg001"],
        word_ids=["w001"],
        text=text,
        target_start_us=0,
        target_end_us=1000000,
        source_subtitle_uids=["s001"],
        style_template_id="canonical_caption_template",
    )


class ArollV21RealMaterialTests(unittest.TestCase):
    def test_title_callout_and_giant_materials_cannot_be_caption_template(self) -> None:
        normal_material, normal_segment = normal_caption()
        giant = load_json("fixtures/real_materials/giant_title_material.json")
        callout = load_json("fixtures/real_materials/callout_text_material.json")
        graph = build_graph(
            [giant["material"], callout["material"], normal_material],
            [giant["segment"], callout["segment"], normal_segment],
        )
        plan, blockers = CaptionMaterialWriter().build_write_plan(graph, [caption()])
        self.assertFalse(blockers)
        self.assertEqual(plan["canonical_caption_template_id"], "caption_template_001")
        self.assertEqual(plan["writer_fallback_count"], 0)

    def test_title_like_caption_confusion_selects_only_real_caption(self) -> None:
        fixture = load_json("fixtures/real_materials/title_like_caption_confusion.json")
        graph = build_graph(fixture["materials"], fixture["segments"])
        plan, blockers = CaptionMaterialWriter().build_write_plan(graph, [caption()])
        self.assertFalse(blockers)
        self.assertEqual(plan["canonical_caption_template_id"], "real_caption_001")

    def test_malformed_content_template_is_blocked_without_fallback(self) -> None:
        malformed = load_json("fixtures/real_materials/malformed_content_json.json")
        graph = build_graph([malformed["material"]], [malformed["segment"]])
        plan, blockers = CaptionMaterialWriter().build_write_plan(graph, [caption()])
        self.assertTrue(blockers)
        self.assertEqual(blockers[0].code, "CAPTION_TEMPLATE_NOT_FOUND")
        self.assertEqual(plan["writer_fallback_count"], 0)

    def test_content_and_base_content_remain_json_with_consistent_fingerprint(self) -> None:
        normal_material, normal_segment = normal_caption()
        graph = build_graph([normal_material], [normal_segment])
        plan, blockers = CaptionMaterialWriter().build_write_plan(graph, [caption("新的字幕文本")])
        self.assertFalse(blockers)
        material = plan["materials"][0]
        content = json.loads(material["content"])
        base_content = json.loads(material["base_content"])
        self.assertEqual(content["text"], "新的字幕文本")
        self.assertEqual(base_content["text"], "新的字幕文本")
        self.assertTrue(content["styles"])
        self.assertEqual(plan["writer_fallback_count"], 0)
        self.assertEqual(len(set(plan["output_material_fingerprints"])), 1)


if __name__ == "__main__":
    unittest.main()
