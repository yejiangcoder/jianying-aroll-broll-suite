from __future__ import annotations

import unittest
import zipfile
from pathlib import Path

from tools.package_aroll_v21_audit_zip import INCLUDE_FILES, build_zip, should_include
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
            "config/deepseek.yaml",
            "config/runtime_paths.local.yaml",
            ".env",
            ".env.local",
            "reports/run_report.json",
            "logs/writeback.log",
            "release/aroll.zip",
            "dev_snapshot/snapshot.zip",
            "cache/tmp.json",
            "outputs/render.mp4",
        )

        included = [path for path in forbidden_paths if should_include(ROOT / path, ROOT)]

        self.assertEqual(included, [])

    def test_v21_audit_package_builds_clean_zip(self) -> None:
        with self.subTest("forbidden paths are omitted from actual archive"):
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                output_zip = repo / "out" / "aroll_v21_audit.zip"
                allowed = repo / "src" / "aroll_v21" / "engine.py"
                allowed.parent.mkdir(parents=True)
                allowed.write_text("print('ok')\n", "utf-8")
                for rel in (
                    ".git/config",
                    ".idea/workspace.xml",
                    ".pytest_cache/v/cache/nodeids",
                    "src/aroll_v21/__pycache__/engine.cpython-311.pyc",
                    "config/deepseek.yaml",
                    "config/deepseek.local.yaml",
                    "config/runtime_paths.local.yaml",
                    ".env",
                    "reports/run_report.json",
                    "logs/writeback.log",
                    "runtime/run_summary.json",
                ):
                    path = repo / rel
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("forbidden\n", "utf-8")

                names = build_zip(repo, output_zip)

                with zipfile.ZipFile(output_zip) as archive:
                    archived_names = set(archive.namelist())

                self.assertIn("src/aroll_v21/engine.py", archived_names)
                self.assertEqual(names, sorted(names))
                self.assertFalse(
                    {
                        ".git/config",
                        ".idea/workspace.xml",
                        ".pytest_cache/v/cache/nodeids",
                        "src/aroll_v21/__pycache__/engine.cpython-311.pyc",
                        "config/deepseek.yaml",
                        "config/deepseek.local.yaml",
                        "config/runtime_paths.local.yaml",
                        ".env",
                        "reports/run_report.json",
                        "logs/writeback.log",
                        "runtime/run_summary.json",
                    }
                    & archived_names
                )

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
