from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_aroll_v21_real_writeback_backend import run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


def root_mirror_required(_draft_dir: Path, _jy_draftc: Path, _run_dir: Path, _timeline_id: str) -> bool:
    return True


def root_mirror_raises(_draft_dir: Path, _jy_draftc: Path, _run_dir: Path, _timeline_id: str) -> bool:
    raise RuntimeError("mirror check unavailable")


class ArollV21WritebackRootMirrorTargetTests(unittest.TestCase):
    def test_root_mirror_required_writes_root_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, template = create_disposable_draft(root)
            root_draft = draft_dir / "draft_content.json"
            root_template = draft_dir / "template-2.tmp"
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)

            writeback_result = fake_real_writeback(root_mirror_func=root_mirror_required).commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            self.assertTrue(writeback_result.report["root_mirror_required"])
            self.assertTrue(writeback_result.report["root_mirror_written"])
            for target in (draft_content, template, root_draft, root_template):
                self.assertTrue(writeback_result.report["target_writes"][str(target)])
                self.assertTrue(target.exists())

    def test_root_mirror_check_failure_blocks_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)

            writeback_result = fake_real_writeback(root_mirror_func=root_mirror_raises).commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertFalse(writeback_result.success)
            self.assertEqual(writeback_result.blockers[0].code, "V21_WRITEBACK_ROOT_MIRROR_DETECTION_FAILED")
            self.assertTrue(writeback_result.report["root_mirror_check_failed"])
            self.assertIsNone(writeback_result.report["root_mirror_required"])
            self.assertEqual(writeback_result.report["target_writes"], {})
            self.assertNotIn(str(draft_dir / "draft_content.json"), writeback_result.report["target_writes"])


if __name__ == "__main__":
    unittest.main()
