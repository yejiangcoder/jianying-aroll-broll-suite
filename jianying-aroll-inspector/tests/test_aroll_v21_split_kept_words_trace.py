from __future__ import annotations

import unittest

from aroll_v21.compiler import FinalTimelineCompiler
from aroll_v21.ingest import DraftIngest
from aroll_v21.ir import DecisionPlan, UnitSplitPlan


class ArollV21SplitKeptWordsTraceTests(unittest.TestCase):
    def test_split_keep_word_ids_carry_split_id_to_final_segment(self) -> None:
        graph = DraftIngest().build_source_graph(
            word_timeline=[
                {
                    "word_id": "w_drop",
                    "word_text": "删除内容",
                    "source_start_us": 0,
                    "source_end_us": 400_000,
                    "source_material_id": "main",
                    "source_segment_id": "clip",
                    "subtitle_uid": "s1",
                    "subtitle_index": 1,
                },
                {
                    "word_id": "w_keep",
                    "word_text": "保留片段",
                    "source_start_us": 420_000,
                    "source_end_us": 980_000,
                    "source_material_id": "main",
                    "source_segment_id": "clip",
                    "subtitle_uid": "s1",
                    "subtitle_index": 1,
                },
            ],
            subtitles=[
                {
                    "subtitle_uid": "s1",
                    "subtitle_index": 1,
                    "text": "删除内容保留片段",
                    "word_ids": ["w_drop", "w_keep"],
                }
            ],
            source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 1_500_000}],
        )
        plan = DecisionPlan(
            decisions=[],
            split_decisions=[
                UnitSplitPlan(
                    split_id="split_keep_trace",
                    cluster_id="cluster_keep_trace",
                    unit_id="s1",
                    drop_word_ids=["w_drop"],
                    keep_word_ids=["w_keep"],
                    reason="drop redundant prefix and keep the useful phrase",
                )
            ],
        )

        timeline, blockers = FinalTimelineCompiler().compile(graph, plan)

        self.assertEqual(blockers, [])
        self.assertEqual([segment.text for segment in timeline], ["保留片段"])
        self.assertIn("split_keep_trace", timeline[0].decision_ids)


if __name__ == "__main__":
    unittest.main()
