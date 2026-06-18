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


class ArollV21ActualPostwriteContractTests(unittest.TestCase):
    def test_verify_only_with_supplied_postwrite_materials_uses_actual_decrypt_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_json = root / "input.json"
            dry_run_dir = root / "dry"
            write_input(input_json)
            dry = run_operator(ArollV21OperatorConfig(mode="dry-run", run_dir=dry_run_dir, input_json=input_json))
            self.assertEqual(dry["status"], "ok")
            materials = json.loads((dry_run_dir / "material_write_plan.json").read_text("utf-8"))["materials"]
            postwrite_json = root / "postwrite_materials.json"
            postwrite_json.write_text(json.dumps(materials, ensure_ascii=False), "utf-8")

            summary = run_operator(
                ArollV21OperatorConfig(
                    mode="verify-only",
                    run_dir=root / "verify",
                    input_json=input_json,
                    postwrite_materials_json=postwrite_json,
                )
            )
            self.assertEqual(summary["status"], "ok")
            self.assertEqual(summary["postwrite_mode"], "actual_decrypt")
            self.assertTrue(summary["postwrite_decrypt_ok"])
            self.assertEqual(summary["write_status"], "verify_only_passed")

    def test_verify_only_without_supplied_postwrite_materials_is_unavailable_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_json = root / "input.json"
            write_input(input_json)
            summary = run_operator(ArollV21OperatorConfig(mode="verify-only", run_dir=root / "verify", input_json=input_json))
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["postwrite_mode"], "unavailable")
            self.assertFalse(summary["postwrite_decrypt_ok"])


if __name__ == "__main__":
    unittest.main()
