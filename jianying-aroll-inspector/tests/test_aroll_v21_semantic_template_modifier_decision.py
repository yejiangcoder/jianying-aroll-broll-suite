from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.create_aroll_v21_semantic_decisions_template import build_suggested_for_rough_cut, main


PHYSICAL_FIELDS = {
    "source_start_us",
    "source_end_us",
    "target_start_us",
    "target_end_us",
    "edl",
    "final_edl",
    "draft_content",
    "material_id",
    "segment_id",
}


class ArollV21SemanticTemplateModifierDecisionTests(unittest.TestCase):
    def test_modifier_redundancy_payload_suggests_drop_redundant_modifier(self) -> None:
        suggested = build_suggested_for_rough_cut(
            [
                {
                    "cluster_id": "repeat_002000",
                    "repeat_type": "modifier_redundancy",
                    "type": "single_variant_modifier_redundancy",
                    "allowed_decisions": [
                        "drop_redundant_modifier",
                        "keep_all",
                        "requires_human_review",
                    ],
                    "suggested_for_rough_cut": "drop_redundant_modifier",
                }
            ]
        )

        self.assertEqual(suggested[0]["cluster_id"], "repeat_002000")
        self.assertEqual(suggested[0]["decision"], "drop_redundant_modifier")
        self.assertFalse(suggested[0]["requires_human_review"])

    def test_invalid_suggested_decision_fails_closed(self) -> None:
        suggested = build_suggested_for_rough_cut(
            [
                {
                    "cluster_id": "repeat_002000",
                    "repeat_type": "modifier_redundancy",
                    "type": "single_variant_modifier_redundancy",
                    "allowed_decisions": ["keep_all", "requires_human_review"],
                    "suggested_for_rough_cut": "drop_redundant_modifier",
                }
            ]
        )

        self.assertEqual(suggested[0]["decision"], "requires_human_review")
        self.assertTrue(suggested[0]["requires_human_review"])
        self.assertIn("suggested_for_rough_cut", suggested[0]["reason"])

    def test_old_modifier_payload_without_explicit_suggestion_remains_compatible(self) -> None:
        suggested = build_suggested_for_rough_cut(
            [
                {
                    "cluster_id": "repeat_legacy",
                    "repeat_type": "modifier_redundancy",
                }
            ]
        )

        self.assertEqual(suggested[0]["decision"], "drop_redundant_modifier")
        self.assertFalse(suggested[0]["requires_human_review"])

    def test_suggested_decision_output_has_no_physical_fields(self) -> None:
        suggested = build_suggested_for_rough_cut(
            [
                {
                    "cluster_id": "repeat_002000",
                    "repeat_type": "modifier_redundancy",
                    "type": "single_variant_modifier_redundancy",
                    "allowed_decisions": ["drop_redundant_modifier", "keep_all"],
                    "suggested_for_rough_cut": "drop_redundant_modifier",
                    "source_start_us": 1,
                    "source_end_us": 2,
                    "material_id": "forbidden_source_payload_field",
                }
            ]
        )

        self.assertFalse(PHYSICAL_FIELDS & set(suggested[0]))

    def test_cli_suggest_rough_cut_writes_drop_redundant_modifier_to_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload_path = root / "semantic_request_payloads.json"
            output_path = root / "semantic_decisions.roughcut_current_suggested.json"
            payload_path.write_text(
                json.dumps(
                    [
                        {
                            "cluster_id": "repeat_002000",
                            "repeat_type": "modifier_redundancy",
                            "type": "single_variant_modifier_redundancy",
                            "allowed_decisions": [
                                "drop_redundant_modifier",
                                "keep_all",
                                "requires_human_review",
                            ],
                            "suggested_for_rough_cut": "drop_redundant_modifier",
                        }
                    ],
                    ensure_ascii=False,
                ),
                "utf-8",
            )

            import sys

            old_argv = sys.argv
            try:
                sys.argv = ["create", str(payload_path), "-o", str(output_path), "--suggest-rough-cut"]
                self.assertEqual(main(), 0)
            finally:
                sys.argv = old_argv

            decisions = json.loads(output_path.read_text("utf-8"))
            self.assertEqual(decisions[0]["cluster_id"], "repeat_002000")
            self.assertEqual(decisions[0]["decision"], "drop_redundant_modifier")


if __name__ == "__main__":
    unittest.main()
