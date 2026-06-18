from __future__ import annotations

import unittest

from aroll_v21 import ArollEngine, ArollRunInput
from aroll_v21.decision.semantic_decision_planner import LocalPolicy, SemanticDecisionPlanner, SemanticDecisionsJsonPlanner
from aroll_v21.ir import Blocker, RepeatCluster
from tests.test_aroll_v21_intra_edit_unit_repeat_split import _material_rows
from tests.test_aroll_v21_unit_split_semantic_request_emission import unit_split_human_review_input


class ForceHumanReviewSplitPolicy(LocalPolicy):
    def decide(self, cluster: RepeatCluster):  # type: ignore[override]
        if cluster.local_recommendation == "requires_unit_split":
            return Blocker(
                code="UNIT_SPLIT_REQUIRES_HUMAN_REVIEW",
                message="forced unit split semantic review for contract coverage",
                layer="decision",
                context={"cluster_id": cluster.cluster_id, "repeat_type": cluster.repeat_type},
            )
        return super().decide(cluster)


def unit_split_contract_input() -> ArollRunInput:
    text_materials, text_segments = _material_rows()
    return ArollRunInput(
        source_segments=[{"id": "clip_1", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1_200_000}],
        word_timeline=[
            {"word_id": "w1", "word_text": "A", "start_us": 0, "end_us": 300_000, "subtitle_uid": "s1", "subtitle_index": 1},
            {"word_id": "w2", "word_text": "A", "start_us": 300_000, "end_us": 600_000, "subtitle_uid": "s1", "subtitle_index": 1},
            {"word_id": "w3", "word_text": "BCDE", "start_us": 600_000, "end_us": 1_200_000, "subtitle_uid": "s1", "subtitle_index": 1},
        ],
        subtitles=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": "AABCDE", "word_ids": ["w1", "w2", "w3"]}],
        text_materials=text_materials,
        text_segments=text_segments,
        postwrite_mode="simulated",
    )


class ArollV21UnitSplitEndToEndContractTests(unittest.TestCase):
    def test_apply_suggested_split_syncs_final_timeline_captions_and_material_plan(self) -> None:
        engine = ArollEngine(
            deepseek_planner=SemanticDecisionsJsonPlanner(
                [
                    {
                        "cluster_id": "repeat_003000",
                        "decision": "apply_suggested_split",
                        "reason": "apply suggested whole-word split",
                        "confidence": 0.91,
                        "requires_human_review": False,
                    }
                ]
            )
        )
        engine.decision_planner = SemanticDecisionPlanner(
            local_policy=ForceHumanReviewSplitPolicy(),
            deepseek_planner=SemanticDecisionsJsonPlanner(
                [
                    {
                        "cluster_id": "repeat_003000",
                        "decision": "apply_suggested_split",
                        "reason": "apply suggested whole-word split",
                        "confidence": 0.91,
                        "requires_human_review": False,
                    }
                ]
            ),
        )

        report = engine.run(unit_split_contract_input())

        blocker_codes = [blocker.code for blocker in report.blocker_report.blockers]
        self.assertEqual(report.status, "ok", blocker_codes)
        self.assertNotIn("UNIT_SPLIT_REQUIRES_HUMAN_REVIEW", blocker_codes)
        self.assertTrue(report.decision_plan.split_decisions)
        split = report.decision_plan.split_decisions[0]
        self.assertEqual(split.drop_word_ids, ["w1"])
        self.assertEqual(split.keep_word_ids, ["w2", "w3"])

        self.assertEqual(len(report.final_timeline), 1)
        self.assertEqual(report.final_timeline[0].text, "ABCDE")
        self.assertEqual(report.final_timeline[0].word_ids, ["w2", "w3"])
        self.assertIn(split.split_id, report.final_timeline[0].decision_ids)
        self.assertEqual([caption.text for caption in report.captions], ["ABCDE"])

        self.assertEqual(len(report.final_timeline), len(report.captions))
        self.assertEqual(len(report.captions), len(report.material_write_plan["materials"]))
        self.assertEqual(len(report.captions), len(report.material_write_plan["segments"]))

        rough = report.validator_report["rough_cut_quality_validator"]
        self.assertEqual(rough["segments_lt_300ms"], 0)
        self.assertEqual(rough["one_char_captions"], 0)
        self.assertTrue(rough["rough_cut_quality_gate_passed"])
        self.assertTrue(report.validator_report["final_repeat_validator"]["final_repeat_gate_passed"])
        self.assertTrue(report.validator_report["hidden_audio_repeat_validator"]["hidden_audio_repeat_gate_passed"])

    def test_unit_split_word_binding_missing_fails_closed(self) -> None:
        planner = SemanticDecisionPlanner(
            local_policy=ForceHumanReviewSplitPolicy(),
            deepseek_planner=SemanticDecisionsJsonPlanner(
                [
                    {
                        "cluster_id": "repeat_001000",
                        "decision": "apply_suggested_split",
                        "reason": "apply suggested whole-word split",
                        "confidence": 0.91,
                        "requires_human_review": False,
                    }
                ]
            ),
        )
        engine = ArollEngine()
        engine.decision_planner = planner

        report = engine.run(unit_split_human_review_input())

        codes = [blocker.code for blocker in report.blocker_report.blockers]
        self.assertEqual(report.status, "blocked")
        self.assertIn("UNIT_SPLIT_WORD_BINDING_MISSING", codes)


if __name__ == "__main__":
    unittest.main()
