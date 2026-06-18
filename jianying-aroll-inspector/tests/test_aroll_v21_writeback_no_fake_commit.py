from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from aroll_v21.operator import ArollV21OperatorConfig, run_operator

from tests.test_aroll_v21_sacrificial_write_override import FakeAdapter, create_disposable_draft, fake_real_draft_result


class ArollV21WritebackNoFakeCommitTests(unittest.TestCase):
    def test_commit_flag_without_sacrificial_writeback_backend_still_does_not_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path

            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            with patch(
                "aroll_v21.operator.RealDraftIngestAdapter",
                lambda *a, **k: FakeAdapter(result=fake_real_draft_result(root=root)),
            ):
                summary = run_operator(
                    ArollV21OperatorConfig(
                        mode="write",
                        run_dir=root / "run",
                        draft_dir=draft_dir,
                        commit=True,
                    )
                )

            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["write_status"], "blocked_actual_decrypt_unavailable")
            self.assertFalse(summary["commit_performed"])
            self.assertFalse(summary["writeback_success"])


if __name__ == "__main__":
    unittest.main()
