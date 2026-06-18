from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21.operator import ArollV21OperatorConfig, run_operator
from tests.test_aroll_v21_semantic_unconfigured_dryrun_policy import semantic_run_input


def _write_input(path: Path) -> None:
    run_input = semantic_run_input(mode="dry-run")
    path.write_text(
        json.dumps(
            {
                "source_segments": run_input.source_segments,
                "word_timeline": run_input.word_timeline,
                "subtitles": run_input.subtitles,
                "text_materials": run_input.text_materials,
                "text_segments": run_input.text_segments,
            },
            ensure_ascii=False,
        ),
        "utf-8",
    )


class ArollV21SemanticUnresolvedWriteGateTests(unittest.TestCase):
    def test_keep_all_semantic_decisions_json_does_not_clear_modifier_write_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_json = root / "input.json"
            decisions_json = root / "semantic_decisions.json"
            _write_input(input_json)
            decisions_json.write_text(
                json.dumps(
                    [
                        {
                            "cluster_id": "repeat_002000",
                            "decision": "keep_all",
                            "reason": "not confidently redundant",
                            "confidence": 0.8,
                            "requires_human_review": False,
                        }
                    ],
                    ensure_ascii=False,
                ),
                "utf-8",
            )

            summary = run_operator(
                ArollV21OperatorConfig(
                    mode="dry-run",
                    run_dir=root / "run",
                    input_json=input_json,
                    semantic_decisions_json=decisions_json,
                )
            )

            self.assertEqual(summary["semantic_unresolved_count"], 1)
            self.assertNotIn("DEEPSEEK_SEMANTIC_PLANNER_NOT_CONFIGURED", summary["blocker_codes"])
            self.assertIn("V21_FATAL_MODIFIER_REDUNDANCY_UNRESOLVED", summary["blocker_codes"])
            self.assertFalse(summary["write_allowed"])
            decision_plan = json.loads((root / "run" / "decision_plan.json").read_text("utf-8"))
            self.assertEqual(decision_plan["decisions"], [])
            self.assertFalse(decision_plan["write_allowed"])
            self.assertEqual(len(decision_plan["semantic_request_payloads"]), 1)

    def test_missing_semantic_decisions_keep_write_disallowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_json = root / "input.json"
            _write_input(input_json)

            summary = run_operator(ArollV21OperatorConfig(mode="dry-run", run_dir=root / "run", input_json=input_json))

            self.assertGreater(summary["semantic_unresolved_count"], 0)
            self.assertEqual(summary["write_allowed"], False)


if __name__ == "__main__":
    unittest.main()
