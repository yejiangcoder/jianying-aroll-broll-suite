from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.create_aroll_v21_semantic_decisions_template import build_suggested_for_rough_cut, build_template, main


class ArollV21SemanticDecisionsTemplateFinalTargetRepeatTests(unittest.TestCase):
    def test_final_target_repeat_payload_gets_conservative_template_and_rough_cut_suggestion(self) -> None:
        payloads = [
            {
                "cluster_id": "final_target_repeat_tc_0001",
                "type": "final_target_repeat",
                "cluster_type": "semantic_containment_take",
                "severity": "medium",
                "requires_llm": True,
            },
            {
                "cluster_id": "repeat_002000",
                "repeat_type": "modifier_redundancy",
            },
        ]

        template = build_template(payloads)
        suggested = build_suggested_for_rough_cut(payloads)

        self.assertEqual(template[0]["decision"], "keep_all")
        self.assertTrue(template[0]["requires_human_review"])
        self.assertEqual(suggested[0]["decision"], "keep_longest_drop_others")
        self.assertFalse(suggested[0]["requires_human_review"])
        self.assertEqual(suggested[1]["decision"], "drop_redundant_modifier")
        self.assertFalse(suggested[1]["requires_human_review"])

    def test_cli_writes_suggested_file_next_to_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload_path = root / "semantic_request_payloads.json"
            output_path = root / "semantic_decisions.template.json"
            payload_path.write_text(
                json.dumps(
                    [
                        {
                            "cluster_id": "final_target_repeat_tc_0001",
                            "type": "final_target_repeat",
                            "cluster_type": "semantic_containment_take",
                        }
                    ],
                    ensure_ascii=False,
                ),
                "utf-8",
            )

            import sys

            old_argv = sys.argv
            try:
                sys.argv = ["create", str(payload_path), "-o", str(output_path)]
                self.assertEqual(main(), 0)
            finally:
                sys.argv = old_argv

            suggested_path = root / "semantic_decisions.suggested_for_rough_cut.json"
            self.assertTrue(output_path.exists())
            self.assertTrue(suggested_path.exists())
            suggested = json.loads(suggested_path.read_text("utf-8"))
            self.assertEqual(suggested[0]["decision"], "keep_longest_drop_others")


if __name__ == "__main__":
    unittest.main()
