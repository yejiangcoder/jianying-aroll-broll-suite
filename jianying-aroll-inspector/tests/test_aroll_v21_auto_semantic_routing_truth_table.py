from __future__ import annotations

import unittest

from aroll_v21.decision.semantic_routing_truth_table import (
    V21_AUTO_SEMANTIC_ROUTING_ISSUE_TYPES,
    build_auto_semantic_routing_truth_table,
)


class ArollV21AutoSemanticRoutingTruthTableTests(unittest.TestCase):
    def test_truth_table_covers_all_v21_issue_types(self) -> None:
        rows = build_auto_semantic_routing_truth_table()

        self.assertEqual({row["issue_type"] for row in rows}, set(V21_AUTO_SEMANTIC_ROUTING_ISSUE_TYPES))
        self.assertEqual(
            {row["issue_type"] for row in rows},
            {
                "modifier_redundancy",
                "self_repair_aborted_phrase",
                "semantic_containment",
                "near_duplicate_take",
                "visible_caption_repeat",
                "exact_duplicate",
                "prefix_suffix_overlap",
                "audio_coverage_gap",
                "text_residue",
                "caption_alignment",
                "speed_drift",
            },
        )

    def test_truth_table_has_required_fields_for_every_issue_type(self) -> None:
        required = {
            "issue_type",
            "severity",
            "local_confidence",
            "deterministic_action_available",
            "requires_provider",
            "provider_called_in_auto",
            "provider_missing_behavior",
            "fail_closed",
            "blocker_code",
            "local_only_or_deepseek_or_structural_gate",
        }

        for row in build_auto_semantic_routing_truth_table():
            self.assertEqual(set(row), required)
            self.assertTrue(row["fail_closed"], row)

    def test_structural_issues_do_not_call_deepseek(self) -> None:
        rows = {
            str(row["issue_type"]): row
            for row in build_auto_semantic_routing_truth_table()
        }

        for issue_type in ("audio_coverage_gap", "text_residue", "caption_alignment", "speed_drift"):
            row = rows[issue_type]
            self.assertEqual(row["local_only_or_deepseek_or_structural_gate"], "structural_gate")
            self.assertFalse(row["requires_provider"])
            self.assertFalse(row["provider_called_in_auto"])
            self.assertEqual(row["provider_missing_behavior"], "provider_not_applicable_structural_gate")

    def test_uncertain_high_fatal_semantic_issues_call_deepseek_in_auto(self) -> None:
        rows = {
            str(row["issue_type"]): row
            for row in build_auto_semantic_routing_truth_table()
        }

        for issue_type in (
            "modifier_redundancy",
            "self_repair_aborted_phrase",
            "semantic_containment",
            "near_duplicate_take",
            "visible_caption_repeat",
        ):
            row = rows[issue_type]
            self.assertEqual(row["local_only_or_deepseek_or_structural_gate"], "deepseek")
            self.assertTrue(row["requires_provider"])
            self.assertTrue(row["provider_called_in_auto"])
            self.assertEqual(row["provider_missing_behavior"], "write_blocker_and_semantic_request_payload")


if __name__ == "__main__":
    unittest.main()
