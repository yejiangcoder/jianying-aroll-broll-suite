from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21.operator import ArollV21OperatorConfig, run_operator
from tests.test_aroll_v21_semantic_unconfigured_dryrun_policy import semantic_run_input
from aroll_v21.ir import dataclass_to_dict


class ArollV21UnresolvedSemanticBlocksWriteTests(unittest.TestCase):
    def test_write_mode_blocks_unresolved_semantic_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "input.json"
            run_dir = root / "run"
            run_input = semantic_run_input(mode="write")
            input_path.write_text(
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

            summary = run_operator(ArollV21OperatorConfig(mode="write", run_dir=run_dir, input_json=input_path, simulate_write=True))
            blocker_report = json.loads((run_dir / "blocker_report.json").read_text("utf-8"))

            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["write_allowed"], False)
            self.assertIn("DEEPSEEK_SEMANTIC_PLANNER_NOT_CONFIGURED", summary["blocker_codes"])
            self.assertEqual(blocker_report["blockers"][0]["severity"], "write_blocker")
            self.assertEqual(blocker_report["blockers"][0]["context"]["allows_dry_run_discovery"], True)


if __name__ == "__main__":
    unittest.main()
