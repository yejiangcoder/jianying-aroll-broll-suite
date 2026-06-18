from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput


ROOT = Path(__file__).resolve().parents[1]


def _material_segment(material_id: str, start_us: int) -> tuple[dict, dict]:
    fixture = json.loads((ROOT / "fixtures" / "real_materials" / "normal_caption_template.json").read_text("utf-8"))
    material = copy.deepcopy(fixture["material"])
    segment = copy.deepcopy(fixture["segment"])
    material["id"] = material_id
    segment["id"] = f"{material_id}_segment"
    segment["material_id"] = material_id
    segment["target_timerange"] = {"start": start_us, "duration": 500_000}
    return material, segment


def _run_pair(left: str, right: str):
    material_left, segment_left = _material_segment("text_left", 0)
    material_right, segment_right = _material_segment("text_right", 600_000)
    return ArollEngine().run(
        ArollRunInput(
            source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 2_000_000}],
            word_timeline=[
                {
                    "word_id": "w_left",
                    "word_text": left,
                    "source_start_us": 0,
                    "source_end_us": 500_000,
                    "source_material_id": "main",
                    "source_segment_id": "clip",
                    "subtitle_uid": "s_left",
                    "subtitle_index": 1,
                },
                {
                    "word_id": "w_right",
                    "word_text": right,
                    "source_start_us": 600_000,
                    "source_end_us": 1_200_000,
                    "source_material_id": "main",
                    "source_segment_id": "clip",
                    "subtitle_uid": "s_right",
                    "subtitle_index": 2,
                },
            ],
            subtitles=[
                {"subtitle_uid": "s_left", "subtitle_index": 1, "text": left, "word_ids": ["w_left"], "text_material_id": "text_left"},
                {"subtitle_uid": "s_right", "subtitle_index": 2, "text": right, "word_ids": ["w_right"], "text_material_id": "text_right"},
            ],
            text_materials=[material_left, material_right],
            text_segments=[segment_left, segment_right],
            postwrite_mode="simulated",
        )
    )


class ArollV21ValidatorRepeatSamplesRound8Tests(unittest.TestCase):
    def test_comment_prefix_sample_no_longer_reaches_final_or_hidden_repeat_validator(self) -> None:
        report = _run_pair("评论区也全是哇", "评论区也全是哇塞")

        self.assertEqual(report.status, "ok", [blocker.code for blocker in report.blocker_report.blockers])
        self.assertEqual([caption.text for caption in report.captions], ["评论区也全是哇塞"])
        self.assertTrue(report.validator_report["final_repeat_validator"]["final_repeat_gate_passed"])
        self.assertTrue(report.validator_report["hidden_audio_repeat_validator"]["hidden_audio_repeat_gate_passed"])

    def test_reopen_prefix_sample_no_longer_reaches_final_or_hidden_repeat_validator(self) -> None:
        report = _run_pair("重新上", "重新上桌")

        self.assertEqual(report.status, "ok", [blocker.code for blocker in report.blocker_report.blockers])
        self.assertEqual([caption.text for caption in report.captions], ["重新上桌"])
        self.assertTrue(report.validator_report["final_repeat_validator"]["final_repeat_gate_passed"])
        self.assertTrue(report.validator_report["hidden_audio_repeat_validator"]["hidden_audio_repeat_gate_passed"])


if __name__ == "__main__":
    unittest.main()
