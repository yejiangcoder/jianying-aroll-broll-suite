from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.create_aroll_v21_semantic_decisions_template import build_suggested_for_rough_cut, main


class ArollV21SemanticTemplateNoSilentEmptyOutputTests(unittest.TestCase):
    def test_payload_count_positive_never_silently_outputs_empty_decisions(self) -> None:
        suggested = build_suggested_for_rough_cut(
            [
                {
                    "cluster_id": "repeat_unknown",
                    "type": "unsupported_semantic_payload",
                    "repeat_type": "unknown_repeat",
                    "allowed_decisions": ["keep_all", "requires_human_review"],
                }
            ]
        )

        self.assertEqual(len(suggested), 1)
        self.assertEqual(suggested[0]["cluster_id"], "repeat_unknown")
        self.assertEqual(suggested[0]["decision"], "requires_human_review")
        self.assertIn("TEMPLATE_UNSUPPORTED_SEMANTIC_PAYLOAD_TYPE", suggested[0]["reason"])

    def test_cli_suggest_rough_cut_fails_loudly_for_unsupported_payload_after_writing_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload_path = root / "semantic_request_payloads.json"
            output_path = root / "semantic_decisions.roughcut.json"
            payload_path.write_text(
                json.dumps(
                    [
                        {
                            "cluster_id": "repeat_unknown",
                            "type": "unsupported_semantic_payload",
                            "repeat_type": "unknown_repeat",
                        }
                    ],
                    ensure_ascii=False,
                ),
                "utf-8",
            )

            import sys

            old_argv = sys.argv
            try:
                sys.argv = ["create", str(payload_path), "-o", str(output_path), "--suggest-rough-cut"]
                with self.assertRaises(SystemExit) as raised:
                    main()
            finally:
                sys.argv = old_argv

            self.assertIn("TEMPLATE_CANNOT_SUGGEST_DECISION", str(raised.exception))
            decisions = json.loads(output_path.read_text("utf-8"))
            self.assertEqual(len(decisions), 1)
            self.assertIn("TEMPLATE_UNSUPPORTED_SEMANTIC_PAYLOAD_TYPE", decisions[0]["reason"])

    def test_missing_cluster_id_gets_explicit_error_row(self) -> None:
        suggested = build_suggested_for_rough_cut([{"type": "single_variant_modifier_redundancy"}])

        self.assertEqual(len(suggested), 1)
        self.assertEqual(suggested[0]["decision"], "requires_human_review")
        self.assertIn("payload is missing cluster_id", suggested[0]["reason"])

    def test_cli_non_object_payloads_fail_instead_of_writing_empty_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload_path = root / "semantic_request_payloads.json"
            output_path = root / "semantic_decisions.roughcut.json"
            payload_path.write_text(json.dumps(["not-an-object"], ensure_ascii=False), "utf-8")

            import sys

            old_argv = sys.argv
            try:
                sys.argv = ["create", str(payload_path), "-o", str(output_path), "--suggest-rough-cut"]
                with self.assertRaises(SystemExit) as raised:
                    main()
            finally:
                sys.argv = old_argv

            self.assertIn("semantic request payload rows must be objects", str(raised.exception))
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
