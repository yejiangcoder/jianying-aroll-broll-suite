from __future__ import annotations

import json
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine
from tests.test_aroll_v21_semantic_unconfigured_dryrun_policy import semantic_run_input


ROOT = Path(__file__).resolve().parents[1]


class FailingRepeatValidators:
    def run(self, **_kwargs):
        return {
            "validators_read_only": True,
            "validator_report_ok": False,
            "final_repeat_validator": {"final_repeat_gate_passed": False, "final_cjk_short_repeat_fatal_count": 1},
            "hidden_audio_repeat_validator": {"hidden_audio_repeat_gate_passed": True},
            "safe_cut_validator": {"safe_cut_boundary_gate_passed": True, "cut_inside_word_count": 0, "partial_multichar_cut_count": 0},
            "subtitle_coverage_validator": {"subtitle_coverage_gate_passed": True, "all_captions_derived_from_final_timeline": True, "missing_caption_segment_ids": []},
            "subtitle_style_validator": {"prewrite_style_gate_ok": True, "giant_subtitle_count": 0, "template_fingerprint_mismatch_count": 0},
            "postwrite_material_validator": {"postwrite_material_gate_ok": True, "postwrite_decrypt_ok": False, "postwrite_mode": "simulated", "content_schema_error_count": 0},
            "semantic_final_review_validator": {"semantic_final_review_validator_passed": True, "semantic_unresolved_count": 0},
        }


class PassingValidators:
    def run(self, **_kwargs):
        return {
            "validators_read_only": True,
            "validator_report_ok": True,
            "final_repeat_validator": {"final_repeat_gate_passed": True},
            "hidden_audio_repeat_validator": {"hidden_audio_repeat_gate_passed": True},
            "safe_cut_validator": {"safe_cut_boundary_gate_passed": True, "cut_inside_word_count": 0, "partial_multichar_cut_count": 0},
            "subtitle_coverage_validator": {"subtitle_coverage_gate_passed": True, "all_captions_derived_from_final_timeline": True, "missing_caption_segment_ids": []},
            "subtitle_style_validator": {"prewrite_style_gate_ok": True, "giant_subtitle_count": 0, "template_fingerprint_mismatch_count": 0},
            "postwrite_material_validator": {"postwrite_material_gate_ok": True, "postwrite_decrypt_ok": False, "postwrite_mode": "simulated", "content_schema_error_count": 0},
            "semantic_final_review_validator": {"semantic_final_review_validator_passed": True, "semantic_unresolved_count": 0},
        }


def _simple_input():
    fixture = json.loads((ROOT / "fixtures" / "real_materials" / "normal_caption_template.json").read_text("utf-8"))
    return semantic_run_input(text="普通字幕")


class ArollV21WriteAllowedAggregatesValidatorBlockersTests(unittest.TestCase):
    def test_semantic_clear_but_validator_fatal_keeps_write_allowed_false(self) -> None:
        report = ArollEngine(validators=FailingRepeatValidators()).run(_simple_input())

        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.blocker_report.summary["semantic_write_allowed"], True)
        self.assertEqual(report.blocker_report.summary["validator_write_allowed"], False)
        self.assertEqual(report.blocker_report.summary["write_allowed"], False)
        self.assertEqual(report.blocker_report.summary["READY_FOR_DISPOSABLE_WRITE_PRE_AUDIT"], False)

    def test_semantic_clear_and_validators_green_allows_write_ready_flag(self) -> None:
        report = ArollEngine(validators=PassingValidators()).run(_simple_input())

        self.assertEqual(report.status, "ok")
        self.assertEqual(report.blocker_report.summary["semantic_write_allowed"], True)
        self.assertEqual(report.blocker_report.summary["validator_write_allowed"], True)
        self.assertEqual(report.blocker_report.summary["write_allowed"], True)
        self.assertEqual(report.blocker_report.summary["READY_FOR_DISPOSABLE_WRITE_PRE_AUDIT"], True)

    def test_semantic_unresolved_keeps_write_allowed_false_even_if_validators_green(self) -> None:
        report = ArollEngine(validators=PassingValidators()).run(semantic_run_input())

        self.assertEqual(report.blocker_report.summary["semantic_write_allowed"], False)
        self.assertEqual(report.blocker_report.summary["validator_write_allowed"], False)
        self.assertEqual(report.blocker_report.summary["write_allowed"], False)
        self.assertIn("V21_FATAL_MODIFIER_REDUNDANCY_UNRESOLVED", [blocker.code for blocker in report.blocker_report.blockers])


if __name__ == "__main__":
    unittest.main()
