from __future__ import annotations

import unittest

from aroll_v21.decision import SemanticDecisionPlanner, SemanticDecisionsJsonPlanner
from aroll_v21.ir import CandidateEvidence, EditUnit, RepeatCluster
from tests.test_aroll_v21_semantic_planner_contract import _semantic_cluster


def _non_modifier_semantic_cluster() -> RepeatCluster:
    unit = EditUnit(
        unit_id="unit_keep",
        word_ids=["w1"],
        text="普通语义待判定",
        normalized_text="普通语义待判定",
        source_start_us=0,
        source_end_us=500_000,
        subtitle_uids=["s1"],
        source_material_ids=["main_video"],
        kind="sentence",
        cut_policy="word_boundary",
    )
    evidence = CandidateEvidence(
        evidence_id="e_keep",
        evidence_type="semantic_retry",
        unit_ids=[unit.unit_id],
        word_ids=list(unit.word_ids),
        text=unit.text,
        normalized_text=unit.normalized_text,
        reason="generic semantic decision",
        confidence=0.7,
        requires_semantic_decision=True,
    )
    return RepeatCluster(
        cluster_id="cluster_keep",
        variants=[unit],
        repeat_type="semantic_retry",
        evidence=[evidence],
        local_recommendation="semantic_review",
    )


class ArollV21SemanticDecisionsJsonTests(unittest.TestCase):
    def test_keep_all_modifier_decision_blocks_fatal_modifier_redundancy(self) -> None:
        cluster = _semantic_cluster()
        planner = SemanticDecisionPlanner(
            deepseek_planner=SemanticDecisionsJsonPlanner(
                [
                    {
                        "cluster_id": cluster.cluster_id,
                        "decision": "keep_all",
                        "reason": "not confidently redundant",
                        "confidence": 0.8,
                        "requires_human_review": False,
                    }
                ]
            )
        )

        plan = planner.plan([cluster])

        self.assertFalse(plan.blocked, [blocker.code for blocker in plan.blockers])
        self.assertEqual(plan.semantic_unresolved_count, 1)
        self.assertFalse(plan.write_allowed)
        self.assertIn("V21_FATAL_MODIFIER_REDUNDANCY_UNRESOLVED", [blocker.code for blocker in plan.blockers])
        self.assertEqual(plan.decisions, [])
        self.assertEqual(len(plan.semantic_request_payloads), 1)

    def test_keep_all_non_modifier_semantic_decision_resolves_without_dropping(self) -> None:
        cluster = _non_modifier_semantic_cluster()
        planner = SemanticDecisionPlanner(
            deepseek_planner=SemanticDecisionsJsonPlanner(
                [
                    {
                        "cluster_id": cluster.cluster_id,
                        "decision": "keep_all",
                        "reason": "not confidently redundant",
                        "confidence": 0.8,
                        "requires_human_review": False,
                    }
                ]
            )
        )

        plan = planner.plan([cluster])

        self.assertFalse(plan.blocked, [blocker.code for blocker in plan.blockers])
        self.assertEqual(plan.semantic_unresolved_count, 0)
        self.assertTrue(plan.write_allowed)
        self.assertEqual(plan.decisions[0].source, "semantic_decisions_json")
        self.assertEqual(plan.decisions[0].drop_unit_ids, [])
        self.assertEqual(plan.semantic_request_payloads, [])

    def test_partial_semantic_decisions_keep_write_blocked(self) -> None:
        cluster_a = _semantic_cluster()
        cluster_b = _semantic_cluster()
        cluster_b = type(cluster_b)(
            cluster_id="cluster_2",
            variants=cluster_b.variants,
            repeat_type=cluster_b.repeat_type,
            evidence=cluster_b.evidence,
            local_recommendation=cluster_b.local_recommendation,
        )
        planner = SemanticDecisionPlanner(
            deepseek_planner=SemanticDecisionsJsonPlanner(
                [{"cluster_id": cluster_a.cluster_id, "decision": "keep_all", "reason": "covered", "confidence": 0.8}]
            )
        )

        plan = planner.plan([cluster_a, cluster_b])

        self.assertFalse(plan.write_allowed)
        self.assertEqual(plan.semantic_unresolved_count, 2)
        self.assertIn("SEMANTIC_DECISION_NOT_PROVIDED", [blocker.code for blocker in plan.blockers])


if __name__ == "__main__":
    unittest.main()
