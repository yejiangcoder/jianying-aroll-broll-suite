from __future__ import annotations

import unittest

from aroll_v21 import ArollEngine
from aroll_v21.decision import SemanticDecisionsJsonPlanner
from tests.test_aroll_v21_semantic_unconfigured_dryrun_policy import semantic_run_input
from tests.test_aroll_v21_semantic_request_modifier_redundancy import final_modifier_fixture_input


class ArollV21ModifierRedundancyEndToEndTests(unittest.TestCase):
    def test_drop_redundant_modifier_resolves_repeat_and_rough_cut_metrics(self) -> None:
        report = ArollEngine(
            deepseek_planner=SemanticDecisionsJsonPlanner(
                [
                    {
                        "cluster_id": "repeat_002000",
                        "decision": "drop_redundant_modifier",
                        "reason": "remove redundant left modifier before same head",
                        "confidence": 0.8,
                        "requires_human_review": False,
                    }
                ]
            )
        ).run(final_modifier_fixture_input())

        self.assertEqual([segment.text for segment in report.final_timeline], ["肆意的踩踏"])
        self.assertEqual([caption.text for caption in report.captions], ["肆意的踩踏"])
        self.assertEqual(report.final_timeline[0].word_ids, ["w_000004", "w_000005", "w_000006", "w_000007", "w_000008"])
        self.assertTrue(report.validator_report["final_repeat_validator"]["final_repeat_gate_passed"])
        self.assertTrue(report.validator_report["hidden_audio_repeat_validator"]["hidden_audio_repeat_gate_passed"])
        rough = report.validator_report["rough_cut_quality_validator"]
        self.assertEqual(rough["segments_lt_300ms"], 0)
        self.assertEqual(rough["one_char_captions"], 0)
        self.assertEqual(rough["adjacent_duplicate_text_count"], 0)
        self.assertNotIn("FINAL_REPEAT_VALIDATOR_FAILED", [blocker.code for blocker in report.blocker_report.blockers])
        self.assertNotIn("HIDDEN_AUDIO_REPEAT_VALIDATOR_FAILED", [blocker.code for blocker in report.blocker_report.blockers])

    def test_keep_all_blocks_fatal_modifier_redundancy(self) -> None:
        report = ArollEngine(
            deepseek_planner=SemanticDecisionsJsonPlanner(
                [
                    {
                        "cluster_id": "repeat_002000",
                        "decision": "keep_all",
                        "reason": "explicitly accept modifier phrase",
                        "confidence": 0.8,
                        "requires_human_review": False,
                    }
                ]
            )
        ).run(final_modifier_fixture_input())

        self.assertEqual([segment.text for segment in report.final_timeline], ["随意的肆意的踩踏"])
        self.assertEqual(report.status, "blocked")
        self.assertIn("V21_FATAL_MODIFIER_REDUNDANCY_UNRESOLVED", [blocker.code for blocker in report.blocker_report.blockers])

    def test_unresolved_modifier_request_is_semantic_blocker_not_repeat_validator_fatal(self) -> None:
        report = ArollEngine().run(final_modifier_fixture_input())

        self.assertTrue(report.decision_plan.semantic_request_payloads)
        self.assertEqual(report.decision_plan.semantic_unresolved_count, 1)
        self.assertFalse(report.decision_plan.write_allowed)
        self.assertTrue(report.validator_report["final_repeat_validator"]["final_repeat_gate_passed"])
        self.assertTrue(report.validator_report["hidden_audio_repeat_validator"]["hidden_audio_repeat_gate_passed"])
        self.assertEqual(report.validator_report["final_repeat_validator"]["adjacent_modifier_semantic_redundancy_semantic_unresolved_count"], 1)
        self.assertNotIn("FINAL_REPEAT_VALIDATOR_FAILED", [blocker.code for blocker in report.blocker_report.blockers])
        self.assertNotIn("HIDDEN_AUDIO_REPEAT_VALIDATOR_FAILED", [blocker.code for blocker in report.blocker_report.blockers])

    def test_existing_precompiler_modifier_request_marks_validator_unresolved_without_double_count(self) -> None:
        report = ArollEngine().run(semantic_run_input(text="随意的肆意的踩踏"))

        self.assertTrue(report.decision_plan.semantic_request_payloads)
        self.assertEqual(report.decision_plan.modifier_redundancy_unresolved_cluster_ids, ["repeat_002000"])
        self.assertEqual(report.decision_plan.semantic_unresolved_count, 1)
        self.assertTrue(report.validator_report["final_repeat_validator"]["final_repeat_gate_passed"])
        self.assertTrue(report.validator_report["hidden_audio_repeat_validator"]["hidden_audio_repeat_gate_passed"])
        self.assertEqual(report.validator_report["final_repeat_validator"]["adjacent_modifier_semantic_redundancy_semantic_unresolved_count"], 1)
        self.assertEqual(report.validator_report["hidden_audio_repeat_validator"]["adjacent_modifier_semantic_redundancy_semantic_unresolved_count"], 1)
        self.assertNotIn("FINAL_REPEAT_VALIDATOR_FAILED", [blocker.code for blocker in report.blocker_report.blockers])
        self.assertNotIn("HIDDEN_AUDIO_REPEAT_VALIDATOR_FAILED", [blocker.code for blocker in report.blocker_report.blockers])
        self.assertNotIn("INTERNAL_SEMANTIC_REQUEST_MISSING_FOR_FATAL_REPEAT", [blocker.code for blocker in report.blocker_report.blockers])


if __name__ == "__main__":
    unittest.main()
