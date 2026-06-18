from __future__ import annotations

import unittest

from aroll_v21.decision import SemanticDecisionPlanner
from aroll_v21.ir import CandidateEvidence, EditUnit, RepeatCluster


def _semantic_cluster() -> RepeatCluster:
    unit = EditUnit(
        unit_id="unit_1",
        word_ids=["w1", "w2"],
        text="修饰词堆叠样例",
        normalized_text="修饰词堆叠样例",
        source_start_us=0,
        source_end_us=1000000,
        subtitle_uids=["s1"],
        source_material_ids=["main_video"],
        kind="sentence",
        cut_policy="word_boundary",
    )
    evidence = CandidateEvidence(
        evidence_id="e1",
        evidence_type="modifier_redundancy",
        unit_ids=["unit_1"],
        word_ids=["w1", "w2"],
        text=unit.text,
        normalized_text=unit.normalized_text,
        reason="semantic redundancy requires planner decision",
        confidence=0.72,
        requires_semantic_decision=True,
        metadata={"local_evidence": "adjacent_modifier"},
    )
    return RepeatCluster(
        cluster_id="cluster_1",
        variants=[unit],
        repeat_type="modifier_redundancy",
        evidence=[evidence],
        local_recommendation="semantic_review",
    )


class MockPlanner:
    def decide(self, clusters):
        return [
            {
                "cluster_id": clusters[0].cluster_id,
                "keep_unit_id": clusters[0].variants[0].unit_id,
                "drop_unit_ids": [],
                "reason": "explicit test planner keeps the unit",
                "confidence": 0.81,
                "requires_human_review": True,
            }
        ]


class PhysicalFieldPlanner:
    def decide(self, clusters):
        return [
            {
                "cluster_id": clusters[0].cluster_id,
                "keep_unit_id": clusters[0].variants[0].unit_id,
                "drop_unit_ids": [],
                "reason": "invalid",
                "confidence": 0.9,
                "requires_human_review": False,
                "source_start_us": 1,
            }
        ]


class ArollV21SemanticPlannerContractTests(unittest.TestCase):
    def test_deepseek_missing_emits_request_payload_and_trace(self) -> None:
        plan = SemanticDecisionPlanner().plan([_semantic_cluster()])

        codes = [blocker.code for blocker in plan.blockers]
        self.assertFalse(plan.blocked)
        self.assertFalse(plan.write_allowed)
        self.assertTrue(plan.requires_human_review)
        self.assertIn("DEEPSEEK_SEMANTIC_PLANNER_NOT_CONFIGURED", codes)
        self.assertNotIn("SEMANTIC_DECISION_REQUIRED", codes)
        self.assertEqual(plan.blockers[0].severity, "write_blocker")
        self.assertEqual(len(plan.semantic_request_payloads), 1)
        self.assertEqual(plan.semantic_request_payloads[0]["cluster_id"], "cluster_1")
        self.assertTrue(plan.decision_trace)
        self.assertIn("deepseek_required", {row["route"] for row in plan.decision_trace})
        self.assertIn("self_review", {row["route"] for row in plan.decision_trace})

    def test_mock_semantic_decision_requires_explicit_planner(self) -> None:
        plan = SemanticDecisionPlanner(deepseek_planner=MockPlanner()).plan([_semantic_cluster()])

        self.assertFalse(plan.blocked, [blocker.code for blocker in plan.blockers])
        self.assertEqual(len(plan.decisions), 1)
        self.assertEqual(plan.decisions[0].source, "deepseek_semantic_planner")
        self.assertEqual(plan.semantic_request_payloads, [])

    def test_deepseek_physical_fields_still_block(self) -> None:
        plan = SemanticDecisionPlanner(deepseek_planner=PhysicalFieldPlanner()).plan([_semantic_cluster()])

        self.assertTrue(plan.blocked)
        self.assertIn("DEEPSEEK_DECISION_HAS_PHYSICAL_FIELDS", [blocker.code for blocker in plan.blockers])
        self.assertIn("blocked", {row["route"] for row in plan.decision_trace})


if __name__ == "__main__":
    unittest.main()
