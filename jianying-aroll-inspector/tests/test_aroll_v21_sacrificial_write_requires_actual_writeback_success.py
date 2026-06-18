from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aroll_v21.operator import ArollV21OperatorConfig, run_operator
from tests.test_aroll_v21_sacrificial_write_override import (
    FakeAdapter,
    create_disposable_draft,
    fake_real_draft_result,
    fake_real_writeback,
)


def failing_encrypt(_jy_draftc: Path, _plain: Path, _encrypted_out: Path) -> None:
    raise RuntimeError("fake encrypt failed")


def failing_writeback_factory(*args, **kwargs):
    return fake_real_writeback(jy_draftc=kwargs.get("jy_draftc"), encrypt_func=failing_encrypt)


class ArollV21SacrificialWriteRequiresActualWritebackSuccessTests(unittest.TestCase):
    def test_encrypt_failure_blocks_and_does_not_fake_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            with patch(
                "aroll_v21.operator.RealDraftIngestAdapter",
                lambda *a, **k: FakeAdapter(result=fake_real_draft_result(root=root)),
            ), patch("aroll_v21.operator.RealDraftWriteback", failing_writeback_factory):
                summary = run_operator(
                    ArollV21OperatorConfig(
                        mode="write",
                        run_dir=root / "run",
                        draft_dir=draft_dir,
                        commit=True,
                        allow_sacrificial_write_without_postwrite_decrypt=True,
                    )
                )

            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["write_status"], "blocked_writeback_failed")
            self.assertFalse(summary["commit_performed"])
            self.assertIn("V21_WRITEBACK_ENCRYPT_FAILED", summary["blocker_codes"])
            writeback_report = json.loads((root / "run" / "writeback_report.json").read_text("utf-8"))
            self.assertFalse(writeback_report["writeback_success"])
            self.assertEqual(writeback_report["block_reason"], "V21_WRITEBACK_ENCRYPT_FAILED")


if __name__ == "__main__":
    unittest.main()
