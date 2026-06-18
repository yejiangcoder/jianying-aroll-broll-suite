from __future__ import annotations

import unittest

from aroll_v21.decision import SemanticDecisionPlanner
from tests.test_aroll_v21_semantic_planner_contract import MockPlanner, _semantic_cluster
from tests.test_aroll_v21_unit_split_plan import _split_run_input
from aroll_v21.evidence import CandidateEvidenceBuilder
from aroll_v21.ingest import DraftIngest


class ArollV21DecisionTraceTests(unittest.TestCase):
    def test_trace_records_deepseek_missing_config(self) -> None:
        plan = SemanticDecisionPlanner().plan([_semantic_cluster()])

        self.assertTrue(plan.decision_trace)
        self.assertIn("V21_SEMANTIC_ADJUDICATION_PROVIDER_MISSING", {row["blocker"] for row in plan.decision_trace})
        self.assertIn("DEEPSEEK_SEMANTIC_PLANNER_NOT_CONFIGURED", {blocker.code for blocker in plan.blockers})

    def test_trace_records_deepseek_decision(self) -> None:
        plan = SemanticDecisionPlanner(deepseek_planner=MockPlanner()).plan([_semantic_cluster()])

        self.assertIn("deepseek_required", {row["route"] for row in plan.decision_trace})
        self.assertEqual(plan.decision_trace[0]["output_decision"], plan.decisions[0].decision_id)

    def test_trace_records_split_generated(self) -> None:
        run_input = _split_run_input()
        graph = DraftIngest().build_source_graph(
            word_timeline=run_input.word_timeline,
            subtitles=run_input.subtitles,
            source_segments=run_input.source_segments,
            text_materials=run_input.text_materials,
            text_segments=run_input.text_segments,
        )
        clusters = CandidateEvidenceBuilder().build(graph)
        plan = SemanticDecisionPlanner().plan(clusters)

        self.assertIn("split_generated", {row["route"] for row in plan.decision_trace})


if __name__ == "__main__":
    unittest.main()
