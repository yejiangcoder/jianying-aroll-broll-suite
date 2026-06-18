from __future__ import annotations

import json
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput


ROOT = Path(__file__).resolve().parents[1]


def _material_rows() -> tuple[list[dict], list[dict]]:
    payload = json.loads((ROOT / "fixtures" / "real_materials" / "normal_caption_template.json").read_text("utf-8"))
    return [payload["material"]], [payload["segment"]]


class ArollV21IntraEditUnitRepeatSplitTests(unittest.TestCase):
    def test_same_unit_duplicate_phrase_is_removed_by_word_split(self) -> None:
        text_materials, text_segments = _material_rows()
        report = ArollEngine().run(
            ArollRunInput(
                source_segments=[{"id": "clip_1", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000000}],
                word_timeline=[
                    {"word_id": "w1", "word_text": "你们是在", "start_us": 0, "end_us": 300000, "subtitle_uid": "s1", "subtitle_index": 1},
                    {"word_id": "w2", "word_text": "你们是在", "start_us": 300000, "end_us": 600000, "subtitle_uid": "s1", "subtitle_index": 1},
                    {"word_id": "w3", "word_text": "集体做空", "start_us": 600000, "end_us": 1000000, "subtitle_uid": "s1", "subtitle_index": 1},
                ],
                subtitles=[
                    {"subtitle_uid": "s1", "subtitle_index": 1, "text": "你们是在你们是在集体做空", "word_ids": ["w1", "w2", "w3"]}
                ],
                text_materials=text_materials,
                text_segments=text_segments,
            )
        )

        self.assertEqual(report.status, "ok", [blocker.code for blocker in report.blocker_report.blockers])
        self.assertEqual("".join(caption.text for caption in report.captions), "你们是在集体做空")
        self.assertTrue(report.decision_plan.split_decisions)

    def test_partial_multichar_word_split_blocks_instead_of_cutting_inside_word(self) -> None:
        text_materials, text_segments = _material_rows()
        report = ArollEngine().run(
            ArollRunInput(
                source_segments=[{"id": "clip_1", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000000}],
                word_timeline=[
                    {"word_id": "w1", "word_text": "然后然后", "start_us": 0, "end_us": 500000, "subtitle_uid": "s1", "subtitle_index": 1},
                    {"word_id": "w2", "word_text": "他开始解释", "start_us": 500000, "end_us": 1000000, "subtitle_uid": "s1", "subtitle_index": 1},
                ],
                subtitles=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": "然后然后他开始解释", "word_ids": ["w1", "w2"]}],
                text_materials=text_materials,
                text_segments=text_segments,
            )
        )

        self.assertEqual(report.status, "blocked")
        self.assertIn("UNIT_SPLIT_REQUIRES_HUMAN_REVIEW", [blocker.code for blocker in report.blocker_report.blockers])


if __name__ == "__main__":
    unittest.main()
