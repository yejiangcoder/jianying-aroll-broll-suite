from __future__ import annotations

import unittest

from aroll_v21.compiler.final_timeline_compiler import FinalTimelineCompiler
from aroll_v21.compiler.rough_cut_quality_normalizer import RoughCutQualityNormalizer
from aroll_v21.ingest.real_draft_adapter import RealDraftIngestAdapter
from aroll_v21.ingest.word_timeline_provider import DefaultWordTimelineProvider
from aroll_v21.ir.models import (
    CanonicalSourceGraph,
    CanonicalWord,
    DecisionPlan,
    EditUnit,
    FinalTimelineSegment,
    SourceGraphInvariantReport,
)


BOUNDARY_US = 143_566_666


def _fresh_0617_like_draft() -> dict:
    return {
        "materials": {
            "texts": [
                {
                    "id": "text_before",
                    "type": "subtitle",
                    "recognize_text": "前段字幕",
                    "words": {"start_time": [0, 600], "end_time": [600, 1200], "text": ["前段", "字幕"]},
                },
                {
                    "id": "text_after",
                    "type": "recognize_text",
                    "recognize_text": "后段字幕",
                    "words": {"start_time": [0, 500], "end_time": [500, 1000], "text": ["后段", "字幕"]},
                },
            ],
            "videos": [
                {"id": "video_1", "type": "video", "path": "C:/redacted/1-1.mp4", "duration": 172_280_000},
                {
                    "id": "video_2",
                    "type": "video",
                    "path": "C:/redacted/2-1.mp4",
                    "duration": 136_520_000,
                    "beauty_face_preset_infos": [{"name": "smooth"}],
                    "beauty_body_preset_id": "body_preset",
                },
            ],
            "speeds": [
                {"id": "speed_1", "speed": 1.2},
                {"id": "speed_2", "speed": 1.2},
            ],
            "effects": [{"id": "effect_1", "type": "figure", "sub_type": "auto_beauty"}],
            "realtime_denoises": [{"id": "denoise_1"}],
        },
        "tracks": [
            {
                "id": "video_track",
                "type": "video",
                "segments": [
                    {
                        "id": "video_seg_1",
                        "material_id": "video_1",
                        "speed": 1.2,
                        "extra_material_refs": ["speed_1", "effect_1"],
                        "source_timerange": {"start": 0, "duration": 172_280_000},
                        "target_timerange": {"start": 0, "duration": BOUNDARY_US},
                    },
                    {
                        "id": "video_seg_2",
                        "material_id": "video_2",
                        "speed": 1.2,
                        "extra_material_refs": [{"id": "speed_2"}, {"id": "effect_1"}],
                        "source_timerange": {"start": 0, "duration": 136_520_000},
                        "target_timerange": {"start": BOUNDARY_US, "duration": 113_766_667},
                    },
                ],
            },
            {
                "id": "text_track",
                "type": "text",
                "segments": [
                    {
                        "id": "subtitle_before",
                        "material_id": "text_before",
                        "target_timerange": {"start": 141_000_000, "duration": 2_000_000},
                    },
                    {
                        "id": "subtitle_after",
                        "material_id": "text_after",
                        "target_timerange": {"start": BOUNDARY_US + 1_700_000, "duration": 2_000_000},
                    },
                ],
            },
        ],
    }


def _ingest_words_from_fixture() -> tuple[list[dict], list[dict], dict]:
    adapter = RealDraftIngestAdapter()
    draft = _fresh_0617_like_draft()
    materials = draft["materials"]
    tracks = draft["tracks"]
    text_materials = [dict(row) for row in materials["texts"]]
    text_segments = adapter._text_segments(tracks)
    source_segments = adapter._source_segments(tracks)
    subtitles = adapter._subtitle_rows(text_segments, text_materials)
    provider = DefaultWordTimelineProvider()
    word_result = provider.load(
        draft_data=draft,
        text_materials=text_materials,
        text_segments=text_segments,
        source_segments=source_segments,
    )
    words, blockers, metadata = adapter._bind_word_rows(word_result.words, subtitles, source_segments)
    assert not blockers, [blocker.code for blocker in blockers]
    metadata["provider_metadata"] = word_result.metadata
    return words, source_segments, metadata


class ArollV21Fresh0617SchemaRegressionTests(unittest.TestCase):
    def test_native_words_dict_of_arrays_from_real_jianying_schema(self) -> None:
        words, _source_segments, metadata = _ingest_words_from_fixture()

        self.assertEqual(len(words), 4)
        self.assertEqual(metadata["provider_metadata"]["selected_provider"], "draft_native_word")
        self.assertEqual(metadata["provider_metadata"]["speech_timeline_granularity"], "word")
        self.assertEqual(metadata["provider_metadata"]["draft_native"]["scanned_text_material_count"], 2)

    def test_native_word_time_mapping_uses_text_segment_target_coordinate(self) -> None:
        words, _source_segments, metadata = _ingest_words_from_fixture()
        first_after = next(row for row in words if row["text_material_id"] == "text_after")

        self.assertGreater(first_after["source_start_us"], BOUNDARY_US)
        self.assertEqual(first_after["source_start_us"], BOUNDARY_US + 1_700_000)
        self.assertEqual(metadata["native_word_time_basis"]["relative_to_text_segment_count"], 4)

    def test_native_word_time_mapping_two_video_segments_source_resets_but_canonical_monotonic(self) -> None:
        words, _source_segments, metadata = _ingest_words_from_fixture()
        source_starts = [row["source_start_us"] for row in words]

        self.assertEqual(source_starts, sorted(source_starts))
        self.assertTrue(metadata["source_time_monotonic_by_subtitle"])
        self.assertGreater(source_starts[-1], BOUNDARY_US)

    def test_native_word_mapping_does_not_rebind_second_segment_words_to_first_segment(self) -> None:
        words, _source_segments, _metadata = _ingest_words_from_fixture()
        after_words = [row for row in words if row["text_material_id"] == "text_after"]

        self.assertTrue(after_words)
        self.assertTrue(all(row["debug_hints"]["current_video_segment_id"] == "video_seg_2" for row in after_words))
        self.assertTrue(all(row["debug_hints"]["current_video_window_index"] == 2 for row in after_words))

    def test_native_word_mapping_sets_canonical_source_segment_id_none(self) -> None:
        words, _source_segments, _metadata = _ingest_words_from_fixture()

        self.assertTrue(all(row.get("source_segment_id") is None for row in words))
        self.assertTrue(all(row.get("source_material_id") == "" for row in words))
        self.assertTrue(all("current_video_segment_id" in row["debug_hints"] for row in words))

    def test_source_windows_use_primary_video_target_ranges_as_canonical_source_ranges(self) -> None:
        _words, source_segments, _metadata = _ingest_words_from_fixture()

        self.assertEqual(source_segments[0]["source_start_us"], 0)
        self.assertEqual(source_segments[0]["source_end_us"], BOUNDARY_US)
        self.assertEqual(source_segments[1]["source_start_us"], BOUNDARY_US)
        self.assertEqual(source_segments[1]["material_local_source_start_us"], 0)


def _source_graph_for_windows() -> CanonicalSourceGraph:
    words = [
        CanonicalWord("w1", "甲甲甲", "甲甲甲", 500_000, 900_000, "", None, "s1", 1, None, None, None, True, True),
        CanonicalWord("w2", "乙乙乙", "乙乙乙", 1_000_000, 1_400_000, "", None, "s1", 1, None, None, None, True, True),
    ]
    return CanonicalSourceGraph(
        words=words,
        edit_units=[
            EditUnit(
                "u1",
                ["w1", "w2"],
                "甲乙",
                "甲乙",
                500_000,
                1_400_000,
                ["s1"],
                [],
                "sentence",
                "word_boundary",
            )
        ],
        subtitle_rows=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": "甲乙", "word_ids": ["w1", "w2"]}],
        source_materials=[],
        source_segments=[
            {
                "id": "video_seg_1",
                "track_type": "video",
                "canonical_source_start_us": 0,
                "canonical_source_end_us": 1_000_000,
            },
            {
                "id": "video_seg_2",
                "track_type": "video",
                "canonical_source_start_us": 1_000_000,
                "canonical_source_end_us": 2_000_000,
            },
        ],
        text_materials=[],
        text_segments=[],
        invariant_report=SourceGraphInvariantReport(True, True, True, 0, 0, 0, []),
    )


class ArollV21SourceWindowContractTests(unittest.TestCase):
    def test_rough_cut_handles_clamped_to_primary_source_window(self) -> None:
        source_graph = _source_graph_for_windows()
        segment = FinalTimelineSegment("seg", "", None, 900_000, 950_000, 0, 50_000, ["w1"], "甲", [])

        handled, blockers = RoughCutQualityNormalizer().normalize(
            [segment],
            source_graph,
            DecisionPlan(decisions=[]),
            emit_residual_blockers=False,
        )

        self.assertFalse(blockers)
        self.assertLessEqual(handled[0].clip_source_end_us, 1_000_000)

    def test_final_segment_crossing_primary_source_window_splits_when_word_level_available(self) -> None:
        segments, blockers = FinalTimelineCompiler().compile(_source_graph_for_windows(), DecisionPlan(decisions=[]))

        self.assertFalse([blocker.code for blocker in blockers])
        self.assertEqual(len(segments), 2)
        self.assertTrue(all(segment.source_segment_id is None for segment in segments))

    def test_final_segment_crossing_primary_source_window_blocks_when_phrase_level_only(self) -> None:
        graph = _source_graph_for_windows()
        phrase_word = CanonicalWord("p1", "整句", "整句", 900_000, 1_050_000, "", None, "s1", 1, None, None, None, True, True)
        graph = CanonicalSourceGraph(
            words=[phrase_word],
            edit_units=[
                EditUnit(
                    "u1",
                    ["p1"],
                    "整句",
                    "整句",
                    900_000,
                    1_050_000,
                    ["s1"],
                    [],
                    "sentence",
                    "whole_unit_only",
                )
            ],
            subtitle_rows=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": "整句", "word_ids": ["p1"]}],
            source_materials=[],
            source_segments=graph.source_segments,
            text_materials=[],
            text_segments=[],
            invariant_report=SourceGraphInvariantReport(True, True, True, 0, 0, 0, []),
        )

        _segments, blockers = FinalTimelineCompiler().compile(graph, DecisionPlan(decisions=[]))

        self.assertIn("V21_FINAL_SEGMENT_CROSSES_PRIMARY_SOURCE_WINDOW", [blocker.code for blocker in blockers])


if __name__ == "__main__":
    unittest.main()
