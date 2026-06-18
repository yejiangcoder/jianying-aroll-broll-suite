from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput


ROOT = Path(__file__).resolve().parents[1]


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text("utf-8"))


class ArollV21Round4WriterValidatorReachableTests(unittest.TestCase):
    def test_round4_like_title_bound_templates_reach_writer_and_validators(self) -> None:
        fixture = _load("fixtures/real_materials/normal_caption_template.json")
        words: list[dict] = []
        subtitles: list[dict] = []
        materials: list[dict] = []
        segments: list[dict] = []
        for index in range(1, 138):
            subtitle_uid = f"s{index:03d}"
            word_id = f"w{index:03d}"
            text = "随意的肆意的踩踏" if index == 1 else "普通字幕"
            material = copy.deepcopy(fixture["material"])
            segment = copy.deepcopy(fixture["segment"])
            material["id"] = f"round4_text_{index:03d}"
            material["role"] = "title"
            material["name"] = "round4 center title-like subtitle"
            segment["id"] = f"round4_segment_{index:03d}"
            segment["type"] = "title"
            segment["material_id"] = material["id"]
            start = (index - 1) * 400000
            end = start + 350000
            words.append(
                {
                    "word_id": word_id,
                    "word_text": text,
                    "source_start_us": start,
                    "source_end_us": end,
                    "source_material_id": "main_video",
                    "source_segment_id": "clip",
                    "subtitle_uid": subtitle_uid,
                    "subtitle_index": index,
                }
            )
            subtitles.append(
                {
                    "subtitle_uid": subtitle_uid,
                    "subtitle_index": index,
                    "text": text,
                    "word_ids": [word_id],
                    "text_material_id": material["id"],
                }
            )
            materials.append(material)
            segments.append(segment)

        report = ArollEngine().run(
            ArollRunInput(
                word_timeline=words,
                subtitles=subtitles,
                source_segments=[{"id": "clip", "material_id": "main_video", "source_start_us": 0, "source_end_us": 60000000}],
                text_materials=materials,
                text_segments=segments,
                postwrite_mode="simulated",
            )
        )

        self.assertEqual(report.material_write_plan["writer_fallback_count"], 0)
        self.assertTrue(report.material_write_plan["materials"])
        self.assertTrue(report.material_write_plan["segments"])
        self.assertIn("validator_report_ok", report.validator_report)
        self.assertTrue(report.validator_report["validators_read_only"])
        self.assertGreater(report.decision_plan.semantic_unresolved_count, 0)
        self.assertFalse(report.blocker_report.summary["write_allowed"])


if __name__ == "__main__":
    unittest.main()
