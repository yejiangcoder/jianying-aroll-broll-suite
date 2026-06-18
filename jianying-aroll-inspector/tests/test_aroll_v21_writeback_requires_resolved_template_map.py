from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.test_aroll_v21_real_writeback_backend import run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


class ArollV21WritebackRequiresResolvedTemplateMapTests(unittest.TestCase):
    def test_commit_blocks_without_resolved_template_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            bound_report = run_report_from_result(result)
            unbound_report = replace(bound_report, resolved_template_map={}, source_binding_report={})

            writeback_result = fake_real_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=unbound_report,
                sacrificial_write_override_used=True,
            )

            self.assertFalse(writeback_result.success)
            self.assertEqual(writeback_result.blockers[0].code, "V21_DYNAMIC_BINDING_REQUIRED")
            self.assertFalse(writeback_result.report["commit_performed"])


if __name__ == "__main__":
    unittest.main()
