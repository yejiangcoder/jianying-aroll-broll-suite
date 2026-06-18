from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = [ROOT / "src" / "aroll_v21", ROOT / "run_aroll_v21_operator.ps1"]


def iter_lines():
    paths: list[Path] = []
    for root in SCAN_ROOTS:
        if root.is_file():
            paths.append(root)
        else:
            paths.extend(root.rglob("*.py"))
    for path in paths:
        rel = path.relative_to(ROOT).as_posix()
        for number, line in enumerate(path.read_text("utf-8").splitlines(), start=1):
            yield rel, number, line


class ArollV21StaticHiddenBugScanTests(unittest.TestCase):
    def test_forbidden_v20_patch_symbols_absent(self) -> None:
        text = "\n".join(line for _rel, _number, line in iter_lines())
        for token in (
            "aroll_phase4e_full_aroll",
            "aroll_uat_full",
            "downstream_repair",
            "repair_applier",
            "safe_cut_boundary_resolver",
            "material_text_rows",
            "validator repair",
            "writer fallback",
        ):
            self.assertNotIn(token, text)

    def test_high_risk_patterns_are_allowlisted(self) -> None:
        allowed_except_files = {
            "src/aroll_v21/operator.py",
            "src/aroll_v21/ingest/real_draft_adapter.py",
            "src/aroll_v21/ingest/external_word_timeline_adapter.py",
            "src/aroll_v21/ingest/draft_native_word_timeline_discovery.py",
            "src/aroll_v21/writer/caption_material_writer.py",
            "src/aroll_v21/writeback/real_draft_writeback.py",
            "src/aroll_v21/writeback/dynamic_source_binding_preflight.py",
        }
        allowed_return_empty = {
            "src/aroll_v21/operator.py",
            "src/aroll_v21/decision/semantic_decision_planner.py",
            "src/aroll_v21/decision/final_target_repeat_resolver.py",
            "src/aroll_v21/evidence/repeat_cluster_builder.py",
            "src/aroll_v21/ingest/draft_native_word_timeline_discovery.py",
            "src/aroll_v21/ingest/real_draft_adapter.py",
            "src/aroll_v21/ingest/source_graph.py",
            "src/aroll_v21/writeback/real_draft_writeback.py",
            "src/aroll_v21/writeback/source_segment_template_resolver.py",
            "src/aroll_v21/writeback/speed_resolver.py",
            "src/aroll_v21/writer/subtitle_identity_resolver.py",
        }
        allowed_success_assignments = {
            "src/aroll_v21/engine.py",
            "src/aroll_v21/operator.py",
            "src/aroll_v21/validate/validators.py",
            "src/aroll_v21/writeback/real_draft_writeback.py",
        }
        findings: list[str] = []
        for rel, number, line in iter_lines():
            stripped = line.strip()
            lowered = stripped.lower()
            if "except exception" in lowered and rel not in allowed_except_files:
                findings.append(f"{rel}:{number}: unexpected broad exception: {stripped}")
            if stripped in {"return {}", "return []", "return None"} and rel not in allowed_return_empty:
                findings.append(f"{rel}:{number}: unexpected empty return: {stripped}")
            if "commit_performed = true" in lowered and rel not in allowed_success_assignments:
                findings.append(f"{rel}:{number}: commit success assignment outside allowlist: {stripped}")
            if 'write_status = "success"' in lowered:
                findings.append(f"{rel}:{number}: ambiguous success write_status: {stripped}")
            if 'write_status = "committed"' in lowered:
                findings.append(f"{rel}:{number}: ambiguous committed write_status: {stripped}")
            if "ready_for_user_manual_qc" in lowered and "true" in lowered and rel not in allowed_success_assignments:
                findings.append(f"{rel}:{number}: manual QC true outside allowlist: {stripped}")
            if "tracks[0]" in lowered or 'data["tracks"][0]' in lowered or "first text track" in lowered or "first video track" in lowered:
                findings.append(f"{rel}:{number}: first-track indexing/text is forbidden: {stripped}")
        self.assertEqual(findings, [])


if __name__ == "__main__":
    unittest.main()
