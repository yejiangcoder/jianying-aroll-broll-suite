from __future__ import annotations

import json
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput


ROOT = Path(__file__).resolve().parents[1]


def _material_rows() -> tuple[list[dict], list[dict]]:
    payload = json.loads((ROOT / "fixtures" / "real_materials" / "normal_caption_template.json").read_text("utf-8"))
    return [payload["material"]], [payload["segment"]]


def _run_text(text: str) -> object:
    text_materials, text_segments = _material_rows()
    return ArollEngine().run(
        ArollRunInput(
            source_segments=[{"id": "clip_1", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000000}],
            word_timeline=[
                {"word_id": "w1", "word_text": text, "start_us": 0, "end_us": 1000000, "subtitle_uid": "s1", "subtitle_index": 1}
            ],
            subtitles=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": text, "word_ids": ["w1"]}],
            text_materials=text_materials,
            text_segments=text_segments,
        )
    )


class ArollV21CjkANotANotHiddenRepeatTests(unittest.TestCase):
    def test_legal_a_not_a_question_does_not_generate_hidden_repeat_blocker(self) -> None:
        for text in (
            "就国南能不能不要规训自己人呐",
            "他会不会继续解释",
            "你要不要重新选择",
            "这是不是一个问题",
            "你有没有发现",
        ):
            with self.subTest(text=text):
                report = _run_text(text)
                codes = [blocker.code for blocker in report.blocker_report.blockers]
                self.assertNotIn("UNIT_SPLIT_REQUIRES_HUMAN_REVIEW", codes)
                self.assertFalse([cluster for cluster in report.repeat_clusters if cluster.repeat_type == "hidden_audio_repeat"])

    def test_repeated_a_not_a_phrase_still_repeats(self) -> None:
        report = _run_text("能不能能不能继续")

        self.assertTrue([cluster for cluster in report.repeat_clusters if cluster.repeat_type == "hidden_audio_repeat"])
        self.assertNotEqual("".join(caption.text for caption in report.captions), "能不能能不能继续")


if __name__ == "__main__":
    unittest.main()
