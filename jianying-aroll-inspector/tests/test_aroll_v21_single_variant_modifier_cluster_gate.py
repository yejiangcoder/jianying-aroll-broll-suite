from __future__ import annotations

import unittest

from aroll_v21 import ArollEngine
from tests.test_aroll_v21_semantic_gate_resolved_by_final_timeline import resolved_modifier_input
from tests.test_aroll_v21_semantic_unconfigured_dryrun_policy import semantic_run_input


class FailingValidators:
    def run(self, **_kwargs):
        return {
            "validators_read_only": True,
            "validator_report_ok": False,
            "final_repeat_validator": {"final_repeat_gate_passed": False, "final_text_repeat_high_count": 1},
            "hidden_audio_repeat_validator": {"hidden_audio_repeat_gate_passed": True},
            "safe_cut_validator": {"safe_cut_boundary_gate_passed": True, "cut_inside_word_count": 0, "partial_multichar_cut_count": 0},
            "subtitle_coverage_validator": {"subtitle_coverage_gate_passed": True, "all_captions_derived_from_final_timeline": True, "missing_caption_segment_ids": []},
            "subtitle_style_validator": {"prewrite_style_gate_ok": True, "giant_subtitle_count": 0, "template_fingerprint_mismatch_count": 0},
            "postwrite_material_validator": {"postwrite_material_gate_ok": True, "postwrite_decrypt_ok": False, "postwrite_mode": "simulated", "content_schema_error_count": 0},
            "semantic_final_review_validator": {"semantic_final_review_validator_passed": True, "semantic_unresolved_count": 0},
        }


class ArollV21SingleVariantModifierClusterGateTests(unittest.TestCase):
    def test_write_mode_can_resolve_stale_semantic_after_final_timeline(self) -> None:
        report = ArollEngine().run(resolved_modifier_input(mode="write"))

        self.assertEqual(report.decision_plan.semantic_unresolved_count, 0)
        self.assertFalse(any(blocker.code == "SEMANTIC_DECISION_NOT_PROVIDED" for blocker in report.blocker_report.blockers))
        self.assertNotEqual((report.blocker_report.summary or {}).get("stage"), "decision")

    def test_validator_fatal_still_controls_write_allowed_after_semantic_resolved(self) -> None:
        report = ArollEngine(validators=FailingValidators()).run(resolved_modifier_input())

        self.assertEqual(report.decision_plan.semantic_unresolved_count, 0)
        self.assertEqual(report.blocker_report.summary["semantic_write_allowed"], True)
        self.assertEqual(report.blocker_report.summary["validator_write_allowed"], False)
        self.assertEqual(report.blocker_report.summary["write_allowed"], False)

    def test_unresolved_single_variant_cluster_remains_write_blocked(self) -> None:
        report = ArollEngine().run(semantic_run_input(text="随意的肆意的踩踏"))

        self.assertEqual(report.decision_plan.semantic_unresolved_count, 1)
        self.assertFalse(report.blocker_report.summary["semantic_write_allowed"])
        self.assertFalse(report.blocker_report.summary["write_allowed"])


if __name__ == "__main__":
    unittest.main()
