from __future__ import annotations

import unittest

from aroll_v21.compiler import FinalTimelineCompiler, RoughCutQualityNormalizer
from aroll_v21.ingest import DraftIngest
from aroll_v21.ir import CaptionRenderUnit, DecisionPlan, UnitSplitPlan
from aroll_v21.render import SubtitleRenderer
from aroll_v21.validate.rough_cut_quality import build_rough_cut_quality_metrics
from tests.test_aroll_v21_rough_cut_quality_normalizer import make_segment, make_source_graph, make_word


def _captions_from_segments(segments):
    return [
        CaptionRenderUnit(
            caption_id=f"cap_{index:06d}",
            timeline_segment_ids=[segment.segment_id],
            word_ids=segment.word_ids,
            text=segment.text,
            target_start_us=segment.target_start_us,
            target_end_us=segment.target_end_us,
            source_subtitle_uids=[f"s{index}"],
            style_template_id="tmpl",
        )
        for index, segment in enumerate(segments, start=1)
    ]


class ArollV21FinalRoughCutQualityContractTests(unittest.TestCase):
    def test_micro_one_char_prefix_and_post_semantic_convergence_produce_clean_timeline_with_handles(self) -> None:
        words = [
            make_word("w1", "A", 0, 80_000, "s1", 1),
            make_word("w2", "B", 100_000, 180_000, "s2", 2),
            make_word("w3", "CDEF", 180_000, 780_000, "s3", 3),
        ]
        segments = [
            make_segment("seg1", "A", 0, 80_000, ["w1"]),
            make_segment("seg2", "B", 100_000, 180_000, ["w2"]),
            make_segment("seg3", "CDEF", 180_000, 780_000, ["w3"]),
        ]

        normalized, blockers = RoughCutQualityNormalizer().normalize(segments, make_source_graph(words), DecisionPlan(decisions=[]))

        self.assertEqual(blockers, [])
        self.assertEqual([segment.text for segment in normalized], ["ABCDEF"])
        self.assertEqual(normalized[0].target_start_us, 0)
        self.assertGreater(normalized[0].target_end_us, normalized[0].target_start_us)
        self.assertIsNotNone(normalized[0].spoken_source_start_us)
        self.assertIsNotNone(normalized[0].spoken_source_end_us)
        self.assertIsNotNone(normalized[0].clip_source_start_us)
        self.assertIsNotNone(normalized[0].clip_source_end_us)
        self.assertGreaterEqual(int(normalized[0].lead_handle_us or 0), 0)
        self.assertGreaterEqual(int(normalized[0].tail_handle_us or 0), 0)

    def test_residual_prefix_drop_and_adjacent_duplicate_cleanup_leave_no_gap_overlap_or_negative_duration(self) -> None:
        graph = DraftIngest().build_source_graph(
            word_timeline=[
                {"word_id": "w1", "word_text": "A", "source_start_us": 0, "source_end_us": 280_000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s1", "subtitle_index": 1},
                {"word_id": "w2", "word_text": "Axxx", "source_start_us": 2_100_000, "source_end_us": 2_700_000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s2", "subtitle_index": 2},
                {"word_id": "w3", "word_text": "Axxx", "source_start_us": 2_740_000, "source_end_us": 3_340_000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s3", "subtitle_index": 3},
            ],
            subtitles=[
                {"subtitle_uid": "s1", "subtitle_index": 1, "text": "A", "word_ids": ["w1"]},
                {"subtitle_uid": "s2", "subtitle_index": 2, "text": "Axxx", "word_ids": ["w2"]},
                {"subtitle_uid": "s3", "subtitle_index": 3, "text": "Axxx", "word_ids": ["w3"]},
            ],
            source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 4_000_000}],
        )
        final_timeline, blockers = FinalTimelineCompiler().compile(graph, DecisionPlan(decisions=[]))
        captions = SubtitleRenderer().render(final_timeline, graph)
        metrics = build_rough_cut_quality_metrics(
            final_timeline=final_timeline,
            captions=captions,
            material_write_plan={"materials": [{} for _ in captions], "segments": [{} for _ in captions]},
        )

        self.assertEqual(blockers, [])
        self.assertEqual([segment.text for segment in final_timeline], ["Axxx"])
        self.assertEqual(metrics["segments_lt_300ms"], 0)
        self.assertEqual(metrics["one_char_captions"], 0)
        self.assertEqual(metrics["target_gap_count"], 0)
        self.assertEqual(metrics["target_overlap_count"], 0)
        self.assertTrue(all(segment.target_end_us > segment.target_start_us for segment in final_timeline))

    def test_post_semantic_split_one_char_merges_before_validator_metrics(self) -> None:
        graph = DraftIngest().build_source_graph(
            word_timeline=[
                {"word_id": "w_drop", "word_text": "drop", "source_start_us": 0, "source_end_us": 320_000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s1", "subtitle_index": 1},
                {"word_id": "w_keep", "word_text": "A", "source_start_us": 340_000, "source_end_us": 420_000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s1", "subtitle_index": 1},
                {"word_id": "w_next", "word_text": "BCDE", "source_start_us": 440_000, "source_end_us": 940_000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s2", "subtitle_index": 2},
            ],
            subtitles=[
                {"subtitle_uid": "s1", "subtitle_index": 1, "text": "dropA", "word_ids": ["w_drop", "w_keep"]},
                {"subtitle_uid": "s2", "subtitle_index": 2, "text": "BCDE", "word_ids": ["w_next"]},
            ],
            source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 2_000_000}],
        )
        plan = DecisionPlan(
            decisions=[],
            split_decisions=[
                UnitSplitPlan(
                    split_id="split_keep_one_char",
                    cluster_id="repeat_002000",
                    unit_id="s1",
                    drop_word_ids=["w_drop"],
                    keep_word_ids=["w_keep"],
                    reason="test split",
                )
            ],
        )

        final_timeline, blockers = FinalTimelineCompiler().compile(graph, plan)
        captions = SubtitleRenderer().render(final_timeline, graph)
        metrics = build_rough_cut_quality_metrics(
            final_timeline=final_timeline,
            captions=captions,
            material_write_plan={"materials": [{} for _ in captions], "segments": [{} for _ in captions]},
        )

        self.assertEqual(blockers, [])
        self.assertEqual([segment.text for segment in final_timeline], ["ABCDE"])
        self.assertEqual(metrics["segments_lt_300ms"], 0)
        self.assertEqual(metrics["one_char_captions"], 0)

    def test_missing_handles_are_metrics_but_sub300_and_one_char_remain_hard_gate(self) -> None:
        good_without_handles = [make_segment("seg1", "ABCD", 0, 400_000, ["w1"])]
        good_metrics = build_rough_cut_quality_metrics(
            final_timeline=good_without_handles,
            captions=_captions_from_segments(good_without_handles),
            material_write_plan={"materials": [{}], "segments": [{}]},
        )
        bad = [make_segment("seg1", "A", 0, 280_000, ["w1"])]
        bad_metrics = build_rough_cut_quality_metrics(
            final_timeline=bad,
            captions=_captions_from_segments(bad),
            material_write_plan={"materials": [{}], "segments": [{}]},
        )

        self.assertGreater(good_metrics["segments_with_no_lead_handle"], 0)
        self.assertGreater(good_metrics["segments_with_no_tail_handle"], 0)
        self.assertTrue(good_metrics["rough_cut_quality_gate_passed"])
        self.assertEqual(bad_metrics["segments_lt_300ms"], 1)
        self.assertEqual(bad_metrics["one_char_captions"], 1)
        self.assertFalse(bad_metrics["rough_cut_quality_gate_passed"])


if __name__ == "__main__":
    unittest.main()
