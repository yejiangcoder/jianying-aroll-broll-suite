from __future__ import annotations

import unittest

from tools.create_aroll_v21_semantic_decisions_template import build_suggested_for_rough_cut


class ArollV21UnitSplitSemanticTemplateTests(unittest.TestCase):
    def test_suggest_rough_cut_uses_valid_unit_split_suggestion(self) -> None:
        suggested = build_suggested_for_rough_cut(
            [
                {
                    "cluster_id": "repeat_unit_split",
                    "type": "unit_split_requires_human_review",
                    "repeat_type": "unit_split",
                    "allowed_decisions": ["apply_suggested_split", "keep_all", "requires_human_review"],
                    "suggested_for_rough_cut": "apply_suggested_split",
                    "split_summary": {
                        "drop_text": "A",
                        "keep_text": "B",
                        "result_text": "B",
                        "drop_word_ids": ["w1"],
                        "keep_word_ids": ["w2"],
                        "binding": "whole_word",
                    },
                }
            ]
        )

        self.assertEqual(suggested[0]["cluster_id"], "repeat_unit_split")
        self.assertEqual(suggested[0]["decision"], "apply_suggested_split")
        self.assertFalse(suggested[0]["requires_human_review"])

    def test_invalid_unit_split_suggestion_fails_closed_to_human_review(self) -> None:
        suggested = build_suggested_for_rough_cut(
            [
                {
                    "cluster_id": "repeat_unit_split",
                    "type": "unit_split_requires_human_review",
                    "repeat_type": "unit_split",
                    "allowed_decisions": ["keep_all", "requires_human_review"],
                    "suggested_for_rough_cut": "apply_suggested_split",
                }
            ]
        )

        self.assertEqual(suggested[0]["decision"], "requires_human_review")
        self.assertTrue(suggested[0]["requires_human_review"])
        self.assertIn("TEMPLATE_SUGGESTED_DECISION_NOT_ALLOWED", suggested[0]["reason"])

    def test_missing_unit_split_suggestion_with_no_binding_keeps_all(self) -> None:
        suggested = build_suggested_for_rough_cut(
            [
                {
                    "cluster_id": "repeat_unit_split",
                    "type": "unit_split_requires_human_review",
                    "repeat_type": "unit_split",
                    "allowed_decisions": ["apply_suggested_split", "keep_all", "requires_human_review"],
                }
            ]
        )

        self.assertEqual(suggested[0]["decision"], "keep_all")
        self.assertFalse(suggested[0]["requires_human_review"])
        self.assertIn("lacks safe whole-word binding", suggested[0]["reason"])


if __name__ == "__main__":
    unittest.main()
