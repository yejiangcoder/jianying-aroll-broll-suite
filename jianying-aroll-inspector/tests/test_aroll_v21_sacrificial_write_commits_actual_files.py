from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aroll_v21.operator import ArollV21OperatorConfig, run_operator

from tests.test_aroll_v21_sacrificial_write_override import (
    FakeAdapter,
    create_disposable_draft,
    fake_real_draft_result,
    fake_writeback_factory,
)


class ArollV21SacrificialWriteCommitsActualFilesTests(unittest.TestCase):
    def test_successful_sacrificial_write_changes_both_timeline_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, template = create_disposable_draft(root)
            old_draft = draft_content.read_text("utf-8")
            old_template = template.read_text("utf-8")
            with patch(
                "aroll_v21.operator.RealDraftIngestAdapter",
                lambda *a, **k: FakeAdapter(result=fake_real_draft_result(root=root)),
            ), patch("aroll_v21.operator.RealDraftWriteback", fake_writeback_factory):
                summary = run_operator(
                    ArollV21OperatorConfig(
                        mode="write",
                        run_dir=root / "run",
                        draft_dir=draft_dir,
                        commit=True,
                        allow_sacrificial_write_without_postwrite_decrypt=True,
                    )
                )

            self.assertEqual(summary["status"], "ok")
            self.assertTrue(summary["commit_performed"])
            self.assertNotEqual(draft_content.read_text("utf-8"), old_draft)
            self.assertNotEqual(template.read_text("utf-8"), old_template)
            self.assertTrue((root / "run" / "writeback_report.json").exists())


if __name__ == "__main__":
    unittest.main()
