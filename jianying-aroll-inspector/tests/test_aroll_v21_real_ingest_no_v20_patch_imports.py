from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ArollV21RealIngestNoV20PatchImportsTests(unittest.TestCase):
    def test_real_ingest_adapter_does_not_import_v20_patch_modules(self) -> None:
        text = (ROOT / "src" / "aroll_v21" / "ingest" / "real_draft_adapter.py").read_text("utf-8")
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
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
