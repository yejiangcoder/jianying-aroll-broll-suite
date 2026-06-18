from __future__ import annotations

import unittest

from aroll_v21 import ArollEngine
from aroll_v21.decision import SemanticDecisionPlanner, SemanticDecisionsJsonPlanner
from tests.test_aroll_v21_modifier_redundancy_end_to_end import final_modifier_fixture_input
from tests.test_aroll_v21_unit_split_end_to_end_contract import ForceHumanReviewSplitPolicy, unit_split_contract_input
from tools.create_aroll_v21_semantic_decisions_template import build_suggested_for_rough_cut


def _force_split_engine(rows: list[dict] | None = None) -> ArollEngine:
    planner = SemanticDecisionsJsonPlanner(rows or []) if rows is not None else None
    engine = ArollEngine()
    engine.decision_planner = SemanticDecisionPlanner(
        local_policy=ForceHumanReviewSplitPolicy(),
        deepseek_planner=planner,
    )
    return engine


class ArollV21SemanticConvergenceConsistencyTests(unittest.TestCase):
    def test_multistage_semantic_convergence_requests_template_and_final_alignment(self) -> None:
        round1_discovery = _force_split_engine().run(unit_split_contract_input())
        round1_payloads = round1_discovery.decision_plan.semantic_request_payloads
        self.assertTrue(round1_payloads)
        self.assertEqual(round1_payloads[0]["type"], "unit_split_requires_human_review")

        round1_decisions = build_suggested_for_rough_cut(round1_payloads)
        self.assertEqual(round1_decisions[0]["decision"], "apply_suggested_split")

        round1_ready = _force_split_engine(round1_decisions).run(unit_split_contract_input())
        round1_codes = [blocker.code for blocker in round1_ready.blocker_report.blockers]
        self.assertEqual(round1_ready.status, "ok", round1_codes)
        self.assertNotIn("UNIT_SPLIT_REQUIRES_HUMAN_REVIEW", round1_codes)

        round2_discovery = ArollEngine().run(final_modifier_fixture_input())
        round2_payloads = round2_discovery.decision_plan.semantic_request_payloads
        self.assertTrue(round2_payloads)
        self.assertEqual(round2_payloads[0]["cluster_id"], "repeat_002000")
        self.assertEqual(round2_payloads[0]["type"], "single_variant_modifier_redundancy")

        round2_decisions = build_suggested_for_rough_cut(round2_payloads)
        self.assertEqual(round2_decisions[0]["decision"], "drop_redundant_modifier")

        round2_ready = ArollEngine(deepseek_planner=SemanticDecisionsJsonPlanner(round2_decisions)).run(
            final_modifier_fixture_input()
        )
        codes = [blocker.code for blocker in round2_ready.blocker_report.blockers]
        self.assertEqual(round2_ready.status, "ok", codes)
        self.assertNotIn("SEMANTIC_DECISION_NOT_PROVIDED", codes)
        self.assertEqual(round2_ready.decision_plan.semantic_unresolved_count, 0)

        self.assertEqual(len(round2_ready.final_timeline), len(round2_ready.captions))
        self.assertEqual(len(round2_ready.captions), len(round2_ready.material_write_plan["materials"]))
        self.assertEqual(len(round2_ready.captions), len(round2_ready.material_write_plan["segments"]))
        rough = round2_ready.validator_report["rough_cut_quality_validator"]
        self.assertEqual(rough["segments_lt_300ms"], 0)
        self.assertEqual(rough["one_char_captions"], 0)
        self.assertTrue(rough["rough_cut_quality_gate_passed"])


if __name__ == "__main__":
    unittest.main()
