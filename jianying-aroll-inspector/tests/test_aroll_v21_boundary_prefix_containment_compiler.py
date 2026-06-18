from __future__ import annotations

import unittest

from aroll_v21.compiler import FinalTimelineCompiler
from aroll_v21.decision import SemanticDecisionPlanner
from aroll_v21.evidence import CandidateEvidenceBuilder
from tests.test_aroll_v21_boundary_prefix_containment_decision import _graph_for_pair


class ArollV21BoundaryPrefixContainmentCompilerTests(unittest.TestCase):
    def test_prefix_drop_left_is_applied_by_compiler_without_cutting_right(self) -> None:
        graph = _graph_for_pair("重新上", "重新上桌")
        clusters = CandidateEvidenceBuilder().build(graph)
        plan = SemanticDecisionPlanner().plan(clusters)
        final_timeline, blockers = FinalTimelineCompiler().compile(graph, plan)

        self.assertEqual(blockers, [])
        self.assertEqual(len(final_timeline), 1)
        self.assertEqual(final_timeline[0].text, "重新上桌")
        self.assertEqual(final_timeline[0].word_ids, ["w_right"])


if __name__ == "__main__":
    unittest.main()
