from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput


ROOT = Path(__file__).resolve().parents[1]


class ArollV21WriterValidatorReachableAfterTemplateDetectionTests(unittest.TestCase):
    def test_writer_and_validator_reachable_with_real_subtitle_template_group(self) -> None:
        fixture = json.loads((ROOT / "fixtures" / "real_materials" / "normal_caption_template.json").read_text("utf-8"))
        material_a = copy.deepcopy(fixture["material"])
        material_b = copy.deepcopy(fixture["material"])
        segment_a = copy.deepcopy(fixture["segment"])
        segment_b = copy.deepcopy(fixture["segment"])
        material_b["id"] = "caption_template_002"
        segment_b["id"] = "caption_segment_002"
        segment_b["material_id"] = material_b["id"]

        report = ArollEngine().run(
            ArollRunInput(
                source_segments=[{"id": "clip", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000000}],
                word_timeline=[
                    {"word_id": "w1", "word_text": "随意的肆意的踩踏", "start_us": 0, "end_us": 1000000, "subtitle_uid": "s1", "subtitle_index": 1}
                ],
                subtitles=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": "随意的肆意的踩踏", "word_ids": ["w1"], "text_material_id": material_a["id"]}],
                text_materials=[material_a, material_b],
                text_segments=[segment_a, segment_b],
                postwrite_mode="simulated",
            )
        )

        self.assertTrue(report.final_timeline)
        self.assertTrue(report.captions)
        self.assertTrue(report.material_write_plan.get("materials"))
        self.assertIn("validator_report_ok", report.validator_report)
        self.assertTrue(report.validator_report["validators_read_only"])
        self.assertEqual(report.decision_plan.semantic_unresolved_count, 1)
        self.assertEqual(report.blocker_report.summary["write_allowed"], False)


if __name__ == "__main__":
    unittest.main()
