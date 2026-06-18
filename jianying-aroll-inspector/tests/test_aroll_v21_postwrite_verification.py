from __future__ import annotations

import json
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: str):
    return json.loads((ROOT / path).read_text("utf-8"))


def normal_material_rows():
    payload = load_json("fixtures/real_materials/normal_caption_template.json")
    return [payload["material"]], [payload["segment"]]


def base_input(**kwargs) -> ArollRunInput:
    text_materials, text_segments = normal_material_rows()
    data = {
        "source_segments": [{"id": "clip", "material_id": "main_video_a", "source_start_us": 0, "source_end_us": 1000000}],
        "word_timeline": [{"word_id": "w001", "word_text": "测试", "start_us": 100000, "end_us": 400000, "subtitle_index": 1, "subtitle_uid": "s001"}],
        "subtitles": [{"subtitle_uid": "s001", "subtitle_index": 1, "text": "测试", "word_ids": ["w001"]}],
        "text_materials": text_materials,
        "text_segments": text_segments,
    }
    data.update(kwargs)
    return ArollRunInput(**data)


class ArollV21PostwriteVerificationTests(unittest.TestCase):
    def test_without_real_decrypt_postwrite_mode_is_simulated(self) -> None:
        report = ArollEngine().run(base_input())
        postwrite = report.postwrite_report
        self.assertEqual(report.status, "ok")
        self.assertEqual(postwrite["postwrite_mode"], "simulated")
        self.assertFalse(postwrite["postwrite_decrypt_ok"])
        self.assertFalse(postwrite["real_uat_verified"])
        self.assertEqual(postwrite["content_schema_error_count"], 0)

    def test_actual_postwrite_materials_are_reported_as_actual_decrypt_input(self) -> None:
        pre = ArollEngine().run(base_input())
        materials = pre.material_write_plan["materials"]
        report = ArollEngine().run(base_input(postwrite_materials=materials))
        postwrite = report.postwrite_report
        self.assertEqual(postwrite["postwrite_mode"], "actual_decrypt")
        self.assertTrue(postwrite["postwrite_decrypt_ok"])
        self.assertTrue(postwrite["real_uat_verified"])
        self.assertEqual(postwrite["content_schema_error_count"], 0)

    def test_malformed_postwrite_material_blocks_with_schema_error(self) -> None:
        malformed = load_json("fixtures/real_materials/malformed_content_json.json")["material"]
        report = ArollEngine().run(base_input(postwrite_materials=[malformed]))
        self.assertEqual(report.status, "blocked")
        postwrite = report.postwrite_report
        self.assertEqual(postwrite["postwrite_mode"], "actual_decrypt")
        self.assertGreater(postwrite["content_schema_error_count"], 0)
        self.assertFalse(postwrite["postwrite_material_gate_ok"])


if __name__ == "__main__":
    unittest.main()
