from __future__ import annotations

import unittest

from aroll_v21 import ArollEngine
from aroll_v21.decision import SemanticDecisionsJsonPlanner
from tests.test_aroll_v21_semantic_unconfigured_dryrun_policy import semantic_run_input


class ArollV21SemanticDecisionNotProvidedRequestTests(unittest.TestCase):
    def test_semantic_decision_not_provided_emits_matching_request_payload(self) -> None:
        report = ArollEngine(deepseek_planner=SemanticDecisionsJsonPlanner([])).run(
            semantic_run_input(text="甲的乙的项")
        )

        codes = [blocker.code for blocker in report.blocker_report.blockers]
        self.assertIn("SEMANTIC_DECISION_NOT_PROVIDED", codes)
        self.assertNotIn("INTERNAL_SEMANTIC_REQUEST_MISSING_FOR_DECISION_NOT_PROVIDED", codes)

        missing_cluster_ids = {
            blocker.context["cluster_id"]
            for blocker in report.blocker_report.blockers
            if blocker.code == "SEMANTIC_DECISION_NOT_PROVIDED"
        }
        payloads_by_id = {
            payload["cluster_id"]: payload
            for payload in report.decision_plan.semantic_request_payloads
        }
        self.assertEqual(missing_cluster_ids, {"repeat_002000"})
        self.assertIn("repeat_002000", payloads_by_id)

        payload = payloads_by_id["repeat_002000"]
        self.assertEqual(payload["repeat_type"], "modifier_redundancy")
        self.assertEqual(payload["type"], "single_variant_modifier_redundancy")
        self.assertEqual(payload["text"], "甲的乙的项")
        self.assertIn("drop_redundant_modifier", payload["allowed_decisions"])
        self.assertEqual(payload["suggested_for_rough_cut"], "drop_redundant_modifier")


if __name__ == "__main__":
    unittest.main()
