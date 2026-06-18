from __future__ import annotations

import unittest

from aroll_v21.compiler import FinalTimelineCompiler
from aroll_v21.ir import DecisionPlan
from tests.test_aroll_v21_final_pre_uat_prefix_drop import _graph_for_texts


class ArollV21PrefixDropConvergenceTests(unittest.TestCase):
    def test_multiple_prefix_pairs_are_processed_in_one_compile(self) -> None:
        graph = _graph_for_texts(["评论区也全是哇", "评论区也全是哇塞", "重新上", "重新上桌"])
        plan = DecisionPlan(decisions=[])

        final_timeline, blockers = FinalTimelineCompiler().compile(graph, plan)

        self.assertEqual(blockers, [])
        self.assertEqual([segment.text for segment in final_timeline], ["评论区也全是哇塞", "重新上桌"])
        self.assertEqual(final_timeline[0].target_start_us, 0)
        self.assertEqual(final_timeline[0].target_end_us, final_timeline[1].target_start_us)
        self.assertGreater(final_timeline[1].target_end_us, final_timeline[1].target_start_us)
        applied = [row for row in plan.decision_trace if row.get("stage") == "final_timeline_pre_emit"]
        self.assertEqual(len(applied), 2)

    def test_chain_prefix_converges_to_longest_completed_segment(self) -> None:
        graph = _graph_for_texts(["A", "AB", "ABC"])
        plan = DecisionPlan(decisions=[])

        final_timeline, blockers = FinalTimelineCompiler().compile(graph, plan)

        self.assertEqual(blockers, [])
        self.assertEqual([segment.text for segment in final_timeline], ["ABC"])
        self.assertEqual(final_timeline[0].target_start_us, 0)
        self.assertGreater(final_timeline[0].target_end_us, 0)
        applied = [row for row in plan.decision_trace if row.get("stage") == "final_timeline_pre_emit"]
        self.assertEqual(len(applied), 2)


if __name__ == "__main__":
    unittest.main()
