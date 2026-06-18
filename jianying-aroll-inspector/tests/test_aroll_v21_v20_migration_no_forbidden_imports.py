from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ArollV21V20MigrationNoForbiddenImportsTests(unittest.TestCase):
    def test_writeback_does_not_import_v20_patch_modules(self) -> None:
        source = (ROOT / "src" / "aroll_v21" / "writeback" / "real_draft_writeback.py").read_text("utf-8")
        forbidden = [
            "aroll_phase4e_full_aroll",
            "aroll_uat_full",
            "aroll_downstream_repair_pipeline",
            "aroll_repair_applier",
            "aroll_safe_cut_boundary_resolver",
            "material_text_rows",
            "run_downstream_repair_pipeline",
            "apply_repair_proposals",
            "resolve_safe_cut_boundaries",
        ]
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_writeback_uses_jy_bridge_low_level_io_only(self) -> None:
        source = (ROOT / "src" / "aroll_v21" / "writeback" / "real_draft_writeback.py").read_text("utf-8")
        self.assertIn("from jy_bridge import", source)
        self.assertIn("encrypt", source)
        self.assertIn("root_mirrors_timeline_id", source)
        self.assertIn("assert_timeline_content_id", source)


if __name__ == "__main__":
    unittest.main()
