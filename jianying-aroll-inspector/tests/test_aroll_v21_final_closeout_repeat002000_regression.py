from __future__ import annotations

import unittest
from pathlib import Path

from aroll_v21 import ArollEngine
from tests.test_aroll_v21_semantic_gate_resolved_by_final_timeline import resolved_modifier_input


ROOT = Path(__file__).resolve().parents[1]


class ArollV21FinalCloseoutRepeat002000RegressionTests(unittest.TestCase):
    def test_repeat002000_resolved_by_final_timeline_trace_and_summary(self) -> None:
        report = ArollEngine().run(resolved_modifier_input())

        self.assertEqual(report.decision_plan.semantic_unresolved_count, 0)
        self.assertTrue(report.blocker_report.summary["semantic_write_allowed"])
        self.assertEqual(report.blocker_report.summary["semantic_unresolved_count"], 0)
        self.assertNotIn("SEMANTIC_DECISION_NOT_PROVIDED", [blocker.code for blocker in report.blocker_report.blockers])
        self.assertIn("肆意的踩踏", "".join(caption.text for caption in report.captions))
        self.assertNotIn("随意的肆意的踩踏", "".join(caption.text for caption in report.captions))

    def test_src_does_not_hardcode_closeout_sample_texts(self) -> None:
        forbidden = ["随意的肆意的踩踏", "肆意的踩踏", "自信的人真的能拿到结果"]
        hits = []
        for path in (ROOT / "src" / "aroll_v21").rglob("*.py"):
            text = path.read_text("utf-8")
            for item in forbidden:
                if item in text:
                    hits.append(f"{path.relative_to(ROOT)}:{item}")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
