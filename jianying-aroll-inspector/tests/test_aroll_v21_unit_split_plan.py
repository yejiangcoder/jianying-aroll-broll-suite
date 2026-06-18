from __future__ import annotations

import json
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput
from aroll_v21.compiler import FinalTimelineCompiler
from aroll_v21.decision import SemanticDecisionPlanner
from aroll_v21.evidence import CandidateEvidenceBuilder
from aroll_v21.ingest import DraftIngest
from aroll_v21.ir import DecisionPlan, UnitSplitPlan


ROOT = Path(__file__).resolve().parents[1]


def _material_rows() -> tuple[list[dict], list[dict]]:
    payload = json.loads((ROOT / "fixtures" / "real_materials" / "normal_caption_template.json").read_text("utf-8"))
    return [payload["material"]], [payload["segment"]]


def _split_run_input(*, cut_policy: str = "word_boundary") -> ArollRunInput:
    text_materials, text_segments = _material_rows()
    return ArollRunInput(
        source_segments=[{"id": "clip_1", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1200000}],
        word_timeline=[
            {"word_id": "w1", "word_text": "然后", "start_us": 0, "end_us": 200000, "subtitle_uid": "s1", "subtitle_index": 1},
            {"word_id": "w2", "word_text": "然后", "start_us": 200000, "end_us": 400000, "subtitle_uid": "s1", "subtitle_index": 1},
            {"word_id": "w3", "word_text": "他开始解释", "start_us": 400000, "end_us": 1000000, "subtitle_uid": "s1", "subtitle_index": 1},
        ],
        subtitles=[
            {
                "subtitle_uid": "s1",
                "subtitle_index": 1,
                "text": "然后然后他开始解释",
                "word_ids": ["w1", "w2", "w3"],
                "cut_policy": cut_policy,
            }
        ],
        text_materials=text_materials,
        text_segments=text_segments,
    )


class ArollV21UnitSplitPlanTests(unittest.TestCase):
    def test_intra_edit_unit_repeat_generates_split_decision(self) -> None:
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

        self.assertFalse(plan.blocked, [blocker.code for blocker in plan.blockers])
        self.assertTrue(plan.split_decisions)
        self.assertEqual(plan.split_decisions[0].unit_id, "s1")
        self.assertTrue(set(plan.split_decisions[0].drop_word_ids) < {"w1", "w2", "w3"})
        self.assertNotIn("REPEAT_CLUSTER_REQUIRES_UNIT_SPLIT", [blocker.code for blocker in plan.blockers])

    def test_compiler_removes_drop_word_ids_from_split_decision(self) -> None:
        run_input = _split_run_input()
        graph = DraftIngest().build_source_graph(
            word_timeline=run_input.word_timeline,
            subtitles=run_input.subtitles,
            source_segments=run_input.source_segments,
            text_materials=run_input.text_materials,
            text_segments=run_input.text_segments,
        )
        plan = DecisionPlan(
            decisions=[],
            split_decisions=[
                UnitSplitPlan(
                    split_id="split_test",
                    cluster_id="repeat_test",
                    unit_id="s1",
                    drop_word_ids=["w1"],
                    keep_word_ids=["w2", "w3"],
                    reason="drop first duplicate phrase",
                )
            ],
        )

        timeline, blockers = FinalTimelineCompiler().compile(graph, plan)

        self.assertEqual(blockers, [])
        self.assertEqual("".join(segment.text for segment in timeline), "然后他开始解释")
        self.assertNotIn("w1", [word_id for segment in timeline for word_id in segment.word_ids])

    def test_engine_uses_split_decision_and_final_gate_passes(self) -> None:
        report = ArollEngine().run(_split_run_input())

        self.assertEqual(report.status, "ok", [blocker.code for blocker in report.blocker_report.blockers])
        self.assertEqual("".join(caption.text for caption in report.captions), "然后他开始解释")
        self.assertTrue(report.decision_plan.split_decisions)

    def test_unsafe_edit_unit_split_blocks_with_specific_reason(self) -> None:
        report = ArollEngine().run(_split_run_input(cut_policy="unsafe"))

        self.assertEqual(report.status, "blocked")
        codes = [blocker.code for blocker in report.blocker_report.blockers]
        self.assertIn("UNIT_SPLIT_UNSAFE_BOUNDARY", codes)
        self.assertNotIn("REPEAT_CLUSTER_REQUIRES_UNIT_SPLIT", codes)


if __name__ == "__main__":
    unittest.main()
