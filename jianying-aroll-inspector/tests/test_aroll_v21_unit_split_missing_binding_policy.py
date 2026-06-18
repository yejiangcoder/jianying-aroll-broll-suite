from __future__ import annotations

import unittest
from pathlib import Path

from tools.create_aroll_v21_semantic_decisions_template import build_suggested_for_rough_cut


PHYSICAL_FIELDS = {
    "source_start_us",
    "source_end_us",
    "target_start_us",
    "target_end_us",
    "edl",
    "final_edl",
    "draft_content",
    "material_id",
    "segment_id",
}


def unit_split_payload(**overrides):
    payload = {
        "cluster_id": "repeat_unit_split",
        "type": "unit_split_requires_human_review",
        "repeat_type": "unit_split",
        "allowed_decisions": ["apply_suggested_split", "keep_all", "requires_human_review"],
        "suggested_for_rough_cut": "apply_suggested_split",
        "split_summary": {
            "drop_text": "A",
            "keep_text": "B",
            "result_text": "B",
            "drop_word_ids": ["w1"],
            "keep_word_ids": ["w2"],
            "binding": "whole_word",
        },
    }
    payload.update(overrides)
    return payload


class ArollV21UnitSplitMissingBindingPolicyTests(unittest.TestCase):
    def test_whole_word_binding_applies_suggested_split(self) -> None:
        suggested = build_suggested_for_rough_cut([unit_split_payload()])

        self.assertEqual(suggested[0]["decision"], "apply_suggested_split")
        self.assertFalse(suggested[0]["requires_human_review"])

    def test_missing_binding_keeps_all_when_allowed(self) -> None:
        payload = unit_split_payload(
            split_summary={
                "drop_text": "A",
                "keep_text": "",
                "result_text": "",
                "drop_word_ids": [],
                "keep_word_ids": [],
                "binding": "missing",
            }
        )

        suggested = build_suggested_for_rough_cut([payload])

        self.assertEqual(suggested[0]["decision"], "keep_all")
        self.assertEqual(
            suggested[0]["reason"],
            "rough cut closeout: unit split lacks safe whole-word binding; keep all to avoid unsafe cut",
        )
        self.assertEqual(suggested[0]["confidence"], 0.65)
        self.assertFalse(suggested[0]["requires_human_review"])

    def test_incomplete_word_ids_keep_all_when_allowed(self) -> None:
        payload = unit_split_payload(
            split_summary={
                "drop_text": "A",
                "keep_text": "B",
                "result_text": "B",
                "drop_word_ids": ["w1"],
                "keep_word_ids": [],
                "binding": "whole_word",
            }
        )

        suggested = build_suggested_for_rough_cut([payload])

        self.assertEqual(suggested[0]["decision"], "keep_all")
        self.assertFalse(suggested[0]["requires_human_review"])

    def test_missing_binding_without_keep_all_fails_loudly(self) -> None:
        payload = unit_split_payload(
            allowed_decisions=["apply_suggested_split", "requires_human_review"],
            split_summary={
                "drop_text": "A",
                "keep_text": "",
                "result_text": "",
                "drop_word_ids": [],
                "keep_word_ids": [],
                "binding": "missing",
            },
        )

        suggested = build_suggested_for_rough_cut([payload])

        self.assertEqual(suggested[0]["decision"], "requires_human_review")
        self.assertTrue(suggested[0]["requires_human_review"])
        self.assertIn("TEMPLATE_CANNOT_SUGGEST_DECISION", suggested[0]["reason"])

    def test_suggested_decision_not_allowed_fails_loudly_even_when_keep_all_allowed(self) -> None:
        payload = unit_split_payload(allowed_decisions=["keep_all", "requires_human_review"])

        suggested = build_suggested_for_rough_cut([payload])

        self.assertEqual(suggested[0]["decision"], "requires_human_review")
        self.assertIn("TEMPLATE_SUGGESTED_DECISION_NOT_ALLOWED", suggested[0]["reason"])

    def test_decision_rows_do_not_include_physical_fields(self) -> None:
        suggested = build_suggested_for_rough_cut(
            [
                unit_split_payload(
                    source_start_us=1,
                    source_end_us=2,
                    target_start_us=3,
                    target_end_us=4,
                    edl=[],
                    final_edl=[],
                    draft_content={},
                    material_id="forbidden",
                    segment_id="forbidden",
                )
            ]
        )

        self.assertFalse(PHYSICAL_FIELDS & set(suggested[0]))

    def test_no_forbidden_v20_or_material_text_rows_in_template_tool(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "tools" / "create_aroll_v21_semantic_decisions_template.py").read_text("utf-8")
        for token in (
            "material_text_rows",
            "aroll_phase4e",
            "aroll_downstream_repair_pipeline",
            "aroll_repair_applier",
            "downstream repair",
        ):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
