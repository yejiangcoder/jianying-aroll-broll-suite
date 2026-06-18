from __future__ import annotations

import unittest

from aroll_v21.decision import SemanticDecisionPlanner, SemanticDecisionsJsonPlanner
from tests.test_aroll_v21_semantic_planner_contract import _semantic_cluster


class ArollV21SemanticDecisionsForbidPhysicalFieldsTests(unittest.TestCase):
    def test_semantic_decisions_json_with_source_time_blocks(self) -> None:
        cluster = _semantic_cluster()
        plan = SemanticDecisionPlanner(
            deepseek_planner=SemanticDecisionsJsonPlanner(
                [
                    {
                        "cluster_id": cluster.cluster_id,
                        "decision": "keep_all",
                        "reason": "invalid physical control",
                        "confidence": 0.8,
                        "source_start_us": 123,
                    }
                ]
            )
        ).plan([cluster])

        self.assertTrue(plan.blocked)
        self.assertIn("SEMANTIC_DECISION_HAS_PHYSICAL_FIELDS", [blocker.code for blocker in plan.blockers])
        self.assertIn("source_start_us", plan.blockers[0].context["forbidden_fields"])


if __name__ == "__main__":
    unittest.main()
