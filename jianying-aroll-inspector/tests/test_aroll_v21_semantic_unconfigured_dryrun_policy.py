from __future__ import annotations

import json
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput


ROOT = Path(__file__).resolve().parents[1]


def _material_rows() -> tuple[list[dict], list[dict]]:
    payload = json.loads((ROOT / "fixtures" / "real_materials" / "normal_caption_template.json").read_text("utf-8"))
    return [payload["material"]], [payload["segment"]]


def semantic_run_input(*, mode: str = "dry-run", text: str = "随意的肆意的踩踏") -> ArollRunInput:
    text_materials, text_segments = _material_rows()
    return ArollRunInput(
        mode=mode,  # type: ignore[arg-type]
        source_segments=[{"id": "clip_1", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000000}],
        word_timeline=[
            {"word_id": "w1", "word_text": text, "start_us": 0, "end_us": 1000000, "subtitle_uid": "s1", "subtitle_index": 1}
        ],
        subtitles=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": text, "word_ids": ["w1"]}],
        text_materials=text_materials,
        text_segments=text_segments,
        postwrite_mode="simulated",
    )


class ArollV21SemanticUnconfiguredDryRunPolicyTests(unittest.TestCase):
    def test_unconfigured_semantic_generates_payload_and_continues_to_later_stages(self) -> None:
        report = ArollEngine().run(semantic_run_input())

        self.assertTrue(report.decision_plan.semantic_request_payloads)
        self.assertTrue(report.decision_trace)
        self.assertEqual(report.decision_plan.semantic_unresolved_count, 1)
        self.assertFalse(report.decision_plan.write_allowed)
        self.assertTrue(report.final_timeline)
        self.assertTrue(report.captions)
        self.assertTrue(report.material_write_plan.get("canonical_caption_template_id"))
        self.assertTrue(report.validator_report)
        self.assertEqual(report.blocker_report.summary["write_allowed"], False)
        self.assertEqual(report.blocker_report.summary["dry_run_continued_for_discovery"], True)


if __name__ == "__main__":
    unittest.main()
