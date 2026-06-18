from __future__ import annotations

import unittest

from aroll_v21 import ArollEngine
from tests.test_aroll_v21_semantic_unconfigured_dryrun_policy import semantic_run_input


class ArollV21WriterValidatorReachableInDryRunTests(unittest.TestCase):
    def test_writer_and_validators_run_even_when_semantic_requires_human_review(self) -> None:
        report = ArollEngine().run(semantic_run_input())

        self.assertTrue(report.material_write_plan.get("materials"))
        self.assertTrue(report.material_write_plan.get("segments"))
        self.assertIn("validator_report_ok", report.validator_report)
        self.assertEqual(report.validator_report["semantic_final_review_validator"]["write_allowed"], False)


if __name__ == "__main__":
    unittest.main()
