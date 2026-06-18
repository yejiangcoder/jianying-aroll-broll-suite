from __future__ import annotations

import unittest

from aroll_v21.compiler import FinalTimelineCompiler
from aroll_v21.ingest import DraftIngest
from aroll_v21.ir import DecisionPlan, UnitSplitPlan


class ArollV21CompilerSplitDecisionsTests(unittest.TestCase):
    def test_split_decision_cannot_reference_unknown_word_ids(self) -> None:
        graph = DraftIngest().build_source_graph(
            word_timeline=[
                {"word_id": "w1", "word_text": "重复", "start_us": 0, "end_us": 100, "subtitle_uid": "s1", "subtitle_index": 1},
                {"word_id": "w2", "word_text": "保留", "start_us": 100, "end_us": 200, "subtitle_uid": "s1", "subtitle_index": 1},
            ],
            subtitles=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": "重复保留", "word_ids": ["w1", "w2"]}],
            source_segments=[{"id": "clip_1", "material_id": "m1", "source_start_us": 0, "source_end_us": 300}],
            text_materials=[],
            text_segments=[],
        )
        plan = DecisionPlan(
            decisions=[],
            split_decisions=[
                UnitSplitPlan(
                    split_id="split_bad",
                    cluster_id="cluster_bad",
                    unit_id="s1",
                    drop_word_ids=["missing"],
                    keep_word_ids=["w1", "w2"],
                    reason="invalid test split",
                )
            ],
        )

        timeline, blockers = FinalTimelineCompiler().compile(graph, plan)

        self.assertEqual(timeline, [])
        self.assertEqual([blocker.code for blocker in blockers], ["UNIT_SPLIT_UNKNOWN_WORD"])


if __name__ == "__main__":
    unittest.main()
