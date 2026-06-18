from __future__ import annotations

import unittest

from aroll_v21 import ArollEngine, ArollRunInput
from tests.test_aroll_v21_captions_after_prefix_drop import _template_rows


class ArollV21Fresh0616BoundaryRepeatRegressionTests(unittest.TestCase):
    def test_boundary_suffix_prefix_and_exact_target_repeat_do_not_reach_final_validators(self) -> None:
        materials, text_segments = _template_rows()
        words = []
        subtitles = []
        cursor = 0
        groups = [
            ["在", "舞台", "中央", "大声", "说"],
            ["中央", "大声", "说", "话的", "自己"],
            ["把输掉的"],
            ["过渡内容"],
            ["把输掉的"],
        ]
        for subtitle_index, group in enumerate(groups, start=1):
            word_ids = []
            for token in group:
                word_id = f"w_{len(words) + 1:06d}"
                duration = max(120_000, len(token) * 100_000)
                word_ids.append(word_id)
                words.append(
                    {
                        "word_id": word_id,
                        "word_text": token,
                        "source_start_us": cursor,
                        "source_end_us": cursor + duration,
                        "source_material_id": "main",
                        "source_segment_id": "clip",
                        "subtitle_uid": f"s_{subtitle_index:03d}",
                        "subtitle_index": subtitle_index,
                    }
                )
                cursor += duration
            subtitles.append(
                {
                    "subtitle_uid": f"s_{subtitle_index:03d}",
                    "subtitle_index": subtitle_index,
                    "text": "".join(group),
                    "word_ids": word_ids,
                    "text_material_id": "template_text",
                }
            )

        report = ArollEngine().run(
            ArollRunInput(
                source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": cursor + 1_000_000}],
                word_timeline=words,
                subtitles=subtitles,
                text_materials=materials,
                text_segments=text_segments,
                postwrite_mode="simulated",
            )
        )

        codes = [blocker.code for blocker in report.blocker_report.blockers]
        self.assertEqual(report.status, "ok", codes)
        self.assertNotIn("FINAL_REPEAT_VALIDATOR_FAILED", codes)
        self.assertNotIn("HIDDEN_AUDIO_REPEAT_VALIDATOR_FAILED", codes)
        self.assertEqual([caption.text for caption in report.captions], ["在舞台", "中央大声说话的自己", "过渡内容", "把输掉的"])
        self.assertTrue(report.validator_report["final_repeat_validator"]["final_repeat_gate_passed"])
        self.assertTrue(report.validator_report["hidden_audio_repeat_validator"]["hidden_audio_repeat_gate_passed"])
        rough = report.validator_report["rough_cut_quality_validator"]
        self.assertEqual(rough["segments_lt_300ms"], 0)
        self.assertEqual(rough["one_char_captions"], 0)
        self.assertLessEqual(len(report.final_timeline), len(report.captions))
        self.assertTrue(rough["caption_count_covers_video_segments"])
        self.assertEqual(len(report.captions), len(report.material_write_plan["materials"]))
        self.assertEqual(len(report.captions), len(report.material_write_plan["segments"]))


if __name__ == "__main__":
    unittest.main()
