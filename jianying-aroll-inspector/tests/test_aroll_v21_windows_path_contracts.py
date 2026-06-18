from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aroll_v21.operator import ArollV21OperatorConfig, run_operator

from tests.test_aroll_v21_full_chain_internal_self_check import ExternalWordTimelineAdapter
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


class ArollV21WindowsPathContractsTests(unittest.TestCase):
    def test_paths_with_spaces_and_chinese_are_preserved_in_summary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="路径 with spaces ") as tmp:
            root = Path(tmp)
            draft_parent = root / "剪映 Draft Parent"
            draft_parent.mkdir()
            draft_dir, _draft_content, _template = create_disposable_draft(draft_parent)
            run_dir = root / "run dir 中文"
            jy_draftc = root / "jy draftc 中文" / "jy-draftc.exe"
            result = fake_real_draft_result(root=draft_parent)
            with patch(
                "aroll_v21.operator.RealDraftIngestAdapter",
                lambda *a, **k: ExternalWordTimelineAdapter(result=result),
            ), patch(
                "aroll_v21.operator.RealDraftWriteback",
                lambda *a, **k: fake_real_writeback(jy_draftc=k.get("jy_draftc")),
            ):
                summary = run_operator(
                    ArollV21OperatorConfig(
                        mode="write",
                        run_dir=run_dir,
                        draft_dir=draft_dir,
                        jy_draftc=jy_draftc,
                        commit=True,
                        allow_sacrificial_write_without_postwrite_decrypt=True,
                    )
                )

            self.assertEqual(summary["status"], "ok")
            self.assertEqual(summary["draft_dir"], str(draft_dir))
            self.assertEqual(summary["jy_draftc_path"], str(jy_draftc))
            persisted = json.loads((run_dir / "run_summary.json").read_text("utf-8"))
            self.assertEqual(persisted["draft_dir"], str(draft_dir))
            self.assertEqual(persisted["jy_draftc_path"], str(jy_draftc))

    def test_v21_code_does_not_use_shell_string_for_writeback_paths(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = "\n".join(
            [
                (root / "src" / "aroll_v21" / "operator.py").read_text("utf-8"),
                (root / "src" / "aroll_v21" / "writeback" / "real_draft_writeback.py").read_text("utf-8"),
            ]
        )
        self.assertNotIn("shell=True", source)
        self.assertNotIn("Start-Process", source)
        self.assertNotIn("cmd /c", source.lower())


if __name__ == "__main__":
    unittest.main()
