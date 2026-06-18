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


def _caption() -> CaptionRenderUnit:
    return CaptionRenderUnit(
        caption_id="cap",
        timeline_segment_ids=["seg"],
        word_ids=["w1"],
        text="字幕",
        target_start_us=0,
        target_end_us=1000000,
        source_subtitle_uids=["s1"],
        style_template_id="canonical_caption_template",
    )


class ArollV21CaptionTemplateRejectionDiagnosticsTests(unittest.TestCase):
    def test_all_rejected_outputs_summary_and_samples(self) -> None:
        malformed = _load("fixtures/real_materials/malformed_content_json.json")
        graph = DraftIngest().build_source_graph(
            word_timeline=[{"word_id": "w1", "word_text": "字幕", "start_us": 0, "end_us": 100000, "subtitle_uid": "s1", "subtitle_index": 1}],
            subtitles=[
                {
                    "subtitle_uid": "s1",
                    "subtitle_index": 1,
                    "text": "字幕",
                    "word_ids": ["w1"],
                    "text_material_id": malformed["material"]["id"],
                }
            ],
            source_segments=[{"id": "clip", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000000}],
            text_materials=[malformed["material"]],
            text_segments=[malformed["segment"]],
        )

        plan, blockers = CaptionMaterialWriter().build_write_plan(graph, [_caption()])

        self.assertTrue(blockers)
        report = plan["template_report"]
        self.assertEqual(report["candidate_count"], 0)
        self.assertEqual(report["rejected_count"], 1)
        self.assertEqual(report["rejection_summary"]["content_schema_unsafe"], 1)
        self.assertTrue(report["sample_rejections"])

    def test_ambiguous_fingerprint_is_reported(self) -> None:
        fixture = _load("fixtures/real_materials/normal_caption_template.json")
        material_a = copy.deepcopy(fixture["material"])
        segment_a = copy.deepcopy(fixture["segment"])
        material_b = copy.deepcopy(fixture["material"])
        segment_b = copy.deepcopy(fixture["segment"])
        material_b["id"] = "caption_variant"
        material_b["font_size"] = 48
        content = json.loads(material_b["content"])
        content["styles"][0]["font_size"] = 48
        material_b["content"] = json.dumps(content, ensure_ascii=False)
        material_b["base_content"] = json.dumps(content, ensure_ascii=False)
        segment_b["id"] = "seg_variant"
        segment_b["material_id"] = material_b["id"]
        graph = DraftIngest().build_source_graph(
            word_timeline=[{"word_id": "w1", "word_text": "字幕", "start_us": 0, "end_us": 100000, "subtitle_uid": "s1", "subtitle_index": 1}],
            subtitles=[
                {"subtitle_uid": "s1", "subtitle_index": 1, "text": "字幕", "word_ids": ["w1"], "text_material_id": material_a["id"]},
                {"subtitle_uid": "s2", "subtitle_index": 2, "text": "字幕", "text_material_id": material_b["id"]},
            ],
            source_segments=[{"id": "clip", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000000}],
            text_materials=[material_a, material_b],
            text_segments=[segment_a, segment_b],
        )

        _material, _segment, report = CaptionMaterialWriter().template_detector.detect(graph, captions=[])

        self.assertEqual(report["fingerprint_group_count"], 2)
        self.assertEqual(report["rejection_summary"]["fingerprint_ambiguous"], 2)
        self.assertEqual(report["blockers"][0]["code"], "CAPTION_TEMPLATE_AMBIGUOUS")


if __name__ == "__main__":
    unittest.main()
