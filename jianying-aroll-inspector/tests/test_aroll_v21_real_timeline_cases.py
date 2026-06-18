from __future__ import annotations

import json
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput
from aroll_v21.ir import dataclass_to_dict


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: str):
    return json.loads((ROOT / path).read_text("utf-8"))


def material_rows():
    payload = load_json("fixtures/real_materials/normal_caption_template.json")
    return [payload["material"]], [payload["segment"]]


def run_timeline(name: str):
    payload = load_json(f"fixtures/real_timelines/{name}.json")
    text_materials, text_segments = material_rows()
    return ArollEngine().run(
        ArollRunInput(
            source_segments=payload["source_segments"],
            word_timeline=payload["word_timeline"],
            subtitles=payload["subtitles"],
            text_materials=text_materials,
            text_segments=text_segments,
        )
    )


class ArollV21RealTimelineCaseTests(unittest.TestCase):
    def test_subtitle_clean_but_audio_words_repeat_is_split_not_silent(self) -> None:
        report = run_timeline("subtitle_audio_mismatch")
        self.assertEqual(report.status, "ok", dataclass_to_dict(report.blocker_report))
        self.assertTrue(report.repeat_clusters)
        self.assertTrue(report.decision_plan.split_decisions)
        self.assertEqual("".join(caption.text for caption in report.captions), "你们是在集体做空呐")
        self.assertTrue(report.validator_report["hidden_audio_repeat_validator"]["hidden_audio_repeat_gate_passed"])

    def test_cjk_short_overlap_uses_unit_decision_and_passes_validators(self) -> None:
        report = run_timeline("cjk_short_overlap")
        self.assertEqual(report.status, "ok", dataclass_to_dict(report.blocker_report))
        self.assertEqual("".join(caption.text for caption in report.captions), "最后只能像一个小丑")
        self.assertEqual(report.validator_report["safe_cut_validator"]["partial_multichar_cut_count"], 0)

    def test_restart_disfluency_drops_restart_stub_at_unit_boundary(self) -> None:
        report = run_timeline("restart")
        self.assertEqual(report.status, "ok", dataclass_to_dict(report.blocker_report))
        self.assertEqual("".join(caption.text for caption in report.captions), "我发现")

    def test_multi_char_word_alignment_has_no_partial_multichar_cut(self) -> None:
        report = run_timeline("multi_char_word_alignment")
        self.assertEqual(report.status, "ok", dataclass_to_dict(report.blocker_report))
        self.assertEqual(report.validator_report["safe_cut_validator"]["partial_multichar_cut_count"], 0)

    def test_unsafe_cut_policy_blocks_instead_of_partial_cut(self) -> None:
        payload = load_json("fixtures/real_timelines/cjk_short_overlap.json")
        payload["subtitles"][0]["cut_policy"] = "unsafe"
        text_materials, text_segments = material_rows()
        report = ArollEngine().run(
            ArollRunInput(
                source_segments=payload["source_segments"],
                word_timeline=payload["word_timeline"],
                subtitles=payload["subtitles"],
                text_materials=text_materials,
                text_segments=text_segments,
            )
        )
        self.assertEqual(report.status, "blocked")
        self.assertIn("UNSAFE_EDIT_UNIT_DROP_BLOCKED", [blocker.code for blocker in report.blocker_report.blockers])


if __name__ == "__main__":
    unittest.main()
