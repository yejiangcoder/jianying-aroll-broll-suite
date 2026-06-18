from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.validate_aroll_v21_word_timeline import normalize_word_timeline_payload


ROOT = Path(__file__).resolve().parents[1]


class ArollV21WordTimelineToolsTests(unittest.TestCase):
    def test_normalizer_maps_common_word_fields(self) -> None:
        normalized, report = normalize_word_timeline_payload(
            [{"word_text": "你", "start_us": 100, "end_us": 200, "source_material_id": "m1"}]
        )

        self.assertTrue(report["ok"])
        self.assertEqual(normalized[0]["text"], "你")
        self.assertEqual(normalized[0]["source_start_us"], 100)
        self.assertEqual(normalized[0]["source_end_us"], 200)

    def test_missing_required_fields_fail(self) -> None:
        normalized, report = normalize_word_timeline_payload([{"text": "你", "start_us": 100}])

        self.assertEqual(normalized, [])
        self.assertFalse(report["ok"])
        self.assertEqual(report["errors"][0]["code"], "WORD_TIMELINE_REQUIRED_FIELD_MISSING")

    def test_subtitle_as_word_is_forbidden(self) -> None:
        normalized, report = normalize_word_timeline_payload(
            [{"type": "subtitle", "text": "整句字幕", "source_start_us": 0, "source_end_us": 1000}]
        )

        self.assertEqual(normalized, [])
        self.assertFalse(report["ok"])
        self.assertEqual(report["errors"][0]["code"], "SUBTITLE_AS_WORD_TIMELINE_FORBIDDEN")

    def test_cli_writes_normalization_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "words.json"
            output_path = root / "normalized.json"
            report_path = root / "report.json"
            input_path.write_text(json.dumps([{"token": "好", "start_us": 0, "end_us": 100}]), "utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "validate_aroll_v21_word_timeline.py"),
                    "--input",
                    str(input_path),
                    "--normalized-output",
                    str(output_path),
                    "--report-output",
                    str(report_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(report_path.read_text("utf-8"))["ok"])
            self.assertEqual(json.loads(output_path.read_text("utf-8"))["word_timeline"][0]["text"], "好")


if __name__ == "__main__":
    unittest.main()
