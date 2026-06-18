from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V21_SRC = ROOT / "src" / "aroll_v21"
V21_ENTRY = ROOT / "run_aroll_v21_operator.ps1"


def v21_text() -> str:
    return "\n".join([*(path.read_text("utf-8") for path in V21_SRC.rglob("*.py")), V21_ENTRY.read_text("utf-8")])


class ArollV21NoArchitectureDriftTests(unittest.TestCase):
    def test_no_v20_patch_modules_or_patch_entrypoints(self) -> None:
        text = v21_text()
        for token in (
            "aroll_phase4e_full_aroll",
            "aroll_uat_full",
            "aroll_downstream_repair_pipeline",
            "aroll_repair_applier",
            "aroll_safe_cut_boundary_resolver",
            "material_text_rows",
            "run_downstream_repair_pipeline",
            "apply_repair_proposals",
            "resolve_safe_cut_boundaries",
        ):
            self.assertNotIn(token, text)

    def test_no_fixup_or_downstream_style_logic_in_v21(self) -> None:
        text = v21_text().lower()
        for token in ("auto_fix", "fixup", "downstream_repair", "safe_cut_expand", "validator repair", "writer fallback"):
            self.assertNotIn(token, text)

    def test_fallback_mentions_are_only_no_writer_contract_fields_or_block_messages(self) -> None:
        lines = [line.strip() for line in v21_text().splitlines() if "fallback" in line.lower()]
        for line in lines:
            lowered = line.lower()
            self.assertTrue(
                "no_writer_fallback" in lowered
                or "writer_fallback_count" in lowered
                or "without fallback" in lowered
                or "fallback is forbidden" in lowered
                or "fallback_policy" in lowered
                or "fail-closed fallback" in lowered,
                line,
            )


if __name__ == "__main__":
    unittest.main()
