from __future__ import annotations

import unittest

from aroll_v21 import ArollEngine
from aroll_v21.ir import Blocker, DecisionPlan


class ArollV21SemanticRequestConsistencyGateTests(unittest.TestCase):
    def test_missing_request_for_validator_modifier_fatal_blocks_internally(self) -> None:
        validator_report = {
            "final_repeat_validator": {
                "final_repeat_gate_passed": False,
                "blocking_issues": [
                    {
                        "type": "adjacent_modifier_semantic_redundancy",
                        "text": "快乐的开心的孩子",
                        "phrase": "快乐的开心的孩子",
                    }
                ],
            },
            "hidden_audio_repeat_validator": {"hidden_audio_repeat_gate_passed": True, "blocking_issues": []},
        }

        blockers = ArollEngine()._semantic_request_consistency_blockers(DecisionPlan(decisions=[]), validator_report)

        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0].code, "INTERNAL_SEMANTIC_REQUEST_MISSING_FOR_FATAL_REPEAT")

    def test_matching_modifier_request_satisfies_consistency_gate(self) -> None:
        plan = DecisionPlan(
            decisions=[],
            semantic_request_payloads=[
                {
                    "cluster_id": "repeat_002000",
                    "repeat_type": "modifier_redundancy",
                    "type": "single_variant_modifier_redundancy",
                    "text": "快乐的开心的孩子",
                }
            ],
        )
        validator_report = {
            "final_repeat_validator": {
                "final_repeat_gate_passed": False,
                "blocking_issues": [
                    {
                        "type": "adjacent_modifier_semantic_redundancy",
                        "text": "快乐的开心的孩子",
                        "phrase": "快乐的开心的孩子",
                    }
                ],
            },
            "hidden_audio_repeat_validator": {"hidden_audio_repeat_gate_passed": True, "blocking_issues": []},
        }

        blockers = ArollEngine()._semantic_request_consistency_blockers(plan, validator_report)

        self.assertEqual(blockers, [])

    def test_missing_request_for_unit_split_human_review_blocks_internally(self) -> None:
        plan = DecisionPlan(
            decisions=[],
            blockers=[
                Blocker(
                    code="UNIT_SPLIT_REQUIRES_HUMAN_REVIEW",
                    message="unit split needs semantic review",
                    layer="decision",
                    context={"cluster_id": "repeat_unit_split"},
                )
            ],
            semantic_request_payloads=[],
        )

        blockers = ArollEngine()._semantic_request_consistency_blockers(plan, {})

        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0].code, "INTERNAL_SEMANTIC_REQUEST_MISSING_FOR_UNIT_SPLIT")
        self.assertEqual(blockers[0].context["cluster_id"], "repeat_unit_split")

    def test_matching_unit_split_request_satisfies_consistency_gate(self) -> None:
        plan = DecisionPlan(
            decisions=[],
            blockers=[
                Blocker(
                    code="UNIT_SPLIT_REQUIRES_HUMAN_REVIEW",
                    message="unit split needs semantic review",
                    layer="decision",
                    context={"cluster_id": "repeat_unit_split"},
                )
            ],
            semantic_request_payloads=[
                {
                    "cluster_id": "repeat_unit_split",
                    "type": "unit_split_requires_human_review",
                    "repeat_type": "unit_split",
                    "suggested_for_rough_cut": "apply_suggested_split",
                }
            ],
        )

        blockers = ArollEngine()._semantic_request_consistency_blockers(plan, {})

        self.assertEqual(blockers, [])

    def test_missing_request_for_semantic_decision_not_provided_blocks_internally(self) -> None:
        plan = DecisionPlan(
            decisions=[],
            blockers=[
                Blocker(
                    code="SEMANTIC_DECISION_NOT_PROVIDED",
                    message="semantic decisions json does not cover this unresolved cluster",
                    layer="decision",
                    severity="write_blocker",
                    context={"cluster_id": "repeat_missing"},
                )
            ],
            semantic_request_payloads=[],
        )

        blockers = ArollEngine()._semantic_request_consistency_blockers(plan, {})

        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0].code, "INTERNAL_SEMANTIC_REQUEST_MISSING_FOR_DECISION_NOT_PROVIDED")
        self.assertEqual(blockers[0].context["cluster_id"], "repeat_missing")

    def test_matching_request_for_semantic_decision_not_provided_satisfies_gate(self) -> None:
        plan = DecisionPlan(
            decisions=[],
            blockers=[
                Blocker(
                    code="SEMANTIC_DECISION_NOT_PROVIDED",
                    message="semantic decisions json does not cover this unresolved cluster",
                    layer="decision",
                    severity="write_blocker",
                    context={"cluster_id": "repeat_missing"},
                )
            ],
            semantic_request_payloads=[
                {
                    "cluster_id": "repeat_missing",
                    "type": "single_variant_modifier_redundancy",
                    "repeat_type": "modifier_redundancy",
                    "text": "甲的乙的项",
                    "allowed_decisions": ["drop_redundant_modifier", "keep_all", "requires_human_review"],
                }
            ],
        )

        blockers = ArollEngine()._semantic_request_consistency_blockers(plan, {})

        self.assertEqual(blockers, [])


if __name__ == "__main__":
    unittest.main()
