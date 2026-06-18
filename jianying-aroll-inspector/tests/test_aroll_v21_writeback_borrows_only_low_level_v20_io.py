from __future__ import annotations

import unittest
from pathlib import Path


class ArollV21WritebackBorrowsOnlyLowLevelV20IoTests(unittest.TestCase):
    def test_writeback_uses_jy_bridge_encrypt_without_v20_patch_imports(self) -> None:
        path = Path("src/aroll_v21/writeback/real_draft_writeback.py")
        text = path.read_text("utf-8")
        self.assertIn("from jy_bridge import", text)
        self.assertIn("DEFAULT_JY_DRAFTC", text)
        self.assertIn("encrypt", text)
        self.assertIn("assert_timeline_content_id", text)
        forbidden = (
            "aroll_phase4e_full_aroll",
            "aroll_uat_full",
            "aroll_downstream_repair_pipeline",
            "aroll_repair_applier",
            "aroll_safe_cut_boundary_resolver",
            "material_text_rows",
        )
        for token in forbidden:
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
