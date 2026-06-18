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


class ArollV21CaptionTemplateRealRound4RejectionCaseTests(unittest.TestCase):
    def test_many_subtitle_bound_title_like_materials_are_not_all_rejected(self) -> None:
        fixture = _load("fixtures/real_materials/normal_caption_template.json")
        materials: list[dict] = []
        segments: list[dict] = []
        subtitles: list[dict] = []
        words: list[dict] = []
        captions: list[CaptionRenderUnit] = []
        for index in range(1, 118):
            material = copy.deepcopy(fixture["material"])
            segment = copy.deepcopy(fixture["segment"])
            material["id"] = f"round4_text_{index:03d}"
            material["role"] = "title"
            material["name"] = "round4 center title-like subtitle"
            segment["id"] = f"round4_segment_{index:03d}"
            segment["type"] = "title"
            segment["material_id"] = material["id"]
            subtitle_uid = f"s{index:03d}"
            word_id = f"w{index:03d}"
            materials.append(material)
            segments.append(segment)
            subtitles.append(
                {
                    "subtitle_uid": subtitle_uid,
                    "subtitle_index": index,
                    "text": "字幕",
                    "word_ids": [word_id],
                    "text_material_id": material["id"],
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
                    text="字幕",
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
        self.assertEqual(report["rejection_summary"]["title_like"], 0)
        self.assertEqual(report["title_like_reasons"]["position_center_title_like"], 117)
        self.assertEqual(plan["writer_fallback_count"], 0)
        self.assertTrue(plan["materials"])
        self.assertTrue(plan["segments"])


if __name__ == "__main__":
    unittest.main()
