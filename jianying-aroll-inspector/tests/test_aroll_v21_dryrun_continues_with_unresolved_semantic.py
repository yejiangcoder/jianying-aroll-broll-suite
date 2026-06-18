from __future__ import annotations

import unittest

from aroll_v21 import ArollEngine
from tests.test_aroll_v21_semantic_unconfigured_dryrun_policy import semantic_run_input


class ArollV21DryRunContinuesWithUnresolvedSemanticTests(unittest.TestCase):
    def test_dryrun_not_stopped_at_decision_stage_by_unresolved_semantic(self) -> None:
        report = ArollEngine().run(semantic_run_input())

        self.assertNotEqual((report.blocker_report.summary or {}).get("stage"), "decision")
        self.assertTrue(report.final_timeline)
        self.assertTrue(report.material_write_plan)
        self.assertTrue(report.validator_report)


if __name__ == "__main__":
    unittest.main()
