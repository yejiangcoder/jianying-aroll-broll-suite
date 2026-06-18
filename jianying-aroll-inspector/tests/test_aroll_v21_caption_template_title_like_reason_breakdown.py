from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from aroll_v21.ingest import DraftIngest
from aroll_v21.writer import CaptionMaterialWriter


ROOT = Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text("utf-8"))


class ArollV21CaptionTemplateTitleLikeReasonBreakdownTests(unittest.TestCase):
    def test_non_subtitle_title_like_rejection_has_reason_breakdown(self) -> None:
        fixture = _load("fixtures/real_materials/normal_caption_template.json")
        material = copy.deepcopy(fixture["material"])
        segment = copy.deepcopy(fixture["segment"])
        material["role"] = "title"
        material["name"] = "center headline text"
        segment["type"] = "title"
        graph = DraftIngest().build_source_graph(
            word_timeline=[],
            subtitles=[],
            source_segments=[{"id": "clip", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000000}],
            text_materials=[material],
            text_segments=[segment],
        )

        _material, _segment, report = CaptionMaterialWriter().template_detector.detect(graph, captions=[])

        self.assertEqual(report["candidate_count"], 0)
        self.assertEqual(report["rejection_summary"]["title_like"], 1)
        self.assertEqual(report["title_like_reasons"]["position_center_title_like"], 1)
        self.assertTrue(report["sample_rejections"])

    def test_giant_rejection_breaks_down_font_scale_and_occupancy_reasons(self) -> None:
        fixture = _load("fixtures/real_materials/giant_title_material.json")
        graph = DraftIngest().build_source_graph(
            word_timeline=[],
            subtitles=[],
            source_segments=[{"id": "clip", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000000}],
            text_materials=[fixture["material"]],
            text_segments=[fixture["segment"]],
        )

        _material, _segment, report = CaptionMaterialWriter().template_detector.detect(graph, captions=[])

        self.assertEqual(report["candidate_count"], 0)
        self.assertEqual(report["rejection_summary"]["title_like"], 1)
        self.assertGreaterEqual(report["title_like_reasons"]["position_center_title_like"], 1)


if __name__ == "__main__":
    unittest.main()
