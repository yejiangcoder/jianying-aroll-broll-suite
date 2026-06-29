from __future__ import annotations

from copy import deepcopy
import unittest

from aroll_v21 import ArollEngine
from aroll_v21.validate import ReadOnlyValidators
from tests.test_aroll_v21_compiler import repeated_run_input


class ArollV21LegacyGateReadonlyContractTests(unittest.TestCase):
    def test_legacy_gate_wrappers_do_not_mutate_compiler_renderer_writer_outputs(self) -> None:
        report = ArollEngine().run(repeated_run_input())
        source_graph = report.source_graph
        self.assertIsNotNone(source_graph)
        final_timeline = deepcopy(report.final_timeline)
        captions = deepcopy(report.captions)
        material_write_plan = deepcopy(report.material_write_plan)

        validator_report = ReadOnlyValidators().run(
            source_graph=source_graph,
            decision_plan=report.decision_plan,
            final_timeline=final_timeline,
            captions=captions,
            material_write_plan=material_write_plan,
            postwrite_mode="simulated",
        )
        self.assertTrue(validator_report["validators_read_only"])
        self.assertIn("final_caption_visible_repeat_gate", validator_report)
        self.assertTrue(validator_report["final_caption_visible_repeat_gate"]["gate_passed"])
        self.assertTrue(validator_report["quality_gate_report"]["final_caption_visible_repeat_gate_present"])
        self.assertTrue(validator_report["quality_gate_report"]["final_caption_visible_repeat_gate"]["gate_passed"])
        self.assertEqual(final_timeline, report.final_timeline)
        self.assertEqual(captions, report.captions)
        self.assertEqual(material_write_plan, report.material_write_plan)


if __name__ == "__main__":
    unittest.main()
