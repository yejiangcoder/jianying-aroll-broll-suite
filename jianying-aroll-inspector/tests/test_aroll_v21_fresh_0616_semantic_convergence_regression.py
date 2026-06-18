from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.create_aroll_v21_semantic_decisions_template import build_suggested_for_rough_cut, main


def stage2_unit_split_binding_missing_payloads() -> list[dict]:
    return [
        {
            "cluster_id": "repeat_stage2_a",
            "type": "unit_split_requires_human_review",
            "repeat_type": "unit_split",
            "source_repeat_type": "hidden_audio_repeat",
            "text": "AAX",
            "reason": "UNIT_SPLIT_REQUIRES_HUMAN_REVIEW",
            "allowed_decisions": ["apply_suggested_split", "keep_all", "requires_human_review"],
            "suggested_for_rough_cut": "apply_suggested_split",
            "split_summary": {
                "drop_text": "A",
                "keep_text": "",
                "result_text": "",
                "drop_word_ids": [],
                "keep_word_ids": [],
                "binding": "missing",
            },
        },
        {
            "cluster_id": "repeat_stage2_b",
            "type": "unit_split_requires_human_review",
            "repeat_type": "unit_split",
            "source_repeat_type": "hidden_audio_repeat",
            "text": "BBY",
            "reason": "UNIT_SPLIT_REQUIRES_HUMAN_REVIEW",
            "allowed_decisions": ["apply_suggested_split", "keep_all", "requires_human_review"],
            "suggested_for_rough_cut": "apply_suggested_split",
            "split_summary": {
                "drop_text": "B",
                "keep_text": "",
                "result_text": "",
                "drop_word_ids": [],
                "keep_word_ids": [],
                "binding": "missing",
            },
        },
    ]


class ArollV21Fresh0616SemanticConvergenceRegressionTests(unittest.TestCase):
    def test_stage2_unit_split_binding_missing_payloads_keep_all_not_empty(self) -> None:
        suggested = build_suggested_for_rough_cut(stage2_unit_split_binding_missing_payloads())

        self.assertEqual(len(suggested), 2)
        for row in suggested:
            self.assertEqual(row["decision"], "keep_all")
            self.assertFalse(row["requires_human_review"])
            self.assertIn("lacks safe whole-word binding", row["reason"])

    def test_cli_stage2_unit_split_binding_missing_payloads_writes_keep_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload_path = root / "semantic_request_payloads.json"
            output_path = root / "semantic_decisions.roughcut.json"
            payload_path.write_text(json.dumps(stage2_unit_split_binding_missing_payloads(), ensure_ascii=False), "utf-8")

            import sys

            old_argv = sys.argv
            try:
                sys.argv = ["create", str(payload_path), "-o", str(output_path), "--suggest-rough-cut"]
                self.assertEqual(main(), 0)
            finally:
                sys.argv = old_argv

            decisions = json.loads(output_path.read_text("utf-8"))
            self.assertEqual(len(decisions), 2)
            self.assertTrue(all(row["decision"] == "keep_all" for row in decisions))
            self.assertTrue(all(not row["requires_human_review"] for row in decisions))


if __name__ == "__main__":
    unittest.main()
