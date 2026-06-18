from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21.operator import ArollV21OperatorConfig, run_operator


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: str):
    return json.loads((ROOT / path).read_text("utf-8"))


def write_input(path: Path, *, malformed: bool = False) -> None:
    material = load_json("fixtures/real_materials/malformed_content_json.json" if malformed else "fixtures/real_materials/normal_caption_template.json")
    payload = {
        "source_segments": [{"id": "clip", "material_id": "main_video_a", "source_start_us": 0, "source_end_us": 1000000}],
        "word_timeline": [
            {"word_id": "w001", "word_text": "测试", "start_us": 100000, "end_us": 400000, "subtitle_index": 1, "subtitle_uid": "s001"}
        ],
        "subtitles": [{"subtitle_uid": "s001", "subtitle_index": 1, "text": "测试", "word_ids": ["w001"]}],
        "text_materials": [material["material"]],
        "text_segments": [material["segment"]],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")


class ArollV21CommitGatingTests(unittest.TestCase):
    def test_commit_flag_cannot_bypass_missing_actual_write_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_json = root / "input.json"
            write_input(input_json)
            summary = run_operator(ArollV21OperatorConfig(mode="write", run_dir=root / "run", input_json=input_json, commit=True))
            self.assertEqual(summary["status"], "blocked")
            self.assertFalse(summary["commit_performed"])
            self.assertTrue(summary["commit_only_after_all_validators"])

    def test_prewrite_validator_block_prevents_write_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_json = root / "input.json"
            write_input(input_json, malformed=True)
            summary = run_operator(ArollV21OperatorConfig(mode="write", run_dir=root / "run", input_json=input_json, simulate_write=True))
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["write_status"], "blocked_by_prewrite_validators")
            self.assertFalse(summary["commit_performed"])


if __name__ == "__main__":
    unittest.main()
