from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V21_SRC = ROOT / "src" / "aroll_v21"


class ArollV21NoV20PatchImportsTests(unittest.TestCase):
    def test_v21_does_not_import_legacy_patch_modules(self) -> None:
        text = "\n".join(path.read_text("utf-8") for path in V21_SRC.rglob("*.py"))
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
            "aroll_shared_edit_utils",
        ]
        for token in forbidden:
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
