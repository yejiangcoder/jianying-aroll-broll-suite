from __future__ import annotations

import unittest

from dataclasses import replace

from aroll_v21 import ArollEngine
from tests.test_aroll_v21_semantic_unconfigured_dryrun_policy import semantic_run_input


class ArollV21PostwriteDecryptUnavailableOverrideTests(unittest.TestCase):
    def test_unavailable_mode_fails_postwrite_gate(self) -> None:
        report = ArollEngine().run(replace(semantic_run_input(text="普通字幕"), postwrite_mode="unavailable"))
        postwrite = report.validator_report["postwrite_material_validator"]
        self.assertEqual(report.status, "blocked")
        self.assertFalse(postwrite["postwrite_material_gate_ok"])
        self.assertEqual(postwrite["block_reason"], "ACTUAL_POSTWRITE_DECRYPT_UNAVAILABLE")

    def test_sacrificial_mode_only_downgrades_postwrite_decrypt_unavailable(self) -> None:
        report = ArollEngine().run(
            replace(semantic_run_input(text="普通字幕"), postwrite_mode="skipped_for_sacrificial_draft")
        )
        postwrite = report.validator_report["postwrite_material_validator"]
        self.assertEqual(report.status, "ok")
        self.assertTrue(postwrite["postwrite_material_gate_ok"])
        self.assertFalse(postwrite["postwrite_decrypt_ok"])
        self.assertEqual(postwrite["postwrite_mode"], "skipped_for_sacrificial_draft")
        self.assertTrue(postwrite["postwrite_decrypt_skipped_for_sacrificial_draft"])
        self.assertEqual(postwrite["postwrite_decrypt_skip_reason"], "ACTUAL_POSTWRITE_DECRYPT_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
