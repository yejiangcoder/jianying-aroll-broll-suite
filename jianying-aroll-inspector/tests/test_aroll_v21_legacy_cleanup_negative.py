from __future__ import annotations

import unittest
from pathlib import Path

from tools.package_aroll_v21_audit_zip import INCLUDE_FILES, should_include
from tools.export_aroll_v21_uat_capsule import V21_ARTIFACT_NAMES


ROOT = Path(__file__).resolve().parents[1]


class ArollV21LegacyCleanupNegativeTests(unittest.TestCase):
    def test_removed_legacy_entrypoints_stay_absent(self) -> None:
        removed = (
            "run_aroll_operator.ps1",
            "run_aroll_uat_full.ps1",
            "run_aroll_phase4e_full_aroll.ps1",
            "run_aroll_decision_dryrun.ps1",
            "src/aroll_phase4e_full_aroll.py",
            "src/aroll_downstream_repair_pipeline.py",
            "src/aroll_repair_applier.py",
            "src/aroll_word_edl_builder.py",
            "tools/export_uat_capsule.py",
            "tests/fixtures/production_parity/fresh_uat_cjk_mixed_blockers/manifest.json",
        )
        existing = [path for path in removed if (ROOT / path).exists()]
        self.assertEqual(existing, [])

    def test_v21_audit_package_does_not_name_removed_legacy_entrypoints(self) -> None:
        forbidden = {
            "run_aroll_operator.ps1",
            "run_aroll_uat_full.ps1",
            "run_aroll_phase4e_full_aroll.ps1",
            "aroll_operator_profile.json",
        }
        self.assertFalse(forbidden & set(INCLUDE_FILES))
        self.assertIn("run_aroll_v21_operator.ps1", INCLUDE_FILES)

    def test_v21_audit_package_excludes_repo_cache_and_temp_reports(self) -> None:
        forbidden_paths = (
            ".git/config",
            ".idea/workspace.xml",
            ".pytest_cache/v/cache/nodeids",
            "src/aroll_v21/__pycache__/engine.cpython-311.pyc",
            "src/aroll_v21/engine.pyc",
            "migration_dry_run_report.md",
            "migration_dry_run_report.json",
            "project_tree_scan_report.md",
            "project_tree_scan_report.json",
            "runtime_migration_plan.md",
            "runtime_migration_plan.json",
        )

        included = [path for path in forbidden_paths if should_include(ROOT / path, ROOT)]

        self.assertEqual(included, [])

    def test_v21_capsule_exporter_does_not_accept_legacy_artifact_names(self) -> None:
        legacy_artifacts = {
            "full_video_edl.initial.json",
            "full_video_edl.json",
            "full_display_subtitle_plan.initial.json",
            "full_display_subtitle_plan.json",
            "display_subtitle_plan.json",
            "downstream_repair_pipeline_report.json",
            "downstream_gate_report.json",
        }
        self.assertFalse(legacy_artifacts & set(V21_ARTIFACT_NAMES))
        self.assertIn("final_edl.json", V21_ARTIFACT_NAMES)
        self.assertIn("captions.json", V21_ARTIFACT_NAMES)


if __name__ == "__main__":
    unittest.main()
