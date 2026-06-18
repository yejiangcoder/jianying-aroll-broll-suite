from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput
from aroll_v21.operator import ArollV21OperatorConfig, run_operator

from tests.test_aroll_v21_compiler import base_material_rows


def _run(words: list[dict], segments: list[dict]):
    text_materials, text_segments = base_material_rows()
    subtitles = [
        {"subtitle_uid": word["subtitle_uid"], "subtitle_index": idx, "text": word["word_text"], "word_ids": [word["word_id"]]}
        for idx, word in enumerate(words, start=1)
    ]
    return ArollEngine().run(
        ArollRunInput(
            source_segments=segments,
            word_timeline=words,
            subtitles=subtitles,
            text_materials=text_materials,
            text_segments=text_segments,
        )
    )


class ArollV21FinalTimelineSourceSegmentBoundaryTests(unittest.TestCase):
    def test_legacy_different_source_segment_does_not_force_logical_split(self) -> None:
        segments = [
            {"id": "clip_a", "material_id": "main", "source_start_us": 0, "source_end_us": 800000},
            {"id": "clip_b", "material_id": "main", "source_start_us": 800000, "source_end_us": 1600000},
        ]
        words = [
            {"word_id": "w1", "word_text": "甲句", "start_us": 100000, "end_us": 450000, "source_material_id": "main", "source_segment_id": "clip_a", "subtitle_uid": "s1"},
            {"word_id": "w2", "word_text": "乙句", "start_us": 920000, "end_us": 1280000, "source_material_id": "main", "source_segment_id": "clip_b", "subtitle_uid": "s2"},
        ]
        report = _run(words, segments)
        self.assertEqual(report.status, "ok")
        self.assertEqual(len(report.final_timeline), 1)
        self.assertIsNone(report.final_timeline[0].source_segment_id)

    def test_same_source_segment_same_subtitle_and_small_gap_can_merge(self) -> None:
        segments = [{"id": "clip_a", "material_id": "main", "source_start_us": 0, "source_end_us": 1000000}]
        words = [
            {"word_id": "w1", "word_text": "甲句", "start_us": 100000, "end_us": 450000, "source_material_id": "main", "source_segment_id": "clip_a", "subtitle_uid": "s1", "subtitle_index": 1},
            {"word_id": "w2", "word_text": "乙句", "start_us": 470000, "end_us": 880000, "source_material_id": "main", "source_segment_id": "clip_a", "subtitle_uid": "s1", "subtitle_index": 1},
        ]
        text_materials, text_segments = base_material_rows()
        report = ArollEngine().run(
            ArollRunInput(
                source_segments=segments,
                word_timeline=words,
                subtitles=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": "甲句乙句", "word_ids": ["w1", "w2"]}],
                text_materials=text_materials,
                text_segments=text_segments,
            )
        )
        self.assertEqual(report.status, "ok")
        self.assertEqual(len(report.final_timeline), 1)

    def test_legacy_different_source_material_does_not_force_logical_split(self) -> None:
        segments = [
            {"id": "clip_a", "material_id": "main_a", "source_start_us": 0, "source_end_us": 800000},
            {"id": "clip_b", "material_id": "main_b", "source_start_us": 800000, "source_end_us": 1600000},
        ]
        words = [
            {"word_id": "w1", "word_text": "甲句", "start_us": 100000, "end_us": 450000, "source_material_id": "main_a", "source_segment_id": "clip_a", "subtitle_uid": "s1"},
            {"word_id": "w2", "word_text": "乙句", "start_us": 920000, "end_us": 1280000, "source_material_id": "main_b", "source_segment_id": "clip_b", "subtitle_uid": "s2"},
        ]
        report = _run(words, segments)
        self.assertEqual(report.status, "ok")
        self.assertEqual(len(report.final_timeline), 1)

    def test_final_edl_artifact_keeps_source_segment_field_as_debug_compatibility(self) -> None:
        segments = [{"id": "clip_a", "material_id": "main", "source_start_us": 0, "source_end_us": 1000000}]
        words = [
            {"word_id": "w1", "word_text": "甲句", "start_us": 100000, "end_us": 450000, "source_material_id": "main", "source_segment_id": "clip_a", "subtitle_uid": "s1"}
        ]
        text_materials, text_segments = base_material_rows()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_json = root / "input.json"
            input_json.write_text(
                json.dumps(
                    {
                        "source_segments": segments,
                        "word_timeline": words,
                        "subtitles": [{"subtitle_uid": "s1", "subtitle_index": 1, "text": "甲句", "word_ids": ["w1"]}],
                        "text_materials": text_materials,
                        "text_segments": text_segments,
                    },
                    ensure_ascii=False,
                ),
                "utf-8",
            )
            run_dir = root / "run"
            summary = run_operator(ArollV21OperatorConfig(mode="dry-run", run_dir=run_dir, input_json=input_json))
            self.assertEqual(summary["status"], "ok")
            final_timeline = json.loads((run_dir / "final_timeline.json").read_text("utf-8"))
            final_edl = json.loads((run_dir / "final_edl.json").read_text("utf-8"))
            self.assertEqual(final_edl[0]["source_segment_id"], final_timeline[0]["source_segment_id"])
            self.assertIsNone(final_edl[0]["source_segment_id"])


if __name__ == "__main__":
    unittest.main()
