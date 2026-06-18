from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.aroll_v21_contract_assertions import assert_run_summary_contract
from tests.test_aroll_v21_real_writeback_backend import run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


class ArollV21NoFakeSuccessContractTests(unittest.TestCase):
    def test_contract_rejects_ok_status_with_blocker_codes(self) -> None:
        summary = {
            "status": "ok",
            "write_status": "committed",
            "write_allowed": True,
            "semantic_unresolved_count": 0,
            "validator_write_allowed": True,
            "commit_performed": True,
            "writeback_success": True,
            "ready_for_user_manual_qc": True,
            "writer_fallback_count": 0,
            "blocker_codes": ["SHOULD_NOT_EXIST"],
        }
        with self.assertRaises(AssertionError):
            assert_run_summary_contract(self, summary, writeback_report={"target_writes": {"draft_content.json": True}})

    def test_contract_rejects_commit_without_writeback_success(self) -> None:
        summary = {
            "status": "ok",
            "write_status": "committed",
            "write_allowed": True,
            "semantic_unresolved_count": 0,
            "validator_write_allowed": True,
            "commit_performed": True,
            "writeback_success": False,
            "ready_for_user_manual_qc": False,
            "writer_fallback_count": 0,
            "blocker_codes": [],
        }
        with self.assertRaises(AssertionError):
            assert_run_summary_contract(self, summary)

    def test_material_write_plan_missing_blocks_writeback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = replace(run_report_from_result(result), material_write_plan={})
            writeback_result = fake_real_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )
            self.assertFalse(writeback_result.success)
            self.assertEqual(writeback_result.blockers[0].code, "V21_WRITEBACK_MATERIAL_PLAN_EMPTY")

    def test_empty_final_timeline_blocks_writeback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = replace(run_report_from_result(result), final_timeline=[])
            writeback_result = fake_real_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )
            self.assertFalse(writeback_result.success)
            self.assertEqual(writeback_result.blockers[0].code, "V21_DYNAMIC_BINDING_REQUIRED")


if __name__ == "__main__":
    unittest.main()
