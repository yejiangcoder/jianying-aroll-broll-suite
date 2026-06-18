from __future__ import annotations

import unittest

from aroll_v21.compiler import FinalTimelineCompiler
from aroll_v21.ingest import DraftIngest
from aroll_v21.ir import DecisionPlan, TakeDecision


def _graph_with_middle_unit(left: str, middle: str, right: str):
    return DraftIngest().build_source_graph(
        word_timeline=[
            {
                "word_id": "w_left",
                "word_text": left,
                "source_start_us": 0,
                "source_end_us": 500_000,
                "source_material_id": "main",
                "source_segment_id": "clip",
                "subtitle_uid": "s_left",
                "subtitle_index": 1,
            },
            {
                "word_id": "w_middle",
                "word_text": middle,
                "source_start_us": 540_000,
                "source_end_us": 580_000,
                "source_material_id": "main",
                "source_segment_id": "clip",
                "subtitle_uid": "s_middle",
                "subtitle_index": 2,
            },
            {
                "word_id": "w_right",
                "word_text": right,
                "source_start_us": 620_000,
                "source_end_us": 1_200_000,
                "source_material_id": "main",
                "source_segment_id": "clip",
                "subtitle_uid": "s_right",
                "subtitle_index": 3,
            },
        ],
        subtitles=[
            {"subtitle_uid": "s_left", "subtitle_index": 1, "text": left, "word_ids": ["w_left"]},
            {"subtitle_uid": "s_middle", "subtitle_index": 2, "text": middle, "word_ids": ["w_middle"]},
            {"subtitle_uid": "s_right", "subtitle_index": 3, "text": right, "word_ids": ["w_right"]},
        ],
        source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 2_000_000}],
    )


def _drop_middle_plan() -> DecisionPlan:
    return DecisionPlan(
        decisions=[
            TakeDecision(
                decision_id="drop_middle",
                cluster_id="manual_middle_drop",
                keep_unit_id="s_right",
                drop_unit_ids=["s_middle"],
                reason="fixture removes middle so final adjacency changes",
                confidence=1.0,
                requires_human_review=False,
            )
        ]
    )


class ArollV21FinalTimelinePreEmitPrefixDropTests(unittest.TestCase):
    def test_pre_emit_drops_left_when_adjacency_only_exists_after_other_drop(self) -> None:
        graph = _graph_with_middle_unit("评论区也全是哇", "中间", "评论区也全是哇塞")
        plan = _drop_middle_plan()
        final_timeline, blockers = FinalTimelineCompiler().compile(graph, plan)

        self.assertEqual(blockers, [])
        self.assertEqual([segment.text for segment in final_timeline], ["评论区也全是哇塞"])
        self.assertEqual(final_timeline[0].target_start_us, 0)
        self.assertEqual(final_timeline[0].target_end_us, 580_000)
        trace = [row for row in plan.decision_trace if row.get("stage") == "final_timeline_pre_emit"]
        self.assertEqual(trace[0]["route"], "boundary_prefix_containment")
        self.assertEqual(trace[0]["left_text"], "评论区也全是哇")
        self.assertEqual(trace[0]["right_text"], "评论区也全是哇塞")
        self.assertTrue(trace[0]["applied"])

    def test_target_timeline_is_repacked_without_gap_after_prefix_drop(self) -> None:
        graph = _graph_with_middle_unit("重新上", "中间", "重新上桌")
        final_timeline, blockers = FinalTimelineCompiler().compile(graph, _drop_middle_plan())

        self.assertEqual(blockers, [])
        self.assertEqual(len(final_timeline), 1)
        self.assertEqual(final_timeline[0].target_start_us, 0)
        self.assertGreater(final_timeline[0].target_end_us, final_timeline[0].target_start_us)


if __name__ == "__main__":
    unittest.main()
