from __future__ import annotations

import unittest

from tests.test_aroll_v21_semantic_planner_contract import _semantic_cluster
from aroll_v21.decision import SemanticDecisionPlanner


class ArollV21SemanticRequestPayloadsTests(unittest.TestCase):
    def test_payload_contains_cluster_context_and_required_schema(self) -> None:
        plan = SemanticDecisionPlanner().plan([_semantic_cluster()])

        payload = plan.semantic_request_payloads[0]
        self.assertEqual(payload["cluster_id"], "cluster_1")
        self.assertEqual(payload["repeat_type"], "modifier_redundancy")
        self.assertTrue(payload["variants"])
        self.assertTrue(payload["local_evidence"])
        self.assertIn("keep_unit_id", payload["required_decision_schema"])
        self.assertIn("drop_unit_ids", payload["required_decision_schema"])


if __name__ == "__main__":
    unittest.main()
