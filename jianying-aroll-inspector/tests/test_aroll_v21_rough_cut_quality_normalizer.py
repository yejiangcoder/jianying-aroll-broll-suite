from __future__ import annotations

import unittest

from aroll_v21.compiler import RoughCutQualityNormalizer
from aroll_v21.ir.models import (
    CanonicalSourceGraph,
    CanonicalWord,
    DecisionPlan,
    FinalTimelineSegment,
    SourceGraphInvariantReport,
)


def make_word(word_id: str, text: str, start_us: int, end_us: int, subtitle_uid: str, subtitle_index: int) -> CanonicalWord:
    return CanonicalWord(
        word_id=word_id,
        text=text,
        normalized_text=text,
        source_start_us=start_us,
        source_end_us=end_us,
        source_material_id="main_video_a",
        source_segment_id="clip_001",
        subtitle_uid=subtitle_uid,
        subtitle_index=subtitle_index,
        char_start=None,
        char_end=None,
        confidence=None,
        is_cuttable_left=True,
        is_cuttable_right=True,
    )


def make_source_graph(words: list[CanonicalWord], source_end_us: int = 2_000_000) -> CanonicalSourceGraph:
    return CanonicalSourceGraph(
        words=words,
        edit_units=[],
        subtitle_rows=[],
        source_materials=[{"source_material_id": "main_video_a", "type": "video", "duration_us": source_end_us}],
        source_segments=[
            {
                "id": "clip_001",
                "material_id": "main_video_a",
                "source_timerange": {"start": 0, "duration": source_end_us},
                "target_timerange": {"start": 0, "duration": source_end_us},
            }
        ],
        text_materials=[],
        text_segments=[],
        invariant_report=SourceGraphInvariantReport(
            single_source_graph_ok=True,
            all_words_have_source_time=True,
            all_edit_units_have_word_ids=True,
            unbound_word_count=0,
            unbound_subtitle_count=0,
            blocker_count=0,
            blockers=[],
        ),
    )


def make_segment(segment_id: str, text: str, start_us: int, end_us: int, word_ids: list[str]) -> FinalTimelineSegment:
    return FinalTimelineSegment(
        segment_id=segment_id,
        source_material_id="main_video_a",
        source_segment_id="clip_001",
        source_start_us=start_us,
        source_end_us=end_us,
        target_start_us=start_us,
        target_end_us=end_us,
        word_ids=word_ids,
        text=text,
        decision_ids=[],
    )


class ArollV21RoughCutQualityNormalizerTests(unittest.TestCase):
    def test_micro_segments_merge_into_phrase_and_remove_one_char_fragments(self) -> None:
        words = [
            make_word("w1", "家", 0, 80_000, "s1", 1),
            make_word("w2", "豪", 80_000, 160_000, "s2", 2),
            make_word("w3", "回来", 160_000, 560_000, "s3", 3),
        ]
        segments = [
            make_segment("seg1", "家", 0, 80_000, ["w1"]),
            make_segment("seg2", "豪", 80_000, 160_000, ["w2"]),
            make_segment("seg3", "回来", 160_000, 560_000, ["w3"]),
        ]
        normalized, blockers = RoughCutQualityNormalizer().normalize(segments, make_source_graph(words), DecisionPlan(decisions=[]))

        self.assertEqual(blockers, [])
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0].text, "家豪回来")
        self.assertGreaterEqual(normalized[0].target_end_us - normalized[0].target_start_us, 560_000)

    def test_handles_expand_clip_source_range_without_crossing_bounds(self) -> None:
        words = [make_word("w1", "测试短句", 300_000, 600_000, "s1", 1)]
        segment = make_segment("seg1", "测试短句", 300_000, 600_000, ["w1"])

        normalized, blockers = RoughCutQualityNormalizer().normalize([segment], make_source_graph(words), DecisionPlan(decisions=[]))

        self.assertEqual(blockers, [])
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0].spoken_source_start_us, 300_000)
        self.assertEqual(normalized[0].spoken_source_end_us, 600_000)
        self.assertEqual(normalized[0].clip_source_start_us, 80_000)
        self.assertEqual(normalized[0].clip_source_end_us, 820_000)
        self.assertEqual(normalized[0].lead_handle_us, 220_000)
        self.assertEqual(normalized[0].tail_handle_us, 220_000)


if __name__ == "__main__":
    unittest.main()
