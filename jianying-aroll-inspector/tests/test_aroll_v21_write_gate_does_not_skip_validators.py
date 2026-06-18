from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Any

from aroll_v21 import ArollEngine
from tests.test_aroll_v21_semantic_unconfigured_dryrun_policy import semantic_run_input
from tests.test_aroll_v21_write_allowed_aggregates_validator_blockers import FailingRepeatValidators


class WriterWithFallback:
    def build_write_plan(self, source_graph, captions) -> tuple[dict[str, Any], list]:
        return (
            {
                "canonical_caption_template_id": "template_1",
                "no_writer_fallback": False,
                "writer_fallback_count": 1,
                "materials": [],
                "segments": [],
                "output_material_fingerprints": [],
            },
            [],
        )


class ArollV21WriteGateDoesNotSkipValidatorsTests(unittest.TestCase):
    def test_sacrificial_postwrite_skip_does_not_skip_validator_fatal(self) -> None:
        report = ArollEngine(validators=FailingRepeatValidators()).run(
            replace(semantic_run_input(mode="write", text="普通字幕"), postwrite_mode="skipped_for_sacrificial_draft")
        )
        self.assertEqual(report.status, "blocked")
        self.assertIn("FINAL_REPEAT_VALIDATOR_FAILED", [blocker.code for blocker in report.blocker_report.blockers])
        self.assertFalse(report.blocker_report.summary["write_allowed"])

    def test_sacrificial_postwrite_skip_does_not_skip_writer_fallback(self) -> None:
        report = ArollEngine(writer=WriterWithFallback()).run(
            replace(semantic_run_input(mode="write", text="普通字幕"), postwrite_mode="skipped_for_sacrificial_draft")
        )
        self.assertEqual(report.status, "blocked")
        self.assertIn("SUBTITLE_STYLE_VALIDATOR_FAILED", [blocker.code for blocker in report.blocker_report.blockers])
        self.assertEqual(report.blocker_report.summary["writer_fallback_count"], 1)
        self.assertFalse(report.blocker_report.summary["write_allowed"])

    def test_sacrificial_postwrite_skip_does_not_skip_semantic_unresolved(self) -> None:
        report = ArollEngine().run(replace(semantic_run_input(mode="write"), postwrite_mode="skipped_for_sacrificial_draft"))
        self.assertEqual(report.status, "blocked")
        self.assertGreater(report.decision_plan.semantic_unresolved_count, 0)
        self.assertFalse(report.blocker_report.summary["semantic_write_allowed"])
        self.assertFalse(report.blocker_report.summary["write_allowed"])


if __name__ == "__main__":
    unittest.main()
