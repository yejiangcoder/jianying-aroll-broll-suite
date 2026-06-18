from __future__ import annotations

import unittest

from aroll_v21.decision.semantic_decision_planner import SemanticDecisionPlanner
from aroll_v21.ir.models import CandidateEvidence, EditUnit, RepeatCluster
from aroll_v21.operator import DeterministicBaselineSemanticPlanner


class ArollV21SemanticBaselineUatPathTests(unittest.TestCase):
    def test_deterministic_baseline_semantic_mode_refuses_medium_semantic_retry(self) -> None:
        unit = EditUnit(
            "u1",
            ["w1"],
            "测试",
            "测试",
            0,
            500_000,
            ["s1"],
            [],
            "sentence",
            "word_boundary",
        )
        cluster = RepeatCluster(
            "cluster_semantic",
            [unit],
            "semantic_retry",
            [
                CandidateEvidence(
                    "e1",
                    "semantic_retry",
                    ["u1"],
                    ["w1"],
                    "测试",
                    "测试",
                    "semantic review required",
                    0.8,
                    True,
                )
            ],
            None,
        )

        planner = SemanticDecisionPlanner(deepseek_planner=DeterministicBaselineSemanticPlanner())
        decision_plan = planner.plan([cluster])

        self.assertFalse(decision_plan.blocked)
        self.assertEqual(decision_plan.decisions, [])
        self.assertEqual(decision_plan.semantic_unresolved_count, 1)
        self.assertFalse(decision_plan.write_allowed)
        self.assertEqual(decision_plan.semantic_adjudication_report["deterministic_baseline_refused_count"], 1)
        self.assertNotIn("keep_all", str(decision_plan.semantic_decision_rows))

    def test_semantic_decisions_are_not_reused_from_old_draft(self) -> None:
        planner = DeterministicBaselineSemanticPlanner()

        self.assertEqual(planner.rows, [])


if __name__ == "__main__":
    unittest.main()
