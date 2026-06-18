from __future__ import annotations

import unittest

from aroll_v21.decision import SemanticDecisionPlanner
from aroll_v21.evidence import CandidateEvidenceBuilder
from aroll_v21.ingest import DraftIngest


def _graph_for_pair(left: str, right: str):
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
                "word_id": "w_right",
                "word_text": right,
                "source_start_us": 600_000,
                "source_end_us": 1_200_000,
                "source_material_id": "main",
                "source_segment_id": "clip",
                "subtitle_uid": "s_right",
                "subtitle_index": 2,
            },
        ],
        subtitles=[
            {"subtitle_uid": "s_left", "subtitle_index": 1, "text": left, "word_ids": ["w_left"]},
            {"subtitle_uid": "s_right", "subtitle_index": 2, "text": right, "word_ids": ["w_right"]},
        ],
        source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 2_000_000}],
    )


class ArollV21BoundaryPrefixContainmentDecisionTests(unittest.TestCase):
    def test_round8_comment_prefix_generates_drop_left_decision(self) -> None:
        graph = _graph_for_pair("评论区也全是哇", "评论区也全是哇塞")
        clusters = CandidateEvidenceBuilder().build(graph)
        plan = SemanticDecisionPlanner().plan(clusters)

        self.assertEqual([blocker.code for blocker in plan.blockers], [])
        self.assertEqual(len(plan.decisions), 1)
        self.assertEqual(plan.decisions[0].drop_unit_ids, ["s_left"])
        self.assertEqual(plan.decisions[0].keep_unit_id, "s_right")
        trace = [row for row in plan.decision_trace if row["route"] == "boundary_prefix_containment"]
        self.assertEqual(trace[0]["left_text"], "评论区也全是哇")
        self.assertEqual(trace[0]["right_text"], "评论区也全是哇塞")
        self.assertEqual(trace[0]["decision"], "drop_left_keep_right")

    def test_legacy_cross_segment_prefix_no_longer_requires_human_review(self) -> None:
        graph = DraftIngest().build_source_graph(
            word_timeline=[
                {
                    "word_id": "w_left",
                    "word_text": "重新上",
                    "source_start_us": 0,
                    "source_end_us": 500_000,
                    "source_material_id": "main",
                    "source_segment_id": "clip_a",
                    "subtitle_uid": "s_left",
                    "subtitle_index": 1,
                },
                {
                    "word_id": "w_right",
                    "word_text": "重新上桌",
                    "source_start_us": 600_000,
                    "source_end_us": 1_200_000,
                    "source_material_id": "main",
                    "source_segment_id": "clip_b",
                    "subtitle_uid": "s_right",
                    "subtitle_index": 2,
                },
            ],
            subtitles=[
                {"subtitle_uid": "s_left", "subtitle_index": 1, "text": "重新上", "word_ids": ["w_left"]},
                {"subtitle_uid": "s_right", "subtitle_index": 2, "text": "重新上桌", "word_ids": ["w_right"]},
            ],
            source_segments=[
                {"id": "clip_a", "material_id": "main", "source_start_us": 0, "source_end_us": 500_000},
                {"id": "clip_b", "material_id": "main", "source_start_us": 600_000, "source_end_us": 1_200_000},
            ],
        )

        plan = SemanticDecisionPlanner().plan(CandidateEvidenceBuilder().build(graph))

        self.assertEqual([blocker.code for blocker in plan.blockers], [])
        self.assertEqual(len(plan.decisions), 1)
        self.assertEqual(plan.decisions[0].drop_unit_ids, ["s_left"])


if __name__ == "__main__":
    unittest.main()
