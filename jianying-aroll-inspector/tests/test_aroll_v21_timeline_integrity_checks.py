from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_aroll_v21_real_writeback_backend import run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


def raises_timeline_content(*_args, **_kwargs) -> None:
    raise RuntimeError("timeline mismatch")


def raises_layout(*_args, **_kwargs) -> None:
    raise RuntimeError("duplicate ids")


def raises_project_folders(*_args, **_kwargs) -> None:
    raise RuntimeError("folder mismatch")


class ArollV21TimelineIntegrityChecksTests(unittest.TestCase):
    def test_timeline_content_id_mismatch_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)

            writeback_result = fake_real_writeback(timeline_content_check_func=raises_timeline_content).commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertFalse(writeback_result.success)
            self.assertEqual(writeback_result.blockers[0].code, "V21_TIMELINE_CONTENT_ID_MISMATCH")

    def test_layout_duplicate_ids_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)

            writeback_result = fake_real_writeback(layout_check_func=raises_layout).commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertFalse(writeback_result.success)
            self.assertEqual(writeback_result.blockers[0].code, "V21_TIMELINE_LAYOUT_DUPLICATE_IDS")

    def test_project_timeline_folder_mismatch_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)

            writeback_result = fake_real_writeback(project_folder_check_func=raises_project_folders).commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertFalse(writeback_result.success)
            self.assertEqual(writeback_result.blockers[0].code, "V21_PROJECT_TIMELINE_FOLDER_ID_MISMATCH")


if __name__ == "__main__":
    unittest.main()
