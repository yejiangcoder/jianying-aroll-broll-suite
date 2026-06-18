from __future__ import annotations

import json
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput


ROOT = Path(__file__).resolve().parents[1]


def _material_rows() -> tuple[list[dict], list[dict]]:
    payload = json.loads((ROOT / "fixtures" / "real_materials" / "normal_caption_template.json").read_text("utf-8"))
    return [payload["material"]], [payload["segment"]]


def final_modifier_fixture_input(*, mode: str = "dry-run") -> ArollRunInput:
    text_materials, text_segments = _material_rows()
    words = []
    subtitles = []
    cursor = 0
    parts = ["随意的", "肆意的踩踏"]
    for subtitle_index, text in enumerate(parts, start=1):
        word_ids = []
        for char in text:
            word_id = f"w_{len(words) + 1:06d}"
            word_ids.append(word_id)
            words.append(
                {
                    "word_id": word_id,
                    "word_text": char,
                    "source_start_us": cursor,
                    "source_end_us": cursor + 90_000,
                    "source_material_id": "main_video",
                    "source_segment_id": "clip_1",
                    "subtitle_uid": f"s{subtitle_index}",
                    "subtitle_index": subtitle_index,
                }
            )
            cursor += 90_000
        subtitles.append(
            {
                "subtitle_uid": f"s{subtitle_index}",
                "subtitle_index": subtitle_index,
                "text": text,
                "word_ids": word_ids,
            }
        )
    return ArollRunInput(
        mode=mode,  # type: ignore[arg-type]
        source_segments=[{"id": "clip_1", "material_id": "main_video", "source_start_us": 0, "source_end_us": cursor + 1_000_000}],
        word_timeline=words,
        subtitles=subtitles,
        text_materials=text_materials,
        text_segments=text_segments,
        postwrite_mode="simulated",
    )


class ArollV21SemanticRequestModifierRedundancyTests(unittest.TestCase):
    def test_final_validator_modifier_redundancy_emits_semantic_request_payload(self) -> None:
        report = ArollEngine().run(final_modifier_fixture_input())

        payloads = report.decision_plan.semantic_request_payloads
        self.assertTrue(payloads)
        payload = payloads[0]
        self.assertEqual(payload["cluster_id"], "repeat_002000")
        self.assertEqual(payload["repeat_type"], "modifier_redundancy")
        self.assertEqual(payload["type"], "single_variant_modifier_redundancy")
        self.assertEqual(payload["allowed_decisions"], ["drop_redundant_modifier", "requires_human_review", "no_decision"])
        self.assertFalse(payload["fatal_modifier_redundancy_keep_all_allowed"])
        self.assertEqual(payload["suggested_for_rough_cut"], "drop_redundant_modifier")
        for required in ("issue_id", "source_start_us", "source_end_us", "target_start_us", "target_end_us", "word_ids"):
            self.assertIn(required, payload)
        payload_text = json.dumps(payload, ensure_ascii=False)
        for forbidden in ("material_id",):
            self.assertNotIn(forbidden, payload_text)
        self.assertNotIn("INTERNAL_SEMANTIC_REQUEST_MISSING_FOR_FATAL_REPEAT", [blocker.code for blocker in report.blocker_report.blockers])


if __name__ == "__main__":
    unittest.main()
