from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21.operator import ArollV21OperatorConfig, run_operator


class ArollV21RealIngestBlockContractTests(unittest.TestCase):
    def test_input_json_cannot_masquerade_as_real_draft_when_draft_dir_is_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_json = root / "input.json"
            draft_dir = root / "draft"
            draft_dir.mkdir()
            input_json.write_text(json.dumps({"word_timeline": [], "subtitles": []}), "utf-8")
            summary = run_operator(
                ArollV21OperatorConfig(
                    mode="dry-run",
                    run_dir=root / "run",
                    input_json=input_json,
                    draft_dir=draft_dir,
                )
            )
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["blocker_codes"], ["REAL_DRAFT_INPUT_JSON_NOT_ALLOWED_WITH_DRAFT_DIR"])

    def test_missing_draft_dir_is_explicit_real_ingest_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = run_operator(ArollV21OperatorConfig(mode="dry-run", run_dir=root / "run", draft_dir=root / "missing"))
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["blocker_codes"], ["REAL_DRAFT_REQUIRED_FILE_MISSING"])

    def test_real_draft_mode_without_any_source_is_explicit_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = run_operator(ArollV21OperatorConfig(mode="dry-run", run_dir=root / "run"))
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["blocker_codes"], ["REAL_DRAFT_DIR_REQUIRED"])


if __name__ == "__main__":
    unittest.main()
