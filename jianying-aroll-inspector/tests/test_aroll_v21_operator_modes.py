from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21.operator import ArollV21OperatorConfig, run_operator


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: str):
    return json.loads((ROOT / path).read_text("utf-8"))


def write_input(path: Path) -> None:
    material = load_json("fixtures/real_materials/normal_caption_template.json")
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


class ArollV21OperatorModeTests(unittest.TestCase):
    def test_dry_run_writes_reports_without_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_json = root / "input.json"
            write_input(input_json)
            summary = run_operator(ArollV21OperatorConfig(mode="dry-run", run_dir=root / "run", input_json=input_json))
            self.assertEqual(summary["status"], "ok")
            self.assertEqual(summary["write_status"], "dry_run_no_write")
            self.assertFalse(summary["commit_performed"])

    def test_write_without_actual_decrypt_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_json = root / "input.json"
            write_input(input_json)
            summary = run_operator(ArollV21OperatorConfig(mode="write", run_dir=root / "run", input_json=input_json))
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["write_status"], "blocked_actual_decrypt_unavailable")
            self.assertEqual(summary["postwrite_mode"], "unavailable")
            self.assertFalse(summary["postwrite_decrypt_ok"])

    def test_write_simulation_is_explicit_and_does_not_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_json = root / "input.json"
            write_input(input_json)
            summary = run_operator(
                ArollV21OperatorConfig(mode="write", run_dir=root / "run", input_json=input_json, simulate_write=True)
            )
            self.assertEqual(summary["status"], "ok")
            self.assertEqual(summary["write_status"], "simulated_write_no_commit")
            self.assertEqual(summary["postwrite_mode"], "simulated_write")
            self.assertFalse(summary["commit_performed"])

    def test_verify_only_without_postwrite_materials_blocks_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_json = root / "input.json"
            write_input(input_json)
            summary = run_operator(ArollV21OperatorConfig(mode="verify-only", run_dir=root / "run", input_json=input_json))
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["write_status"], "verify_only_blocked")
            self.assertEqual(summary["postwrite_mode"], "unavailable")


if __name__ == "__main__":
    unittest.main()
