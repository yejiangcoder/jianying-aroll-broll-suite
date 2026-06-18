from __future__ import annotations

import unittest

from aroll_final_repeat_gate import build_final_repeat_gate_report
from aroll_v21.ir import DecisionPlan
from aroll_v21.validate.validators import ReadOnlyValidators


def _display_rows(texts: list[str]) -> list[dict]:
    rows = []
    cursor = 0
    for index, text in enumerate(texts, start=1):
        duration = max(200_000, len(text) * 40_000)
        rows.append(
            {
                "fragment_id": f"cap_{index:06d}",
                "fragment_text": text,
                "text": text,
                "target_start_us": cursor,
                "target_duration_us": duration,
                "word_ids": [f"w_{index:06d}"],
            }
        )
        cursor += duration
    return rows


class ArollV21FinalTargetRepeatValidatorIntegrationTests(unittest.TestCase):
    def test_keep_all_semantic_trace_makes_medium_candidate_non_fatal(self) -> None:
        report = build_final_repeat_gate_report({"issues": []}, _display_rows(["甲乙丙丁", "过渡句", "甲乙丙丁戊己庚辛"]))
        plan = DecisionPlan(
            decisions=[],
            final_target_repeat_accepted_cluster_ids=["final_target_repeat_tc_0001"],
        )

        updated = ReadOnlyValidators()._final_repeat_semantic_status(report, plan)

        self.assertTrue(updated["final_repeat_gate_passed"])
        self.assertEqual(updated["final_target_repeat_accepted_count"], 1)
        self.assertEqual(updated["final_target_repeat_medium_count"], 0)
        self.assertEqual(updated["final_target_repeat_candidates"][0]["v21_resolution"], "accepted_by_semantic_decision")

    def test_unresolved_medium_candidate_is_not_final_repeat_fatal_but_is_tracked(self) -> None:
        report = build_final_repeat_gate_report({"issues": []}, _display_rows(["甲乙丙丁", "过渡句", "甲乙丙丁戊己庚辛"]))
        plan = DecisionPlan(
            decisions=[],
            final_target_repeat_unresolved_cluster_ids=["final_target_repeat_tc_0001"],
            semantic_unresolved_count=1,
            write_allowed=False,
        )

        updated = ReadOnlyValidators()._final_repeat_semantic_status(report, plan)

        self.assertTrue(updated["final_repeat_gate_passed"])
        self.assertEqual(updated["final_target_repeat_semantic_unresolved_count"], 1)
        self.assertEqual(updated["final_target_repeat_medium_count"], 0)
        self.assertEqual(updated["final_target_repeat_candidates"][0]["v21_resolution"], "semantic_unresolved_write_blocker")

    def test_uncovered_medium_candidate_remains_blocking(self) -> None:
        report = build_final_repeat_gate_report({"issues": []}, _display_rows(["甲乙丙丁", "过渡句", "甲乙丙丁戊己庚辛"]))

        updated = ReadOnlyValidators()._final_repeat_semantic_status(report, DecisionPlan(decisions=[]))

        self.assertFalse(updated["final_repeat_gate_passed"])
        self.assertEqual(updated["final_target_repeat_medium_count"], 1)
        self.assertEqual(updated["final_target_repeat_candidates"][0]["v21_resolution"], "fatal_uncovered_medium")

    def test_high_exact_duplicate_not_removed_remains_fatal(self) -> None:
        report = build_final_repeat_gate_report({"issues": []}, _display_rows(["把输掉的", "把输掉的"]))

        updated = ReadOnlyValidators()._final_repeat_semantic_status(report, DecisionPlan(decisions=[]))

        self.assertFalse(updated["final_repeat_gate_passed"])
        self.assertEqual(updated["final_target_repeat_high_count"], 1)
        self.assertEqual(updated["final_target_repeat_candidates"][0]["v21_resolution"], "fatal_unresolved_high")


if __name__ == "__main__":
    unittest.main()
