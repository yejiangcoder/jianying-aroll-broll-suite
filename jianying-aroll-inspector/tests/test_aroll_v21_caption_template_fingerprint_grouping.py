from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from aroll_v21.ir import CaptionRenderUnit
from aroll_v21.writer import CaptionMaterialWriter

from tests.test_aroll_v21_real_materials import build_graph, load_json


def _caption() -> CaptionRenderUnit:
    return CaptionRenderUnit(
        caption_id="cap",
        timeline_segment_ids=["seg"],
        word_ids=["w001"],
        text="输出字幕",
        target_start_us=0,
        target_end_us=1000000,
        source_subtitle_uids=["s001"],
        style_template_id="canonical_caption_template",
    )


class ArollV21CaptionTemplateFingerprintGroupingTests(unittest.TestCase):
    def test_multiple_safe_caption_materials_with_same_fingerprint_pass(self) -> None:
        fixture = load_json("fixtures/real_materials/normal_caption_template.json")
        material_a = copy.deepcopy(fixture["material"])
        segment_a = copy.deepcopy(fixture["segment"])
        material_b = copy.deepcopy(fixture["material"])
        segment_b = copy.deepcopy(fixture["segment"])
        material_b["id"] = "caption_template_002"
        segment_b["id"] = "caption_segment_002"
        segment_b["material_id"] = "caption_template_002"
        graph = build_graph([material_a, material_b], [segment_a, segment_b])
        plan, blockers = CaptionMaterialWriter().build_write_plan(graph, [_caption()])
        self.assertFalse(blockers)
        template = plan["canonical_caption_template"]
        self.assertEqual(template["candidate_count"], 2)
        self.assertEqual(template["fingerprint_group_count"], 1)
        self.assertEqual(template["selection_reason"], "single_safe_fingerprint_group")
        self.assertEqual(plan["writer_fallback_count"], 0)

    def test_multiple_safe_caption_materials_with_different_fingerprints_block(self) -> None:
        fixture = load_json("fixtures/real_materials/normal_caption_template.json")
        material_a = copy.deepcopy(fixture["material"])
        segment_a = copy.deepcopy(fixture["segment"])
        material_b = copy.deepcopy(fixture["material"])
        segment_b = copy.deepcopy(fixture["segment"])
        material_b["id"] = "caption_template_variant"
        material_b["font_size"] = 48
        content = json.loads(material_b["content"])
        content["styles"][0]["font_size"] = 48
        material_b["content"] = json.dumps(content, ensure_ascii=False)
        material_b["base_content"] = json.dumps(content, ensure_ascii=False)
        segment_b["id"] = "caption_segment_variant"
        segment_b["material_id"] = "caption_template_variant"
        graph = build_graph([material_a, material_b], [segment_a, segment_b])
        plan, blockers = CaptionMaterialWriter().build_write_plan(graph, [_caption()])
        self.assertTrue(blockers)
        self.assertEqual(blockers[0].code, "CAPTION_TEMPLATE_AMBIGUOUS")
        self.assertEqual(plan["writer_fallback_count"], 0)

    def test_title_callout_and_giant_materials_are_rejected_before_grouping(self) -> None:
        normal = load_json("fixtures/real_materials/normal_caption_template.json")
        giant = load_json("fixtures/real_materials/giant_title_material.json")
        callout = load_json("fixtures/real_materials/callout_text_material.json")
        graph = build_graph([normal["material"], giant["material"], callout["material"]], [normal["segment"], giant["segment"], callout["segment"]])
        plan, blockers = CaptionMaterialWriter().build_write_plan(graph, [_caption()])
        self.assertFalse(blockers)
        self.assertEqual(plan["canonical_caption_template"]["candidate_count"], 1)
        self.assertEqual(plan["canonical_caption_template"]["rejected_count"], 2)

    def test_no_legal_caption_template_blocks_without_fallback(self) -> None:
        giant = load_json("fixtures/real_materials/giant_title_material.json")
        graph = build_graph([giant["material"]], [giant["segment"]])
        plan, blockers = CaptionMaterialWriter().build_write_plan(graph, [_caption()])
        self.assertTrue(blockers)
        self.assertEqual(blockers[0].code, "CAPTION_TEMPLATE_NOT_FOUND")
        self.assertEqual(plan["writer_fallback_count"], 0)


if __name__ == "__main__":
    unittest.main()
