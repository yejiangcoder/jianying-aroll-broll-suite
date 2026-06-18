from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from aroll_v21 import ArollEngine, ArollRunInput
from aroll_v21.engine import build_run_summary
from aroll_v21.operator import ArollV21OperatorConfig, run_operator
from aroll_v21.ir import BlockerReport, CaptionRenderUnit, FinalTimelineSegment, RunReport
from aroll_v21.ingest.real_draft_adapter import RealDraftIngestResult
from aroll_v21.quality.caption_alignment import build_caption_alignment_report
from aroll_v21.quality.final_caption_visible_repeat import build_final_caption_visible_repeat_gate
from aroll_v21.quality.final_repeat_convergence import build_final_repeat_convergence_report
from aroll_v21.quality.quality_gate import build_quality_gate_report
from aroll_v21.quality.visual_pacing import VisualPacingNormalizer, build_visual_pacing_report
from aroll_v21.render.subtitle_renderer import SubtitleRenderer, _cleanup_caption_units
from aroll_v21.writeback import real_draft_writeback as real_writeback_module
from aroll_v21.writeback.dynamic_source_binding_preflight import DynamicSourceBindingPreflight
from aroll_v21.writeback.real_draft_writeback import RealDraftWriteback
from tests.test_aroll_v21_captions_after_prefix_drop import _template_rows
from tests.test_aroll_v21_real_writeback_backend import run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import (
    FakeAdapter,
    create_disposable_draft,
    fake_encrypt,
    fake_integrity_ok,
    fake_real_draft_result,
    fake_root_mirror_not_required,
)


def _segment(index: int, start: int, end: int) -> FinalTimelineSegment:
    return FinalTimelineSegment(
        segment_id=f"v21_seg_{index:06d}",
        source_material_id="",
        source_segment_id=None,
        source_start_us=start,
        source_end_us=end,
        target_start_us=start,
        target_end_us=end,
        word_ids=[f"w{index}"],
        text=f"字幕{index}",
        decision_ids=[],
    )


def _caption(index: int, segment_id: str, start: int, end: int, text: str = "字幕") -> CaptionRenderUnit:
    return CaptionRenderUnit(
        caption_id=f"v21_cap_{index:06d}",
        timeline_segment_ids=[segment_id],
        word_ids=[f"w{index}"],
        text=text,
        target_start_us=start,
        target_end_us=end,
        source_subtitle_uids=[f"s{index}"],
        style_template_id="canonical_caption_template",
    )


def _semantic_gate_ok() -> dict[str, object]:
    return {
        "semantic_adjudication_gate_passed": True,
        "semantic_request_count": 0,
        "semantic_request_unresolved_count": 0,
        "fatal_semantic_issue_count": 0,
        "blocker_codes": [],
    }


def _multi_caption_fake_result(*, root: Path | None = None) -> RealDraftIngestResult:
    result = fake_real_draft_result(root=root)
    draft_data = deepcopy(result.draft_data)
    source_segment = deepcopy(result.source_segments[0])
    source_segment.update(
        {
            "source_timerange": {"start": 0, "duration": 1_800_000},
            "target_timerange": {"start": 0, "duration": 1_800_000},
            "source_start_us": 0,
            "source_end_us": 1_800_000,
            "target_start_us": 0,
            "target_end_us": 1_800_000,
        }
    )
    draft_data["duration"] = 1_800_000
    draft_data["tracks"][0]["segments"][0] = source_segment
    draft_data["materials"]["videos"][0]["duration"] = 1_800_000
    return RealDraftIngestResult(
        draft_data=draft_data,
        source_segments=[source_segment],
        source_materials=[{"source_material_id": "main_video_a", "type": "video", "duration_us": 1_800_000}],
        word_timeline=[
            {"word_id": "w001", "word_text": "这个问题需要确认", "start_us": 0, "end_us": 500_000, "subtitle_index": 1, "subtitle_uid": "s001"},
            {"word_id": "w002", "word_text": "那个答案继续保留", "start_us": 600_000, "end_us": 1_100_000, "subtitle_index": 1, "subtitle_uid": "s001"},
            {"word_id": "w003", "word_text": "然后继续推进测试", "start_us": 1_200_000, "end_us": 1_700_000, "subtitle_index": 1, "subtitle_uid": "s001"},
        ],
        subtitles=[
            {
                "subtitle_uid": "s001",
                "subtitle_index": 1,
                "text": "这个问题需要确认那个答案继续保留然后继续推进测试",
                "word_ids": ["w001", "w002", "w003"],
            },
        ],
        text_materials=deepcopy(result.text_materials),
        text_segments=deepcopy(result.text_segments),
        metadata=deepcopy(result.metadata),
    )


def _graph_for_visual_merge_rows(rows: list[tuple[str, str, int, int]]) :
    materials, text_segments = _template_rows()
    words = [
        {
            "word_id": word_id,
            "word_text": text,
            "start_us": start,
            "end_us": end,
            "subtitle_index": index,
            "subtitle_uid": f"s{index:03d}",
        }
        for index, (word_id, text, start, end) in enumerate(rows, start=1)
    ]
    return ArollEngine().ingest.build_source_graph(
        word_timeline=words,
        subtitles=[
            {
                "subtitle_uid": row["subtitle_uid"],
                "subtitle_index": row["subtitle_index"],
                "text": row["word_text"],
                "word_ids": [row["word_id"]],
            }
            for row in words
        ],
        source_segments=[
            {
                "id": "primary_window",
                "material_id": "main",
                "type": "video",
                "source_start_us": 0,
                "source_end_us": max(end for _word_id, _text, _start, end in rows) + 500_000,
            }
        ],
        text_materials=materials,
        text_segments=text_segments,
    )


def _audit_writeback(encrypt_func=fake_encrypt, decrypt_func=None) -> RealDraftWriteback:
    return RealDraftWriteback(
        jy_draftc=Path("jy-draftc.exe"),
        encrypt_func=encrypt_func,
        decrypt_func=decrypt_func,
        root_mirror_func=fake_root_mirror_not_required,
        timeline_content_check_func=fake_integrity_ok,
        layout_check_func=fake_integrity_ok,
        project_folder_check_func=fake_integrity_ok,
    )


def _append_actual_text_segment(
    data: dict,
    *,
    segment_id: str,
    material_id: str,
    text: str,
    start_us: int,
    duration_us: int,
    track_id: str = "text_track",
    role: str | None = None,
) -> None:
    material = {"id": material_id, "type": "text", "text": text}
    if role is not None:
        material["role"] = role
    data.setdefault("materials", {}).setdefault("texts", []).append(material)
    track = next(track for track in data["tracks"] if track["id"] == track_id)
    track.setdefault("segments", []).append(
        {
            "id": segment_id,
            "type": "text",
            "material_id": material_id,
            "target_timerange": {"start": start_us, "duration": duration_us},
        }
    )


def _caption_trim_report(result: RealDraftIngestResult):
    report = run_report_from_result(result)
    first_word = report.source_graph.words[0]
    dropped_word = replace(
        first_word,
        word_id="w_drop",
        text="删掉",
        normalized_text="删掉",
        source_start_us=100_000,
        source_end_us=400_000,
    )
    kept_word = replace(
        first_word,
        word_id="w_keep",
        text="保留",
        normalized_text="保留",
        source_start_us=500_000,
        source_end_us=800_000,
    )
    final_segment = replace(
        report.final_timeline[0],
        source_start_us=100_000,
        source_end_us=800_000,
        target_start_us=0,
        target_end_us=700_000,
        word_ids=["w_drop", "w_keep"],
        text="删掉保留",
        spoken_source_start_us=None,
        spoken_source_end_us=None,
        clip_source_start_us=None,
        clip_source_end_us=None,
        lead_handle_us=0,
        tail_handle_us=0,
    )
    caption = replace(
        report.captions[0],
        word_ids=["w_keep"],
        text="保留",
        target_start_us=300_000,
        target_end_us=600_000,
        spoken_source_start_us=500_000,
        spoken_source_end_us=800_000,
        containing_video_segment_id=final_segment.segment_id,
        timeline_segment_ids=[final_segment.segment_id],
    )
    material_write_plan = deepcopy(report.material_write_plan)
    material_write_plan["segments"][0]["target_timerange"] = {"start": 300_000, "duration": 300_000}
    return replace(
        report,
        source_graph=replace(report.source_graph, words=[dropped_word, kept_word]),
        final_timeline=[final_segment],
        captions=[caption],
        material_write_plan=material_write_plan,
    )


def _dropped_reintroduced_report(result: RealDraftIngestResult):
    report = _caption_trim_report(result)
    final_segment = replace(
        report.final_timeline[0],
        source_start_us=500_000,
        source_end_us=800_000,
        target_start_us=300_000,
        target_end_us=600_000,
        word_ids=["w_keep"],
        text="保留",
    )
    return replace(report, final_timeline=[final_segment])


def _inside_dropped_report(result: RealDraftIngestResult):
    report = run_report_from_result(result)
    base_word = report.source_graph.words[0]
    before_word = replace(
        base_word,
        word_id="w_before",
        text="前",
        normalized_text="前",
        source_start_us=100_000,
        source_end_us=300_000,
    )
    dropped_word = replace(
        base_word,
        word_id="w_drop_inside",
        text="删掉",
        normalized_text="删掉",
        source_start_us=400_000,
        source_end_us=500_000,
    )
    after_word = replace(
        base_word,
        word_id="w_after",
        text="后",
        normalized_text="后",
        source_start_us=600_000,
        source_end_us=800_000,
    )
    final_segment = replace(
        report.final_timeline[0],
        source_start_us=100_000,
        source_end_us=800_000,
        target_start_us=0,
        target_end_us=700_000,
        word_ids=["w_before", "w_after"],
        text="前后",
        spoken_source_start_us=None,
        spoken_source_end_us=None,
        clip_source_start_us=None,
        clip_source_end_us=None,
        lead_handle_us=0,
        tail_handle_us=0,
    )
    caption = replace(
        report.captions[0],
        word_ids=["w_before", "w_after"],
        text="前后",
        target_start_us=0,
        target_end_us=700_000,
        spoken_source_start_us=100_000,
        spoken_source_end_us=800_000,
        containing_video_segment_id=final_segment.segment_id,
        timeline_segment_ids=[final_segment.segment_id],
    )
    material_write_plan = deepcopy(report.material_write_plan)
    material_write_plan["segments"][0]["target_timerange"] = {"start": 0, "duration": 700_000}
    return replace(
        report,
        source_graph=replace(report.source_graph, words=[before_word, dropped_word, after_word]),
        final_timeline=[final_segment],
        captions=[caption],
        material_write_plan=material_write_plan,
    )


class ArollV21QualityGateTests(unittest.TestCase):
    def test_final_repeat_convergence_reduces_high_count_to_zero(self) -> None:
        report = build_final_repeat_convergence_report(
            decision_trace=[
                {
                    "route": "final_target_repeat",
                    "cluster_id": "final_target_repeat_tc_0001",
                    "decision": "drop_recommended",
                    "drop_index": 1,
                    "convergence_iteration": 1,
                    "applied": True,
                }
            ],
            final_repeat_report={"final_target_repeat_high_count": 0, "final_target_repeat_candidates": []},
        )

        self.assertTrue(report["gate_passed"])
        self.assertEqual(report["final_repeat_high_count_after"], 0)
        self.assertEqual(report["dropped_cluster_ids"], ["final_target_repeat_tc_0001"])
        self.assertEqual(report["dropped_segment_indices"], [1])
        self.assertEqual(report["iterations"], 1)

    def test_final_repeat_convergence_report_deduplicates_dropped_clusters(self) -> None:
        report = build_final_repeat_convergence_report(
            decision_trace=[
                {
                    "route": "final_target_repeat",
                    "cluster_id": "final_target_repeat_tc_0011",
                    "decision": "drop_recommended",
                    "dropped_segment_indices": [4],
                    "convergence_iteration": 1,
                    "applied": True,
                },
                {
                    "route": "final_target_repeat",
                    "cluster_id": "final_target_repeat_tc_0011",
                    "decision": "drop_recommended",
                    "dropped_segment_indices": [4],
                    "convergence_iteration": 1,
                    "applied": True,
                },
                {
                    "route": "final_target_repeat",
                    "cluster_id": "final_target_repeat_tc_0012",
                    "decision": "auto_drop_high_confidence_exact_repeat",
                    "dropped_indices": [4],
                    "convergence_iteration": 2,
                    "applied": True,
                },
            ],
            final_repeat_report={"final_target_repeat_high_count": 0, "final_target_repeat_candidates": []},
        )

        self.assertEqual(report["dropped_cluster_ids"], ["final_target_repeat_tc_0011", "final_target_repeat_tc_0012"])
        self.assertEqual(report["dropped_cluster_count"], 2)
        self.assertEqual(report["dropped_segment_indices"], [4])
        self.assertEqual(report["dropped_segment_count"], 1)
        self.assertEqual(report["final_repeat_dropped_segment_count"], 1)
        self.assertEqual(report["clusters_per_dropped_segment"], {"4": ["final_target_repeat_tc_0011", "final_target_repeat_tc_0012"]})
        self.assertEqual(report["iterations"], 2)

    def test_unresolved_high_repeat_blocks_ready(self) -> None:
        report = build_final_repeat_convergence_report(
            decision_trace=[],
            final_repeat_report={
                "final_target_repeat_high_count": 1,
                "final_target_repeat_candidates": [
                    {
                        "cluster_id": "final_target_repeat_tc_0001",
                        "confidence": "high",
                        "v21_resolution": "fatal_unresolved_high",
                    }
                ],
            },
        )

        self.assertFalse(report["gate_passed"])
        self.assertIn("V21_FINAL_REPEAT_UNRESOLVED_AFTER_CONVERGENCE", report["blocker_codes"])

    def test_final_caption_visible_repeat_blocks_containment_repeat(self) -> None:
        gate = build_final_caption_visible_repeat_gate(
            [
                _caption(1, "v21_seg_000001", 0, 700_000, text="就国南"),
                _caption(2, "v21_seg_000002", 10_000_000, 11_000_000, text="就国南就只会内斗"),
            ]
        )

        self.assertFalse(gate["gate_passed"])
        self.assertEqual(gate["containment_repeat_count"], 1)
        self.assertIn("V21_FINAL_CAPTION_VISIBLE_REPEAT_GATE_FAILED", gate["blocker_codes"])

    def test_final_caption_visible_repeat_blocks_prefix_suffix_overlap(self) -> None:
        gate = build_final_caption_visible_repeat_gate(
            [
                _caption(1, "v21_seg_000001", 0, 900_000, text="你应该相信自己"),
                _caption(2, "v21_seg_000002", 900_000, 1_800_000, text="相信自己能做到"),
            ]
        )

        self.assertFalse(gate["gate_passed"])
        self.assertEqual(gate["prefix_suffix_overlap_count"], 1)
        self.assertEqual(gate["prefix_suffix_overlap_candidates"][0]["overlap_text"], "相信自己")

    def test_final_caption_visible_repeat_blocks_ngram_repeat(self) -> None:
        gate = build_final_caption_visible_repeat_gate(
            [
                _caption(1, "v21_seg_000001", 0, 900_000, text="我们重新开始吧"),
                _caption(2, "v21_seg_000002", 3_000_000, 3_900_000, text="大家都要重新开始"),
            ]
        )

        self.assertFalse(gate["gate_passed"])
        self.assertGreaterEqual(gate["ngram_repeat_count"], 1)

    def test_renderer_repairs_deterministic_visible_repeats_before_gate(self) -> None:
        source_graph = _graph_for_visual_merge_rows(
            [
                ("w001", "就国南", 0, 640_000),
                ("w002", "就国南就只会内斗", 700_000, 1_700_000),
            ]
        )
        segments = [
            replace(_segment(1, 0, 640_000), source_end_us=640_000, word_ids=["w001"], text="就国南"),
            replace(
                _segment(2, 700_000, 1_700_000),
                source_start_us=700_000,
                source_end_us=1_700_000,
                word_ids=["w002"],
                text="就国南就只会内斗",
            ),
        ]

        captions = SubtitleRenderer().render(segments, source_graph)
        gate = build_final_caption_visible_repeat_gate(captions)

        self.assertEqual(gate["visible_repeat_candidate_count"], 0)
        self.assertTrue(gate["gate_passed"])

    def test_final_caption_repeat_gate_does_not_depend_on_high_cluster_only(self) -> None:
        caption_gate = build_final_caption_visible_repeat_gate(
            [
                _caption(1, "v21_seg_000001", 0, 700_000, text="就是在"),
                _caption(2, "v21_seg_000002", 10_000_000, 11_000_000, text="她们就是在集体做多啊"),
            ]
        )
        quality = build_quality_gate_report(
            effective_speed_gate={"gate_passed": True, "blocker_codes": []},
            final_repeat_convergence_gate={
                "gate_passed": True,
                "blocker_codes": [],
                "final_repeat_high_count_after": 0,
                "detector_report_present": True,
            },
            final_caption_visible_repeat_gate=caption_gate,
            visual_pacing_gate={
                "gate_passed": True,
                "blocker_codes": [],
                "visual_pacing_executed": True,
                "visual_merge_safety_gate_passed": True,
            },
            caption_alignment_gate={"gate_passed": True, "blocker_codes": []},
            ready_for_user_manual_qc_preconditions_passed=True,
        )

        self.assertFalse(quality["gate_passed"])
        self.assertIn("V21_FINAL_CAPTION_VISIBLE_REPEAT_GATE_FAILED", quality["blocker_codes"])
        self.assertEqual(quality["final_repeat_convergence_gate"]["final_repeat_high_count_after"], 0)

    def test_failure_sample_visible_repeat_candidates_block_ready(self) -> None:
        caption_gate = build_final_caption_visible_repeat_gate(
            [
                _caption(1, "v21_seg_000001", 0, 640_000, text="就国南"),
                _caption(51, "v21_seg_000051", 69_239_998, 70_799_998, text="就国南就只会内斗"),
                _caption(59, "v21_seg_000059", 81_320_000, 83_186_666, text="她们就是在集体做多啊"),
                _caption(75, "v21_seg_000075", 106_406_666, 106_886_666, text="就是在"),
            ]
        )
        quality = build_quality_gate_report(
            effective_speed_gate={"gate_passed": True, "blocker_codes": []},
            final_repeat_convergence_gate={"gate_passed": True, "blocker_codes": [], "final_repeat_high_count_after": 0},
            final_caption_visible_repeat_gate=caption_gate,
            visual_pacing_gate={
                "gate_passed": True,
                "blocker_codes": [],
                "visual_pacing_executed": True,
                "visual_merge_safety_gate_passed": True,
            },
            caption_alignment_gate={"gate_passed": True, "blocker_codes": []},
            ready_for_user_manual_qc_preconditions_passed=True,
        )

        self.assertFalse(quality["gate_passed"])
        self.assertEqual(caption_gate["containment_repeat_count"], 2)
        self.assertEqual(caption_gate["visible_repeat_candidate_count"], 2)
        self.assertIn("V21_FINAL_CAPTION_VISIBLE_REPEAT_GATE_FAILED", quality["blocker_codes"])

    def test_repeat_convergence_does_not_zero_report_without_detector(self) -> None:
        report = build_final_repeat_convergence_report(
            decision_trace=[],
            final_repeat_report={},
        )

        self.assertFalse(report["gate_passed"])
        self.assertFalse(report["detector_report_present"])
        self.assertIn("V21_FINAL_REPEAT_DETECTOR_REPORT_MISSING", report["blocker_codes"])

    def test_visual_pacing_report_fields(self) -> None:
        report = build_visual_pacing_report(
            final_timeline=[_segment(1, 0, 500_000), _segment(2, 500_000, 2_000_000)],
            captions=[_caption(1, "v21_seg_000001", 0, 500_000), _caption(2, "v21_seg_000002", 500_000, 2_000_000)],
            executed=True,
            merge_report={
                "visual_pacing_executed": True,
                "visual_pacing_merge_attempted_count": 0,
                "visual_pacing_merged_count": 0,
                "visual_short_segment_count_lt_1200ms_before": 1,
                "visual_short_segment_count_lt_1200ms_after": 1,
                "semantic_bridge_short_segment_count": 1,
                "visual_pacing_blocker_codes": [],
            },
        )

        self.assertTrue(report["gate_passed"])
        self.assertEqual(report["final_video_segment_count"], 2)
        self.assertEqual(report["caption_count"], 2)
        self.assertEqual(report["visual_short_segment_count_lt_1200ms"], 1)
        self.assertGreater(report["median_segment_duration_us"], 0)
        self.assertGreater(report["p10_segment_duration_us"], 0)
        self.assertTrue(report["visual_pacing_executed"])

    def test_visual_pacing_report_false_when_not_executed(self) -> None:
        report = build_visual_pacing_report(
            final_timeline=[_segment(1, 0, 500_000), _segment(2, 500_000, 2_000_000)],
            captions=[_caption(1, "v21_seg_000001", 0, 500_000), _caption(2, "v21_seg_000002", 500_000, 2_000_000)],
        )

        self.assertFalse(report["gate_passed"])
        self.assertIn("V21_VISUAL_PACING_NOT_EXECUTED", report["blocker_codes"])

    def test_visual_pacing_executes_merge_not_report_only(self) -> None:
        result = _multi_caption_fake_result()
        source_graph = ArollEngine().ingest.build_source_graph(
            draft_data=result.draft_data,
            word_timeline=result.word_timeline,
            subtitles=result.subtitles,
            source_segments=result.source_segments,
            source_materials=result.source_materials,
            text_materials=result.text_materials,
            text_segments=result.text_segments,
        )
        initial = [
            replace(_segment(1, 0, 300_000), text="这个", word_ids=["w001"]),
            replace(_segment(2, 350_000, 650_000), text="那个", word_ids=["w002"]),
            replace(_segment(3, 700_000, 1_200_000), text="然后", word_ids=["w003"]),
        ]

        normalized, visual = VisualPacingNormalizer().normalize(initial, source_graph)

        self.assertTrue(visual["visual_pacing_executed"])
        self.assertGreater(visual["visual_pacing_merged_count"], 0)
        self.assertLess(len(normalized), len(initial))
        self.assertTrue(visual["gate_passed"])
        self.assertTrue(visual["visual_merge_safety_gate_passed"])

    def test_residual_visual_short_segments_merge_when_safe(self) -> None:
        source_graph = _graph_for_visual_merge_rows(
            [
                ("w001", "啊", 0, 300_000),
                ("w002", "继续", 380_000, 780_000),
            ]
        )
        initial = [
            replace(_segment(1, 0, 300_000), text="啊", word_ids=["w001"]),
            replace(_segment(2, 380_000, 780_000), text="继续", word_ids=["w002"]),
        ]

        normalized, visual = VisualPacingNormalizer().normalize(initial, source_graph)

        self.assertEqual(len(normalized), 1)
        self.assertTrue(visual["gate_passed"])
        self.assertEqual(visual["visual_short_segment_count_lt_1200ms_after_blocking"], 0)

    def test_residual_visual_short_segments_semantic_bridge_exception_not_blocking(self) -> None:
        source_graph = _graph_for_visual_merge_rows([("w001", "语义桥", 0, 700_000)])
        initial = [replace(_segment(1, 0, 700_000), text="语义桥", word_ids=["w001"])]

        normalized, visual = VisualPacingNormalizer().normalize(initial, source_graph)

        self.assertEqual(len(normalized), 1)
        self.assertTrue(visual["gate_passed"])
        self.assertEqual(visual["semantic_bridge_short_segment_count"], 1)
        self.assertEqual(visual["visual_short_segment_count_lt_1200ms_after_blocking"], 0)
        self.assertEqual(visual["residual_visual_short_segments"][0]["short_segment_status"], "semantic_bridge_exception")

    def test_residual_weak_filler_short_segment_merges_or_drops(self) -> None:
        source_graph = _graph_for_visual_merge_rows(
            [
                ("w001", "就", 0, 240_000),
                ("w002", "继续表达", 300_000, 900_000),
            ]
        )
        initial = [
            replace(_segment(1, 0, 240_000), text="就", word_ids=["w001"]),
            replace(_segment(2, 300_000, 900_000), text="继续表达", word_ids=["w002"]),
        ]

        normalized, visual = VisualPacingNormalizer().normalize(initial, source_graph)

        self.assertLess(len(normalized), len(initial))
        self.assertTrue(visual["gate_passed"])
        self.assertEqual(visual["visual_short_segment_count_lt_1200ms_after_blocking"], 0)

    def test_one_char_weak_filler_micro_segment_cannot_survive(self) -> None:
        source_graph = _graph_for_visual_merge_rows(
            [
                ("w001", "前面内容", 0, 1_200_000),
                ("w002", "就", 2_000_000, 2_240_000),
                ("w003", "后面内容继续", 3_000_000, 4_300_000),
            ]
        )
        initial = [
            replace(_segment(1, 0, 1_200_000), source_end_us=1_200_000, text="前面内容", word_ids=["w001"]),
            replace(_segment(2, 2_000_000, 2_240_000), source_start_us=2_000_000, source_end_us=2_240_000, text="就", word_ids=["w002"]),
            replace(_segment(3, 3_000_000, 4_300_000), source_start_us=3_000_000, source_end_us=4_300_000, text="后面内容继续", word_ids=["w003"]),
        ]

        normalized, visual = VisualPacingNormalizer().normalize(initial, source_graph)
        captions = SubtitleRenderer().render(normalized, source_graph)
        alignment = build_caption_alignment_report(final_timeline=normalized, captions=captions)

        self.assertTrue(all(segment.text != "就" for segment in normalized))
        self.assertEqual(visual["visual_short_segment_count_lt_1200ms_after_blocking"], 0)
        self.assertEqual(alignment["one_char_caption_count"], 0)
        self.assertEqual(alignment["caption_too_short_count"], 0)

    def test_one_char_weak_filler_micro_segment_merges_when_safe(self) -> None:
        source_graph = _graph_for_visual_merge_rows(
            [
                ("w001", "就", 0, 240_000),
                ("w002", "继续表达", 300_000, 1_200_000),
            ]
        )
        initial = [
            replace(_segment(1, 0, 240_000), text="就", word_ids=["w001"]),
            replace(_segment(2, 300_000, 1_200_000), source_start_us=300_000, source_end_us=1_200_000, text="继续表达", word_ids=["w002"]),
        ]

        normalized, visual = VisualPacingNormalizer().normalize(initial, source_graph)
        captions = SubtitleRenderer().render(normalized, source_graph)
        alignment = build_caption_alignment_report(final_timeline=normalized, captions=captions)

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0].text, "就继续表达")
        self.assertEqual(visual["merged_weak_filler_micro_segment_count"], 1)
        self.assertEqual(visual["dropped_weak_filler_micro_segment_count"], 0)
        self.assertEqual(alignment["one_char_caption_count"], 0)
        self.assertEqual(alignment["caption_too_short_count"], 0)

    def test_one_char_weak_filler_micro_segment_drops_when_merge_unsafe(self) -> None:
        source_graph = _graph_for_visual_merge_rows(
            [
                ("w001", "就", 0, 240_000),
                ("w002", "继续表达很好", 900_000, 2_200_000),
            ]
        )
        initial = [
            replace(_segment(1, 0, 240_000), text="就", word_ids=["w001"]),
            replace(_segment(2, 900_000, 2_200_000), source_start_us=900_000, source_end_us=2_200_000, text="继续表达很好", word_ids=["w002"]),
        ]

        normalized, visual = VisualPacingNormalizer().normalize(initial, source_graph)
        captions = SubtitleRenderer().render(normalized, source_graph)
        alignment = build_caption_alignment_report(final_timeline=normalized, captions=captions)

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0].text, "继续表达很好")
        self.assertEqual(visual["merged_weak_filler_micro_segment_count"], 0)
        self.assertEqual(visual["dropped_weak_filler_micro_segment_count"], 1)
        self.assertEqual(visual["visual_short_segment_count_lt_1200ms_after_blocking"], 0)
        self.assertEqual(alignment["one_char_caption_count"], 0)
        self.assertEqual(alignment["caption_too_short_count"], 0)

    def test_visual_pacing_gate_blocks_when_short_segments_remain(self) -> None:
        class NoopVisualPacing:
            def normalize(self, final_timeline, source_graph):
                return final_timeline, {
                    "visual_pacing_executed": True,
                    "visual_pacing_merge_attempted_count": 0,
                    "visual_pacing_merged_count": 0,
                    "visual_short_segment_count_lt_1200ms_before": 1,
                    "visual_short_segment_count_lt_1200ms_after": 1,
                    "semantic_bridge_short_segment_count": 0,
                    "visual_pacing_blocker_codes": ["V21_VISUAL_PACING_SHORT_SEGMENTS_REMAIN"],
                }

        result = fake_real_draft_result()
        report = ArollEngine(visual_pacing=NoopVisualPacing()).run(
            ArollRunInput(
                mode="write",
                draft_data=result.draft_data,
                word_timeline=result.word_timeline,
                subtitles=result.subtitles,
                source_segments=result.source_segments,
                source_materials=result.source_materials,
                text_materials=result.text_materials,
                text_segments=result.text_segments,
                postwrite_mode="simulated",
            )
        )

        self.assertEqual(report.status, "blocked")
        visual = report.validator_report["visual_pacing_gate"]
        self.assertFalse(visual["gate_passed"])
        self.assertIn("V21_VISUAL_PACING_SHORT_SEGMENTS_REMAIN", visual["blocker_codes"])

    def test_visual_merge_does_not_cross_dropped_repeat_segment(self) -> None:
        source_graph = _graph_for_visual_merge_rows(
            [
                ("w001", "啊", 0, 300_000),
                ("w_drop", "删", 400_000, 700_000),
                ("w002", "呃", 800_000, 1_100_000),
            ]
        )
        initial = [
            replace(_segment(1, 0, 300_000), text="啊", word_ids=["w001"]),
            replace(_segment(2, 800_000, 1_100_000), text="呃", word_ids=["w002"]),
        ]

        normalized, visual = VisualPacingNormalizer().normalize(initial, source_graph)

        self.assertEqual(len(normalized), 2)
        self.assertFalse(visual["gate_passed"])
        self.assertEqual(visual["dropped_content_reintroduced_count"], 0)
        self.assertGreater(visual["visual_merge_safety_report"]["visual_pacing_blocked_unsafe_merge_attempt_count"], 0)

    def test_visual_merge_does_not_cross_hidden_repeat_cleanup_span(self) -> None:
        source_graph = _graph_for_visual_merge_rows(
            [
                ("w001", "啊", 0, 300_000),
                ("w_hidden", "重复", 360_000, 660_000),
                ("w002", "呃", 720_000, 1_020_000),
            ]
        )
        initial = [
            replace(_segment(1, 0, 300_000), text="啊", word_ids=["w001"]),
            replace(_segment(2, 720_000, 1_020_000), text="呃", word_ids=["w002"]),
        ]

        normalized, visual = VisualPacingNormalizer().normalize(initial, source_graph)

        self.assertEqual(len(normalized), 2)
        self.assertFalse(visual["gate_passed"])
        self.assertGreater(visual["visual_merge_safety_report"]["visual_pacing_blocked_unsafe_merge_attempt_count"], 0)

    def test_visual_merge_does_not_cross_boundary_overlap_cleanup_span(self) -> None:
        source_graph = _graph_for_visual_merge_rows(
            [
                ("w001", "啊", 0, 300_000),
                ("w_boundary", "边界", 320_000, 620_000),
                ("w002", "呃", 680_000, 980_000),
            ]
        )
        initial = [
            replace(_segment(1, 0, 300_000), text="啊", word_ids=["w001"]),
            replace(_segment(2, 680_000, 980_000), text="呃", word_ids=["w002"]),
        ]

        normalized, visual = VisualPacingNormalizer().normalize(initial, source_graph)

        self.assertEqual(len(normalized), 2)
        self.assertFalse(visual["gate_passed"])
        self.assertGreater(visual["visual_merge_safety_report"]["visual_pacing_blocked_unsafe_merge_attempt_count"], 0)

    def test_visual_merge_does_not_bridge_large_unspoken_gap(self) -> None:
        source_graph = _graph_for_visual_merge_rows(
            [
                ("w001", "啊", 0, 300_000),
                ("w002", "呃", 800_000, 1_100_000),
            ]
        )
        initial = [
            replace(_segment(1, 0, 300_000), text="啊", word_ids=["w001"]),
            replace(_segment(2, 800_000, 1_100_000), text="呃", word_ids=["w002"]),
        ]

        normalized, visual = VisualPacingNormalizer().normalize(initial, source_graph)

        self.assertEqual(len(normalized), 2)
        self.assertFalse(visual["gate_passed"])
        self.assertGreater(visual["visual_merge_safety_report"]["visual_pacing_blocked_unsafe_merge_attempt_count"], 0)

    def test_visual_merge_allows_small_safe_gap_same_source_window(self) -> None:
        source_graph = _graph_for_visual_merge_rows(
            [
                ("w001", "啊", 0, 300_000),
                ("w002", "呃", 380_000, 680_000),
            ]
        )
        initial = [
            replace(_segment(1, 0, 300_000), text="啊", word_ids=["w001"]),
            replace(_segment(2, 380_000, 680_000), text="呃", word_ids=["w002"]),
        ]

        normalized, visual = VisualPacingNormalizer().normalize(initial, source_graph)

        self.assertEqual(len(normalized), 1)
        self.assertTrue(visual["visual_merge_safety_gate_passed"])
        self.assertEqual(visual["unsafe_merge_group_count"], 0)
        self.assertEqual(visual["dropped_content_reintroduced_count"], 0)
        self.assertEqual(visual["max_bridged_gap_us"], 80_000)

    def test_visual_merge_safety_report_records_child_segments_and_gaps(self) -> None:
        source_graph = _graph_for_visual_merge_rows(
            [
                ("w001", "啊", 0, 300_000),
                ("w002", "呃", 380_000, 680_000),
            ]
        )
        initial = [
            replace(_segment(1, 0, 300_000), text="啊", word_ids=["w001"]),
            replace(_segment(2, 380_000, 680_000), text="呃", word_ids=["w002"]),
        ]

        _normalized, visual = VisualPacingNormalizer().normalize(initial, source_graph)
        groups = visual["visual_merge_groups"]

        self.assertEqual(groups[0]["child_segment_ids"], ["v21_seg_000001", "v21_seg_000002"])
        self.assertEqual(groups[0]["source_window_id"], "primary_window")
        self.assertEqual(groups[0]["bridged_gaps"][0]["duration_us"], 80_000)
        self.assertTrue(groups[0]["merge_safe"])

    def test_visual_pacing_blocks_overmerged_four_segments_without_safety_proof(self) -> None:
        report = build_visual_pacing_report(
            final_timeline=[_segment(index, index * 1_000_000, (index + 1) * 1_000_000) for index in range(4)],
            captions=[_caption(index, "v21_seg_000001", index * 100_000, index * 100_000 + 80_000) for index in range(1, 109)],
            executed=True,
            merge_report={"visual_pacing_merged_count": 126},
        )

        self.assertFalse(report["gate_passed"])
        self.assertFalse(report["visual_merge_safety_gate_passed"])
        self.assertIn("V21_VISUAL_PACING_MISSING_MERGE_SAFETY_PROOF", report["blocker_codes"])

    def test_quality_gate_requires_visual_merge_safety(self) -> None:
        quality = build_quality_gate_report(
            effective_speed_gate={"gate_passed": True, "blocker_codes": []},
            final_repeat_convergence_gate={"gate_passed": True, "blocker_codes": []},
            visual_pacing_gate={"gate_passed": True, "visual_pacing_executed": True, "blocker_codes": []},
            caption_alignment_gate={"gate_passed": True, "blocker_codes": []},
        )

        self.assertFalse(quality["gate_passed"])
        self.assertIn("V21_VISUAL_PACING_UNSAFE_MERGE", quality["blocker_codes"])

    def test_caption_per_video_segment_ratio_high_requires_safe_bridge_proof(self) -> None:
        report = build_visual_pacing_report(
            final_timeline=[_segment(1, 0, 2_000_000)],
            captions=[_caption(index, "v21_seg_000001", index * 100_000, index * 100_000 + 80_000) for index in range(1, 13)],
            executed=True,
            merge_report={"visual_pacing_merged_count": 0},
        )

        self.assertFalse(report["gate_passed"])
        self.assertFalse(report["visual_merge_safety_gate_passed"])

    def test_final_video_segment_count_can_drop_only_when_merge_safety_passes(self) -> None:
        source_graph = _graph_for_visual_merge_rows(
            [
                ("w001", "啊", 0, 300_000),
                ("w002", "呃", 380_000, 680_000),
            ]
        )
        initial = [
            replace(_segment(1, 0, 300_000), text="啊", word_ids=["w001"]),
            replace(_segment(2, 380_000, 680_000), text="呃", word_ids=["w002"]),
        ]

        normalized, visual = VisualPacingNormalizer().normalize(initial, source_graph)

        self.assertEqual(len(normalized), 1)
        self.assertTrue(visual["gate_passed"])
        self.assertTrue(visual["visual_merge_safety_gate_passed"])

    def test_hidden_repeated_suffix_island_drops_whole_word_span(self) -> None:
        materials, text_segments = _template_rows()
        words = []
        cursor = 0
        for index, token in enumerate(["重复", "短语", "中间", "重复", "短语"], start=1):
            words.append(
                {
                    "word_id": f"w_{index:06d}",
                    "word_text": token,
                    "start_us": cursor,
                    "end_us": cursor + 200_000,
                    "subtitle_index": 1,
                    "subtitle_uid": "s001",
                }
            )
            cursor += 200_000

        report = ArollEngine().run(
            ArollRunInput(
                mode="write",
                source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": cursor + 500_000}],
                word_timeline=words,
                subtitles=[
                    {
                        "subtitle_uid": "s001",
                        "subtitle_index": 1,
                        "text": "重复短语中间重复短语",
                        "word_ids": [row["word_id"] for row in words],
                    }
                ],
                text_materials=materials,
                text_segments=text_segments,
                postwrite_mode="simulated",
            )
        )

        self.assertEqual(report.status, "ok", [blocker.code for blocker in report.blocker_report.blockers])
        self.assertEqual([caption.text for caption in report.captions], ["重复短语中间"])
        self.assertEqual(report.final_timeline[0].word_ids, ["w_000001", "w_000002", "w_000003"])
        self.assertTrue(report.validator_report["hidden_audio_repeat_validator"]["hidden_audio_repeat_gate_passed"])
        trace = [row for row in report.decision_trace if row.get("decision") == "drop_repeated_suffix_island"]
        self.assertEqual(trace[0]["dropped_word_ids"], ["w_000004", "w_000005"])

    def test_visual_pacing_cleanup_drops_hidden_repeat_created_by_merge(self) -> None:
        materials, text_segments = _template_rows()
        rows = [
            ("w_000001", "然后", 0, 300_000),
            ("w_000002", "亲手", 300_000, 600_000),
            ("w_000003", "摧毁", 600_000, 900_000),
            ("w_000004", "然后", 1_100_000, 1_400_000),
        ]
        words = [
            {
                "word_id": word_id,
                "word_text": text,
                "start_us": start,
                "end_us": end,
                "subtitle_index": 1,
                "subtitle_uid": "s001",
            }
            for word_id, text, start, end in rows
        ]

        engine = ArollEngine()
        source_graph = engine.ingest.build_source_graph(
            word_timeline=words,
            subtitles=[
                {
                    "subtitle_uid": "s001",
                    "subtitle_index": 1,
                    "text": "然后亲手摧毁然后",
                    "word_ids": [row["word_id"] for row in words],
                }
            ],
            source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 2_000_000}],
            text_materials=materials,
            text_segments=text_segments,
        )
        initial = [
            replace(_segment(1, 0, 900_000), text="然后亲手摧毁", word_ids=["w_000001", "w_000002", "w_000003"]),
            replace(_segment(2, 1_100_000, 1_400_000), text="然后", word_ids=["w_000004"]),
        ]

        normalized, visual = VisualPacingNormalizer().normalize(initial, source_graph)
        captions = engine.renderer.render(normalized, source_graph)

        self.assertEqual([segment.text for segment in normalized], ["然后亲手摧毁"])
        self.assertEqual(normalized[0].word_ids, ["w_000001", "w_000002", "w_000003"])
        self.assertEqual([caption.text for caption in captions], ["然后亲手摧毁"])
        self.assertTrue(visual["visual_pacing_executed"])
        self.assertGreater(visual["visual_pacing_merged_count"], 0)
        self.assertEqual(visual["visual_pacing_hidden_repeat_dropped_word_count"], 1)
        self.assertEqual(
            build_caption_alignment_report(final_timeline=normalized, captions=captions)["caption_overlap_count"],
            0,
        )

    def test_visual_pacing_cleanup_drops_caption_boundary_suffix_prefix_overlap(self) -> None:
        materials, text_segments = _template_rows()
        rows = [
            ("w_000001", "就是", 0, 300_000, 1, "s001"),
            ("w_000002", "在", 300_000, 500_000, 1, "s001"),
            ("w_000003", "亲手", 500_000, 800_000, 1, "s001"),
            ("w_000004", "摧毁", 800_000, 1_100_000, 1, "s001"),
            ("w_000005", "亲手", 1_300_000, 1_600_000, 2, "s002"),
            ("w_000006", "摧毁", 1_600_000, 1_900_000, 2, "s002"),
            ("w_000007", "男性", 1_900_000, 2_200_000, 2, "s002"),
        ]
        words = [
            {
                "word_id": word_id,
                "word_text": text,
                "start_us": start,
                "end_us": end,
                "subtitle_index": subtitle_index,
                "subtitle_uid": subtitle_uid,
            }
            for word_id, text, start, end, subtitle_index, subtitle_uid in rows
        ]
        engine = ArollEngine()
        source_graph = engine.ingest.build_source_graph(
            word_timeline=words,
            subtitles=[
                {
                    "subtitle_uid": "s001",
                    "subtitle_index": 1,
                    "text": "就是在亲手摧毁",
                    "word_ids": ["w_000001", "w_000002", "w_000003", "w_000004"],
                },
                {
                    "subtitle_uid": "s002",
                    "subtitle_index": 2,
                    "text": "亲手摧毁男性",
                    "word_ids": ["w_000005", "w_000006", "w_000007"],
                },
            ],
            source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 2_500_000}],
            text_materials=materials,
            text_segments=text_segments,
        )
        initial = [
            replace(_segment(1, 0, 1_100_000), text="就是在亲手摧毁", word_ids=["w_000001", "w_000002", "w_000003", "w_000004"]),
            replace(_segment(2, 1_300_000, 2_200_000), text="亲手摧毁男性", word_ids=["w_000005", "w_000006", "w_000007"]),
        ]

        normalized, visual = VisualPacingNormalizer().normalize(initial, source_graph)
        captions = engine.renderer.render(normalized, source_graph)

        self.assertEqual([segment.text for segment in normalized], ["就是在", "亲手摧毁男性"])
        self.assertEqual(normalized[0].word_ids, ["w_000001", "w_000002"])
        self.assertEqual([caption.text for caption in captions], ["就是在", "亲手摧毁男性"])
        self.assertEqual(visual["visual_pacing_boundary_overlap_dropped_word_count"], 2)

    def test_caption_uses_spoken_target_span(self) -> None:
        report = build_caption_alignment_report(
            final_timeline=[_segment(1, 0, 1_000_000)],
            captions=[_caption(1, "v21_seg_000001", 100_000, 700_000)],
        )

        self.assertTrue(report["gate_passed"])
        self.assertEqual(report["caption_outside_video_count"], 0)

    def test_caption_alignment_blocks_ready_when_invalid(self) -> None:
        caption_report = build_caption_alignment_report(
            final_timeline=[_segment(1, 0, 500_000)],
            captions=[_caption(1, "v21_seg_000001", 400_000, 800_000, text="字")],
        )
        quality_report = build_quality_gate_report(caption_alignment_gate=caption_report)

        self.assertFalse(caption_report["gate_passed"])
        self.assertFalse(quality_report["gate_passed"])
        self.assertIn("V21_CAPTION_OUTSIDE_VIDEO_SEGMENT", quality_report["blocker_codes"])
        self.assertIn("V21_ONE_CHAR_CAPTION", quality_report["blocker_codes"])

    def test_caption_alignment_uses_containing_video_segment_not_self_final_segment(self) -> None:
        caption = CaptionRenderUnit(
            caption_id="v21_cap_000001",
            timeline_segment_ids=["v21_seg_000001"],
            word_ids=["w2"],
            text="字幕",
            target_start_us=100_000,
            target_end_us=500_000,
            source_subtitle_uids=["s1"],
            style_template_id="canonical_caption_template",
            spoken_source_start_us=1_300_000,
            spoken_source_end_us=1_600_000,
            containing_video_segment_id="v21_seg_000001",
        )
        report = build_caption_alignment_report(
            final_timeline=[_segment(1, 0, 1_000_000)],
            captions=[caption],
        )

        self.assertFalse(report["gate_passed"])
        self.assertEqual(report["caption_cross_primary_window_count"], 1)
        self.assertIn("V21_CAPTION_CROSSES_PRIMARY_SOURCE_WINDOW", report["blocker_codes"])

    def test_caption_too_short_separate_from_outside_video_count(self) -> None:
        report = build_caption_alignment_report(
            final_timeline=[_segment(1, 0, 1_000_000)],
            captions=[_caption(1, "v21_seg_000001", 100_000, 250_000, text="字幕")],
        )

        self.assertFalse(report["gate_passed"])
        self.assertEqual(report["caption_too_short_count"], 1)
        self.assertEqual(report["caption_outside_video_count"], 0)
        self.assertIn("V21_CAPTION_TOO_SHORT", report["blocker_codes"])

    def test_caption_gui_gate_blocks_orphan_or_floating_captions(self) -> None:
        orphan = CaptionRenderUnit(
            caption_id="v21_cap_orphan",
            timeline_segment_ids=[],
            word_ids=["w1"],
            text="字幕内容",
            target_start_us=100_000,
            target_end_us=700_000,
            source_subtitle_uids=["s1"],
            style_template_id="canonical_caption_template",
        )

        report = build_caption_alignment_report(final_timeline=[_segment(1, 0, 1_000_000)], captions=[orphan])

        self.assertFalse(report["gate_passed"])
        self.assertEqual(report["orphan_caption_count"], 1)
        self.assertEqual(report["floating_caption_count"], 1)
        self.assertIn("V21_CAPTION_GUI_TRACK_GATE_FAILED", report["blocker_codes"])

    def test_caption_gui_gate_requires_single_visible_caption_track(self) -> None:
        report = build_caption_alignment_report(
            final_timeline=[_segment(1, 0, 1_000_000)],
            captions=[_caption(1, "v21_seg_000001", 100_000, 700_000, text="字幕内容")],
            visible_caption_track_count=2,
            caption_lane_count=1,
        )
        quality = build_quality_gate_report(caption_alignment_gate=report)

        self.assertFalse(report["caption_gui_track_gate_passed"])
        self.assertFalse(quality["gate_passed"])
        self.assertEqual(report["visible_caption_track_count"], 2)
        self.assertIn("V21_CAPTION_GUI_TRACK_GATE_FAILED", quality["blocker_codes"])

    def test_subtitle_readability_blocks_many_tiny_captions(self) -> None:
        captions = [
            _caption(index, "v21_seg_000001", (index - 1) * 600_000, index * 600_000, text=f"短{index}")
            for index in range(1, 8)
        ]

        report = build_caption_alignment_report(
            final_timeline=[_segment(1, 0, 5_000_000)],
            captions=captions,
        )

        self.assertFalse(report["gate_passed"])
        self.assertEqual(report["captions_le_3_chars"], 7)
        self.assertEqual(report["captions_le_3_chars_cap"], 3)
        self.assertIn("V21_SUBTITLE_READABILITY_GATE_FAILED", report["blocker_codes"])

    def test_subtitle_readability_blocks_hard_max_chars(self) -> None:
        report = build_caption_alignment_report(
            final_timeline=[_segment(1, 0, 2_000_000)],
            captions=[_caption(1, "v21_seg_000001", 100_000, 1_100_000, text="这是一个明显超过二十个字符限制的超长字幕块内容")],
        )

        self.assertFalse(report["gate_passed"])
        self.assertEqual(report["subtitle_hard_max_char_count"], 1)
        self.assertIn("V21_SUBTITLE_HARD_MAX_CHARS", report["blocker_codes"])
        self.assertIn("V21_SUBTITLE_READABILITY_GATE_FAILED", report["blocker_codes"])

    def test_caption_density_gate_blocks_bursty_caption_timeline(self) -> None:
        captions = [
            _caption(index, "v21_seg_000001", (index - 1) * 500_000, index * 500_000, text=f"字幕内容{index}")
            for index in range(1, 10)
        ]

        report = build_caption_alignment_report(
            final_timeline=[_segment(1, 0, 6_000_000)],
            captions=captions,
        )

        self.assertFalse(report["gate_passed"])
        self.assertEqual(report["max_captions_in_5s"], 9)
        self.assertGreater(report["caption_burst_density_count"], 0)
        self.assertIn("V21_SUBTITLE_READABILITY_GATE_FAILED", report["blocker_codes"])

    def test_v20_subtitle_interval_thresholds_are_gate_enforced(self) -> None:
        report = build_caption_alignment_report(
            final_timeline=[_segment(1, 0, 5_000_000)],
            captions=[
                _caption(1, "v21_seg_000001", 100_000, 4_000_000, text="字幕内容"),
            ],
        )
        quality = build_quality_gate_report(caption_alignment_gate=report)

        self.assertFalse(report["gate_passed"])
        self.assertEqual(report["subtitle_interval_too_long_count"], 1)
        self.assertIn("V21_SUBTITLE_TOO_LONG", report["blocker_codes"])
        self.assertIn("V21_SUBTITLE_READABILITY_GATE_FAILED", quality["blocker_codes"])

    def test_quality_gate_missing_required_gate_fail_closed(self) -> None:
        quality = build_quality_gate_report()

        self.assertFalse(quality["gate_passed"])
        self.assertFalse(quality["effective_speed_gate_present"])
        self.assertFalse(quality["semantic_adjudication_gate_present"])
        self.assertFalse(quality["visual_pacing_gate_present"])
        self.assertIn("V21_QUALITY_GATE_MISSING_REQUIRED_GATE", quality["blocker_codes"])

    def test_quality_gate_missing_semantic_adjudication_gate_fail_closed(self) -> None:
        quality = build_quality_gate_report(
            effective_speed_gate={"gate_passed": True, "blocker_codes": []},
            final_repeat_convergence_gate={"gate_passed": True, "blocker_codes": [], "final_repeat_high_count_after": 0},
            visual_pacing_gate={
                "gate_passed": True,
                "blocker_codes": [],
                "visual_pacing_executed": True,
                "visual_merge_safety_gate_passed": True,
            },
            caption_alignment_gate={"gate_passed": True, "blocker_codes": []},
            ready_for_user_manual_qc_preconditions_passed=True,
        )

        self.assertFalse(quality["gate_passed"])
        self.assertFalse(quality["semantic_adjudication_gate_present"])
        self.assertFalse(quality["semantic_adjudication_gate_passed"])
        self.assertIn("V21_QUALITY_GATE_MISSING_REQUIRED_GATE", quality["blocker_codes"])

    def test_quality_gate_subreport_without_gate_passed_fails_closed(self) -> None:
        quality = build_quality_gate_report(
            effective_speed_gate={"blocker_codes": []},
            final_repeat_convergence_gate={"gate_passed": True, "blocker_codes": []},
            visual_pacing_gate={
                "gate_passed": True,
                "visual_pacing_executed": True,
                "visual_merge_safety_gate_passed": True,
                "blocker_codes": [],
            },
            caption_alignment_gate={"gate_passed": True, "blocker_codes": []},
            ready_for_user_manual_qc_preconditions_passed=True,
        )

        self.assertFalse(quality["gate_passed"])
        self.assertFalse(quality["effective_speed_gate"]["gate_passed"])

    def test_prewrite_effective_speed_not_applicable_is_not_summary_passed(self) -> None:
        quality = build_quality_gate_report(
            effective_speed_gate={
                "gate_passed": False,
                "blocker_codes": [],
                "prewrite_pending": True,
                "not_applicable": True,
                "not_applicable_reason": "prewrite_source_binding_pending",
            },
            final_repeat_convergence_gate={"gate_passed": True, "blocker_codes": [], "final_repeat_high_count_after": 0},
            visual_pacing_gate={
                "gate_passed": True,
                "blocker_codes": [],
                "visual_pacing_executed": True,
                "visual_merge_safety_gate_passed": True,
            },
            semantic_adjudication_gate=_semantic_gate_ok(),
            caption_alignment_gate={"gate_passed": True, "blocker_codes": []},
            ready_for_user_manual_qc_preconditions_passed=True,
        )
        report = RunReport(
            status="ok",
            source_graph=None,
            repeat_clusters=[],
            decision_plan=None,
            final_timeline=[],
            captions=[],
            material_write_plan={},
            validator_report={"validator_report_ok": True, "quality_gate_report": quality},
            postwrite_report={},
            blocker_report=BlockerReport(blocked=False, blockers=[]),
        )

        summary = build_run_summary(report)

        self.assertTrue(quality["gate_passed"])
        self.assertFalse(summary["effective_speed_gate_passed"])
        self.assertTrue(summary["effective_speed_not_applicable"])
        self.assertIsNone(summary["effective_speed_min"])
        self.assertIsNone(summary["effective_speed_max"])

    def test_quality_gate_normalizes_prewrite_effective_speed_placeholder(self) -> None:
        quality = build_quality_gate_report(
            effective_speed_gate={"gate_passed": True, "blocker_codes": [], "prewrite_pending": True},
            final_repeat_convergence_gate={"gate_passed": True, "blocker_codes": [], "final_repeat_high_count_after": 0},
            visual_pacing_gate={
                "gate_passed": True,
                "blocker_codes": [],
                "visual_pacing_executed": True,
                "visual_merge_safety_gate_passed": True,
            },
            semantic_adjudication_gate=_semantic_gate_ok(),
            caption_alignment_gate={"gate_passed": True, "blocker_codes": []},
            ready_for_user_manual_qc_preconditions_passed=True,
        )

        self.assertTrue(quality["gate_passed"])
        self.assertFalse(quality["effective_speed_gate"]["gate_passed"])
        self.assertTrue(quality["effective_speed_gate"]["not_applicable"])
        self.assertEqual(quality["effective_speed_gate"]["not_applicable_reason"], "prewrite_source_binding_pending")

    def test_quality_gate_rejects_unscoped_effective_speed_not_applicable(self) -> None:
        quality = build_quality_gate_report(
            effective_speed_gate={"gate_passed": False, "blocker_codes": [], "not_applicable": True},
            final_repeat_convergence_gate={"gate_passed": True, "blocker_codes": [], "final_repeat_high_count_after": 0},
            visual_pacing_gate={
                "gate_passed": True,
                "blocker_codes": [],
                "visual_pacing_executed": True,
                "visual_merge_safety_gate_passed": True,
            },
            caption_alignment_gate={"gate_passed": True, "blocker_codes": []},
            ready_for_user_manual_qc_preconditions_passed=True,
        )

        self.assertFalse(quality["gate_passed"])
        self.assertIn("V21_EFFECTIVE_SPEED_GATE_FAILED", quality["blocker_codes"])

    def test_validator_blockers_include_quality_subgate_codes(self) -> None:
        blockers = ArollEngine()._validator_blockers(
            {
                "validators_read_only": True,
                "final_repeat_validator": {"final_repeat_gate_passed": True},
                "hidden_audio_repeat_validator": {"hidden_audio_repeat_gate_passed": True},
                "safe_cut_validator": {"safe_cut_boundary_gate_passed": True},
                "subtitle_coverage_validator": {"subtitle_coverage_gate_passed": True},
                "caption_alignment_gate": {"gate_passed": True, "blocker_codes": []},
                "final_caption_visible_repeat_gate": {"gate_passed": True, "blocker_codes": []},
                "subtitle_style_validator": {"prewrite_style_gate_ok": True},
                "rough_cut_quality_validator": {"rough_cut_quality_gate_passed": True},
                "postwrite_material_validator": {"postwrite_material_gate_ok": True},
                "semantic_final_review_validator": {"semantic_final_review_validator_passed": True},
                "quality_gate_report": {
                    "gate_passed": False,
                    "blocker_codes": ["V21_VISUAL_CUT_DENSITY_FAILED", "V21_SUBTITLE_READABILITY_GATE_FAILED"],
                },
            }
        )

        codes = [blocker.code for blocker in blockers]
        self.assertIn("V21_QUALITY_GATE_FAILED", codes)
        self.assertIn("V21_VISUAL_CUT_DENSITY_FAILED", codes)
        self.assertIn("V21_SUBTITLE_READABILITY_GATE_FAILED", codes)

    def test_quality_gate_preserves_subgate_diagnostic_fields(self) -> None:
        quality = build_quality_gate_report(
            effective_speed_gate={
                "gate_passed": True,
                "blocker_codes": [],
                "effective_speed_projected_row_missing_count": 0,
            },
            final_repeat_convergence_gate={
                "gate_passed": True,
                "blocker_codes": [],
                "detector_report_present": True,
                "dropped_cluster_count": 2,
                "dropped_segment_count": 1,
                "clusters_per_dropped_segment": {"4": ["a", "b"]},
            },
            visual_pacing_gate={
                "gate_passed": True,
                "visual_pacing_executed": True,
                "visual_merge_safety_gate_passed": True,
                "blocker_codes": [],
            },
            semantic_adjudication_gate=_semantic_gate_ok(),
            caption_alignment_gate={"gate_passed": True, "blocker_codes": []},
            ready_for_user_manual_qc_preconditions_passed=True,
        )

        self.assertTrue(quality["gate_passed"])
        self.assertEqual(quality["effective_speed_gate"]["effective_speed_projected_row_missing_count"], 0)
        self.assertTrue(quality["final_repeat_convergence_gate"]["detector_report_present"])
        self.assertEqual(quality["final_repeat_convergence_gate"]["dropped_segment_count"], 1)

    def test_ready_requires_final_repeat_convergence_gate(self) -> None:
        quality = build_quality_gate_report(
            final_repeat_convergence_gate={
                "gate_passed": False,
                "blocker_codes": ["V21_FINAL_REPEAT_UNRESOLVED_AFTER_CONVERGENCE"],
            }
        )

        self.assertFalse(quality["gate_passed"])
        self.assertIn("V21_FINAL_REPEAT_UNRESOLVED_AFTER_CONVERGENCE", quality["blocker_codes"])

    def test_quality_gate_blocks_final_repeat_detector_not_executed(self) -> None:
        quality = build_quality_gate_report(
            effective_speed_gate={"gate_passed": True, "blocker_codes": []},
            final_repeat_convergence_gate={
                "gate_passed": True,
                "blocker_codes": [],
                "detector_report_present": False,
            },
            visual_pacing_gate={
                "gate_passed": True,
                "visual_pacing_executed": True,
                "visual_merge_safety_gate_passed": True,
                "blocker_codes": [],
            },
            semantic_adjudication_gate=_semantic_gate_ok(),
            caption_alignment_gate={"gate_passed": True, "blocker_codes": []},
            ready_for_user_manual_qc_preconditions_passed=True,
        )

        self.assertFalse(quality["gate_passed"])
        self.assertIn("V21_FINAL_REPEAT_DETECTOR_REPORT_MISSING", quality["blocker_codes"])

    def test_ready_requires_visual_pacing_gate(self) -> None:
        quality = build_quality_gate_report(visual_pacing_gate={"gate_passed": False, "blocker_codes": ["V21_VISUAL_PACING_BLOCKED"]})

        self.assertFalse(quality["gate_passed"])
        self.assertIn("V21_VISUAL_PACING_BLOCKED", quality["blocker_codes"])

    def test_ready_requires_caption_alignment_gate(self) -> None:
        quality = build_quality_gate_report(caption_alignment_gate={"gate_passed": False, "blocker_codes": ["V21_CAPTION_OVERLAP"]})

        self.assertFalse(quality["gate_passed"])
        self.assertIn("V21_CAPTION_OVERLAP", quality["blocker_codes"])

    def test_quality_gate_report_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            with patch(
                "aroll_v21.operator.RealDraftIngestAdapter",
                lambda *a, **k: FakeAdapter(result=fake_real_draft_result(root=root)),
            ):
                summary = run_operator(ArollV21OperatorConfig(mode="dry-run", run_dir=root / "run", draft_dir=draft_dir))

            quality_path = root / "run" / "quality_gate_report.json"
            quality = json.loads(quality_path.read_text("utf-8"))
            self.assertTrue(quality_path.exists())
            self.assertEqual(summary["READY_FOR_DISPOSABLE_WRITE_PRE_AUDIT"], quality["gate_passed"])
            self.assertIn("effective_speed_gate", quality)
            self.assertIn("final_repeat_convergence_gate", quality)
            self.assertIn("visual_pacing_gate", quality)
            self.assertIn("caption_alignment_gate", quality)
            self.assertTrue(quality["post_write_actual_draft_audit_required_on_commit"])

    def test_commit_requires_post_write_actual_draft_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)

            writeback_result = _audit_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            self.assertTrue(writeback_result.report["post_write_actual_draft_audit_required_on_commit"])
            self.assertTrue(writeback_result.report["post_write_actual_draft_audit_executed"])
            self.assertTrue(writeback_result.report["post_write_actual_draft_audit_gate_passed"])

    def test_post_write_audit_blocks_when_actual_draft_missing(self) -> None:
        def unreadable_encrypt(_jy_draftc: Path, _plain: Path, encrypted_out: Path) -> None:
            encrypted_out.write_text("not json and not decryptable", "utf-8")

        def failing_decrypt(_jy_draftc: Path, _encrypted: Path, _decrypted: Path) -> None:
            raise RuntimeError("decrypt unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)

            writeback_result = _audit_writeback(unreadable_encrypt, failing_decrypt).commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertFalse(writeback_result.success)
            self.assertEqual(writeback_result.blockers[0].code, "V21_POST_WRITE_ACTUAL_DRAFT_AUDIT_FAILED")
            self.assertFalse(writeback_result.report["post_write_actual_draft_loaded"])
            self.assertFalse(writeback_result.report["ready_for_user_manual_qc"])

    def test_post_write_audit_blocks_when_actual_quality_differs_from_plan(self) -> None:
        def drift_encrypt(_jy_draftc: Path, plain: Path, encrypted_out: Path) -> None:
            data = json.loads(plain.read_text("utf-8"))
            video_track = next(track for track in data["tracks"] if track["id"] == "video_track")
            video_track["segments"][0]["source_timerange"]["duration"] += 250_000
            encrypted_out.write_text(json.dumps(data, ensure_ascii=False), "utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)

            writeback_result = _audit_writeback(drift_encrypt).commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertFalse(writeback_result.success)
            audit = writeback_result.report["post_write_actual_draft_audit"]
            self.assertFalse(audit["actual_video_rows_match_plan"])
            self.assertFalse(audit["actual_effective_speed_gate_passed"])
            self.assertIn("V21_POST_WRITE_ACTUAL_DRAFT_AUDIT_FAILED", audit["blocker_codes"])

    def test_post_write_audit_passes_when_actual_draft_matches_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)

            writeback_result = _audit_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            audit = writeback_result.report["post_write_actual_draft_audit"]
            self.assertTrue(audit["gate_passed"])
            self.assertTrue(audit["actual_video_rows_match_plan"])
            self.assertTrue(audit["actual_caption_rows_match_plan"])
            self.assertTrue(audit["actual_effective_speed_gate_passed"])
            self.assertTrue(writeback_result.report["ready_for_user_manual_qc"])

    def test_actual_text_residue_gate_blocks_old_subtitle_residue(self) -> None:
        def residue_encrypt(_jy_draftc: Path, plain: Path, encrypted_out: Path) -> None:
            data = json.loads(plain.read_text("utf-8"))
            _append_actual_text_segment(
                data,
                segment_id="old_caption_residue_segment",
                material_id="old_caption_residue_material",
                text="旧字幕残留",
                start_us=350_000,
                duration_us=100_000,
            )
            encrypted_out.write_text(json.dumps(data, ensure_ascii=False), "utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)

            writeback_result = _audit_writeback(residue_encrypt).commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            audit = writeback_result.report["post_write_actual_draft_audit"]
            self.assertFalse(writeback_result.success)
            self.assertFalse(audit["actual_text_residue_gate_passed"])
            self.assertEqual(audit["old_subtitle_residue_count"], 1)
            self.assertIn("actual_text_residue_gate_failed", [row["reason"] for row in audit["failure_reasons"]])

    def test_actual_text_residue_gate_blocks_text_after_final_video_end(self) -> None:
        def trailing_text_encrypt(_jy_draftc: Path, plain: Path, encrypted_out: Path) -> None:
            data = json.loads(plain.read_text("utf-8"))
            _append_actual_text_segment(
                data,
                segment_id="late_caption_residue_segment",
                material_id="late_caption_residue_material",
                text="拖尾旧字幕",
                start_us=900_000,
                duration_us=100_000,
            )
            encrypted_out.write_text(json.dumps(data, ensure_ascii=False), "utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)

            writeback_result = _audit_writeback(trailing_text_encrypt).commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            audit = writeback_result.report["post_write_actual_draft_audit"]
            self.assertFalse(writeback_result.success)
            self.assertFalse(audit["actual_text_residue_gate_passed"])
            self.assertEqual(audit["text_after_final_video_end_count"], 1)
            self.assertEqual(audit["orphan_text_segment_count"], 1)

    def test_post_write_audit_fails_when_extra_caption_like_text_segments_exist(self) -> None:
        def extra_caption_encrypt(_jy_draftc: Path, plain: Path, encrypted_out: Path) -> None:
            data = json.loads(plain.read_text("utf-8"))
            _append_actual_text_segment(
                data,
                segment_id="extra_caption_like_segment",
                material_id="extra_caption_like_material",
                text="额外字幕",
                start_us=420_000,
                duration_us=80_000,
            )
            encrypted_out.write_text(json.dumps(data, ensure_ascii=False), "utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)

            writeback_result = _audit_writeback(extra_caption_encrypt).commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            audit = writeback_result.report["post_write_actual_draft_audit"]
            self.assertFalse(writeback_result.success)
            self.assertFalse(audit["actual_has_no_extra_caption_like_text_segments"])
            self.assertFalse(writeback_result.report["writeback_success"])
            self.assertFalse(writeback_result.report["ready_for_user_manual_qc"])
            self.assertEqual(writeback_result.blockers[0].code, "V21_POST_WRITE_ACTUAL_DRAFT_AUDIT_FAILED")

    def test_actual_audio_coverage_gate_blocks_heard_but_uncaptioned_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)
            report = replace(report, captions=[replace(report.captions[0], word_ids=[])])

            writeback_result = _audit_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            audit = writeback_result.report["post_write_actual_draft_audit"]
            self.assertFalse(writeback_result.success)
            self.assertFalse(audit["actual_audio_coverage_gate_passed"])
            self.assertEqual(audit["audio_coverage_failure_count"], 1)
            self.assertEqual(audit["heard_but_uncaptioned_word_count"], 1)

    def test_audio_coverage_trim_or_blocks_heard_but_uncaptioned_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = _caption_trim_report(result)

            writeback_result = _audit_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            audit = writeback_result.report["post_write_actual_draft_audit"]
            self.assertTrue(audit["actual_audio_coverage_gate_passed"])
            self.assertEqual(audit["heard_but_uncaptioned_word_count"], 0)
            written = json.loads(draft_content.read_text("utf-8"))
            video_segment = next(track for track in written["tracks"] if track["id"] == "video_track")["segments"][0]
            self.assertEqual(video_segment["_v21_audio_coverage"]["source_start_us"], 500_000)
            self.assertEqual(video_segment["_v21_audio_coverage"]["source_end_us"], 800_000)

    def test_audio_coverage_blocks_dropped_but_reintroduced_words(self) -> None:
        def reintroducing_encrypt(_jy_draftc: Path, plain: Path, encrypted_out: Path) -> None:
            data = json.loads(plain.read_text("utf-8"))
            video_segment = next(track for track in data["tracks"] if track["id"] == "video_track")["segments"][0]
            video_segment["source_timerange"] = {"start": 100_000, "duration": 700_000}
            video_segment["_v21_audio_coverage"].update(
                {
                    "source_start_us": 100_000,
                    "source_end_us": 800_000,
                    "spoken_source_start_us": 100_000,
                    "spoken_source_end_us": 800_000,
                }
            )
            encrypted_out.write_text(json.dumps(data, ensure_ascii=False), "utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            before = draft_content.read_text("utf-8")
            result = fake_real_draft_result(root=root)
            report = _dropped_reintroduced_report(result)

            writeback_result = _audit_writeback(reintroducing_encrypt).commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            audit = writeback_result.report["post_write_actual_draft_audit"]
            self.assertFalse(writeback_result.success)
            self.assertFalse(audit["actual_audio_coverage_gate_passed"])
            self.assertEqual(audit["dropped_but_reintroduced_word_count"], 1)
            self.assertEqual(draft_content.read_text("utf-8"), before)

    def test_video_source_interval_cannot_include_uncaptioned_speech(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = _caption_trim_report(result)

            writeback_result = _audit_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            written = json.loads(draft_content.read_text("utf-8"))
            video_segments = next(track for track in written["tracks"] if track["id"] == "video_track")["segments"]
            self.assertEqual(len(video_segments), 1)
            coverage = video_segments[0]["_v21_audio_coverage"]
            self.assertFalse(coverage["source_start_us"] < 400_000 and coverage["source_end_us"] > 100_000)
            self.assertEqual(coverage["word_ids"], ["w_keep"])

    def test_single_dropped_word_at_boundary_is_trimmed_from_video_source_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = _caption_trim_report(result)

            writeback_result = _audit_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            written = json.loads(draft_content.read_text("utf-8"))
            video_segment = next(track for track in written["tracks"] if track["id"] == "video_track")["segments"][0]
            coverage = video_segment["_v21_audio_coverage"]
            self.assertEqual(coverage["source_start_us"], 500_000)
            self.assertEqual(coverage["source_end_us"], 800_000)
            self.assertEqual(coverage["word_ids"], ["w_keep"])

    def test_single_dropped_word_inside_segment_splits_video_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = _inside_dropped_report(result)

            writeback_result = _audit_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            written = json.loads(draft_content.read_text("utf-8"))
            video_segments = next(track for track in written["tracks"] if track["id"] == "video_track")["segments"]
            self.assertEqual(len(video_segments), 2)
            coverages = [segment["_v21_audio_coverage"] for segment in video_segments]
            self.assertEqual([(row["source_start_us"], row["source_end_us"]) for row in coverages], [(100_000, 300_000), (600_000, 800_000)])
            self.assertEqual([row["word_ids"] for row in coverages], [["w_before"], ["w_after"]])

    def test_video_write_plan_is_gapless_after_split_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = _inside_dropped_report(result)

            writeback_result = _audit_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            written = json.loads(draft_content.read_text("utf-8"))
            video_segments = next(track for track in written["tracks"] if track["id"] == "video_track")["segments"]
            self.assertEqual(
                [
                    (segment["target_timerange"]["start"], segment["target_timerange"]["duration"])
                    for segment in video_segments
                ],
                [(0, 200_000), (200_000, 200_000)],
            )
            self.assertTrue(writeback_result.report["gapless_video_write_plan_enabled"])
            self.assertEqual(writeback_result.report["gapless_final_video_end_us"], 400_000)

    def test_caption_times_repacked_after_video_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = _inside_dropped_report(result)

            writeback_result = _audit_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            written = json.loads(draft_content.read_text("utf-8"))
            text_segment = next(track for track in written["tracks"] if track["id"] == "text_track")["segments"][0]
            self.assertEqual(text_segment["target_timerange"], {"start": 0, "duration": 400_000})
            self.assertLessEqual(
                text_segment["target_timerange"]["start"] + text_segment["target_timerange"]["duration"],
                writeback_result.report["gapless_final_video_end_us"],
            )

    def test_caption_does_not_cross_split_video_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = _inside_dropped_report(result)

            writeback_result = _audit_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            audit = writeback_result.report["post_write_actual_draft_audit"]
            self.assertTrue(writeback_result.success)
            self.assertEqual(audit["post_write_video_target_gap_count_gt_300ms"], 0)
            self.assertEqual(audit["caption_crosses_video_split_gap_count"], 0)
            self.assertEqual(audit["split_caption_container_mismatch_count"], 0)

    def test_jianying_canonical_save_collapse_keeps_caption_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = _inside_dropped_report(result)

            writeback_result = _audit_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            audit = writeback_result.report["post_write_actual_draft_audit"]
            self.assertTrue(writeback_result.success)
            self.assertTrue(audit["jianying_canonical_timeline_sync_gate_passed"])
            self.assertEqual(audit["final_video_end_us"], 400_000)
            self.assertEqual(audit["max_caption_end_us"], 400_000)
            self.assertEqual(audit["captions_after_final_video_end_count"], 0)
            self.assertEqual(audit["caption_video_drift_count"], 0)
            self.assertEqual(audit["max_caption_video_drift_us"], 0)
            self.assertEqual(audit["caption_words_not_covered_by_actual_video_count"], 0)

    def test_captions_after_final_video_end_blocked(self) -> None:
        def late_caption_encrypt(_jy_draftc: Path, plain: Path, encrypted_out: Path) -> None:
            data = json.loads(plain.read_text("utf-8"))
            text_track = next(track for track in data["tracks"] if track["id"] == "text_track")
            text_track["segments"][0]["target_timerange"] = {"start": 900_000, "duration": 100_000}
            encrypted_out.write_text(json.dumps(data, ensure_ascii=False), "utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = _inside_dropped_report(result)

            writeback_result = _audit_writeback(late_caption_encrypt).commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            audit = writeback_result.report["post_write_actual_draft_audit"]
            self.assertFalse(writeback_result.success)
            self.assertGreater(audit["captions_after_final_video_end_count"], 0)
            self.assertFalse(audit["jianying_canonical_timeline_sync_gate_passed"])
            self.assertIn("V21_JIANYING_CANONICAL_TIMELINE_SYNC_FAILED", audit["blocker_codes"])

    def test_canonical_timeline_sync_gate_blocks_old_gap_based_plan(self) -> None:
        def old_gap_plan_encrypt(_jy_draftc: Path, plain: Path, encrypted_out: Path) -> None:
            data = json.loads(plain.read_text("utf-8"))
            video_track = next(track for track in data["tracks"] if track["id"] == "video_track")
            video_track["segments"][1]["target_timerange"]["start"] = 600_000
            encrypted_out.write_text(json.dumps(data, ensure_ascii=False), "utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = _inside_dropped_report(result)

            writeback_result = _audit_writeback(old_gap_plan_encrypt).commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            audit = writeback_result.report["post_write_actual_draft_audit"]
            self.assertFalse(writeback_result.success)
            self.assertFalse(audit["jianying_canonical_timeline_sync_gate_passed"])
            self.assertEqual(audit["post_write_video_target_gap_count_gt_300ms"], 1)
            self.assertEqual(audit["caption_crosses_video_split_gap_count"], 1)
            self.assertIn("V21_JIANYING_CANONICAL_TIMELINE_SYNC_FAILED", audit["blocker_codes"])

    def test_dropped_word_is_not_solved_by_caption_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = _inside_dropped_report(result)

            writeback_result = _audit_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            written = json.loads(draft_content.read_text("utf-8"))
            video_segments = next(track for track in written["tracks"] if track["id"] == "video_track")["segments"]
            self.assertNotIn("w_drop_inside", [word_id for segment in video_segments for word_id in segment["_v21_audio_coverage"]["word_ids"]])
            caption_material = written["materials"]["texts"][-1]
            self.assertNotIn("删掉", json.dumps(caption_material, ensure_ascii=False))

    def test_audio_coverage_zero_after_dropped_word_trim_or_split(self) -> None:
        for report_factory in (_caption_trim_report, _inside_dropped_report):
            with self.subTest(report_factory=report_factory.__name__), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                draft_dir, _draft_content, _template = create_disposable_draft(root)
                result = fake_real_draft_result(root=root)
                report = report_factory(result)

                writeback_result = _audit_writeback().commit(
                    draft_dir=draft_dir,
                    run_dir=root / "run",
                    real_draft_result=result,
                    run_report=report,
                    sacrificial_write_override_used=True,
                )

                audit = writeback_result.report["post_write_actual_draft_audit"]
                self.assertTrue(writeback_result.success)
                self.assertTrue(audit["actual_audio_coverage_gate_passed"])
                self.assertEqual(audit["audio_coverage_failure_count"], 0)
                self.assertEqual(audit["heard_but_uncaptioned_word_count"], 0)
                self.assertEqual(audit["dropped_but_reintroduced_word_count"], 0)

    def test_audio_coverage_allows_explicit_silence_or_handle_gap_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)
            tail_word = replace(
                report.source_graph.words[0],
                word_id="w_tail_handle",
                text="尾声",
                normalized_text="尾声",
                source_start_us=450_000,
                source_end_us=500_000,
            )
            report = replace(report, source_graph=replace(report.source_graph, words=[*report.source_graph.words, tail_word]))

            writeback_result = _audit_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            audit = writeback_result.report["post_write_actual_draft_audit"]
            self.assertTrue(writeback_result.success)
            self.assertTrue(audit["actual_audio_coverage_gate_passed"])
            self.assertEqual(audit["heard_but_uncaptioned_word_count"], 0)
            self.assertEqual(audit["actual_audio_coverage_report"]["allowed_handle_gap_word_count"], 0)

    def test_actual_visible_text_repeat_gate_scans_residue_text_segments(self) -> None:
        def repeat_residue_encrypt(_jy_draftc: Path, plain: Path, encrypted_out: Path) -> None:
            data = json.loads(plain.read_text("utf-8"))
            _append_actual_text_segment(
                data,
                segment_id="repeat_residue_segment",
                material_id="repeat_residue_material",
                text="测试",
                start_us=350_000,
                duration_us=100_000,
            )
            encrypted_out.write_text(json.dumps(data, ensure_ascii=False), "utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)

            writeback_result = _audit_writeback(repeat_residue_encrypt).commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            audit = writeback_result.report["post_write_actual_draft_audit"]
            self.assertFalse(writeback_result.success)
            self.assertFalse(audit["actual_visible_text_repeat_gate_passed"])
            self.assertGreater(audit["actual_visible_repeat_candidate_count"], 0)

    def test_actual_caption_rows_exact_match_requires_no_extras(self) -> None:
        def exact_match_extra_encrypt(_jy_draftc: Path, plain: Path, encrypted_out: Path) -> None:
            data = json.loads(plain.read_text("utf-8"))
            _append_actual_text_segment(
                data,
                segment_id="exact_match_extra_segment",
                material_id="exact_match_extra_material",
                text="多余字幕",
                start_us=360_000,
                duration_us=100_000,
            )
            encrypted_out.write_text(json.dumps(data, ensure_ascii=False), "utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)

            writeback_result = _audit_writeback(exact_match_extra_encrypt).commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            audit = writeback_result.report["post_write_actual_draft_audit"]
            self.assertFalse(writeback_result.success)
            self.assertTrue(audit["expected_caption_rows_present"])
            self.assertFalse(audit["actual_caption_rows_exact_match_plan"])
            self.assertFalse(audit["actual_caption_rows_match_plan"])

    def test_writeback_audit_failure_rolls_back_target_files(self) -> None:
        original_copyfile = real_writeback_module.shutil.copyfile

        def tampering_copyfile(src: Path, dst: Path) -> str:
            src_path = Path(src)
            dst_path = Path(dst)
            if src_path.name == "draft_content.v21.modified.enc.json" and dst_path.name == "draft_content.json":
                data = json.loads(src_path.read_text("utf-8"))
                _append_actual_text_segment(
                    data,
                    segment_id="post_copy_residue_segment",
                    material_id="post_copy_residue_material",
                    text="复制后污染字幕",
                    start_us=350_000,
                    duration_us=100_000,
                )
                dst_path.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
                return str(dst_path)
            return original_copyfile(src_path, dst_path)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, template = create_disposable_draft(root)
            before_draft = draft_content.read_text("utf-8")
            before_template = template.read_text("utf-8")
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)

            with patch("aroll_v21.writeback.real_draft_writeback.shutil.copyfile", side_effect=tampering_copyfile):
                writeback_result = _audit_writeback().commit(
                    draft_dir=draft_dir,
                    run_dir=root / "run",
                    real_draft_result=result,
                    run_report=report,
                    sacrificial_write_override_used=True,
                )

            self.assertFalse(writeback_result.success)
            self.assertFalse(writeback_result.report["commit_performed"])
            self.assertFalse(writeback_result.report["WRITE_SUCCESS"])
            self.assertTrue(writeback_result.report["rollback_performed"])
            self.assertTrue(writeback_result.report["rollback_success"])
            self.assertEqual(draft_content.read_text("utf-8"), before_draft)
            self.assertEqual(template.read_text("utf-8"), before_template)

    def test_commit_performed_false_means_no_persistent_target_write(self) -> None:
        def bad_staged_encrypt(_jy_draftc: Path, plain: Path, encrypted_out: Path) -> None:
            data = json.loads(plain.read_text("utf-8"))
            _append_actual_text_segment(
                data,
                segment_id="staged_residue_segment",
                material_id="staged_residue_material",
                text="预审污染字幕",
                start_us=350_000,
                duration_us=100_000,
            )
            encrypted_out.write_text(json.dumps(data, ensure_ascii=False), "utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, template = create_disposable_draft(root)
            before_draft = draft_content.read_text("utf-8")
            before_template = template.read_text("utf-8")
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)

            writeback_result = _audit_writeback(bad_staged_encrypt).commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertFalse(writeback_result.success)
            self.assertFalse(writeback_result.report["commit_performed"])
            self.assertFalse(writeback_result.report["WRITE_SUCCESS"])
            self.assertTrue(all(value is False for value in writeback_result.report["target_writes"].values()))
            self.assertEqual(draft_content.read_text("utf-8"), before_draft)
            self.assertEqual(template.read_text("utf-8"), before_template)

    def test_ready_for_user_manual_qc_false_when_post_write_audit_failed(self) -> None:
        def drift_encrypt(_jy_draftc: Path, plain: Path, encrypted_out: Path) -> None:
            data = json.loads(plain.read_text("utf-8"))
            video_track = next(track for track in data["tracks"] if track["id"] == "video_track")
            video_track["segments"][0]["target_timerange"]["duration"] += 250_000
            encrypted_out.write_text(json.dumps(data, ensure_ascii=False), "utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)

            writeback_result = _audit_writeback(drift_encrypt).commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertFalse(writeback_result.success)
            self.assertFalse(writeback_result.report["ready_for_user_manual_qc"])
            self.assertFalse(writeback_result.report["writeback_success"])

    def test_caption_no_overlap_after_video_merge(self) -> None:
        segment = replace(_segment(1, 0, 1_200_000), word_ids=["w1", "w2"])
        report = build_caption_alignment_report(
            final_timeline=[segment],
            captions=[
                _caption(1, "v21_seg_000001", 0, 500_000),
                _caption(2, "v21_seg_000001", 500_000, 1_000_000),
            ],
        )

        self.assertTrue(report["gate_passed"])
        self.assertEqual(report["caption_overlap_count"], 0)

    def test_caption_count_can_exceed_video_segment_count(self) -> None:
        segment = replace(_segment(1, 0, 1_200_000), word_ids=["w1", "w2"])
        visual = build_visual_pacing_report(
            final_timeline=[segment],
            captions=[
                _caption(1, "v21_seg_000001", 0, 500_000),
                _caption(2, "v21_seg_000001", 500_000, 1_000_000),
            ],
            executed=True,
            merge_report={
                "visual_pacing_executed": True,
                "visual_pacing_merge_attempted_count": 0,
                "visual_pacing_merged_count": 0,
                "visual_short_segment_count_lt_1200ms_before": 0,
                "visual_short_segment_count_lt_1200ms_after": 0,
                "semantic_bridge_short_segment_count": 0,
                "visual_pacing_blocker_codes": [],
            },
        )
        alignment = build_caption_alignment_report(
            final_timeline=[segment],
            captions=[
                _caption(1, "v21_seg_000001", 0, 500_000),
                _caption(2, "v21_seg_000001", 500_000, 1_000_000),
            ],
        )

        self.assertEqual(visual["final_video_segment_count"], 1)
        self.assertEqual(visual["caption_count"], 2)
        self.assertTrue(alignment["gate_passed"])

    def test_too_short_caption_merges_with_neighbor(self) -> None:
        source_graph = _graph_for_visual_merge_rows(
            [
                ("w001", "就", 0, 240_000),
                ("w002", "继续", 300_000, 700_000),
            ]
        )
        segment = replace(_segment(1, 0, 900_000), source_end_us=900_000, word_ids=["w001", "w002"], text="就继续")

        captions = SubtitleRenderer().render([segment], source_graph)
        alignment = build_caption_alignment_report(final_timeline=[segment], captions=captions)

        self.assertEqual(len(captions), 1)
        self.assertEqual(captions[0].text, "就继续")
        self.assertEqual(alignment["caption_too_short_count"], 0)
        self.assertEqual(alignment["one_char_caption_count"], 0)

    def test_too_short_caption_extends_inside_containing_video_when_safe(self) -> None:
        segment = replace(_segment(1, 0, 600_000), word_ids=["w1"], text="短语")
        captions = [
            replace(
                _caption(1, "v21_seg_000001", 100_000, 250_000, text="短语"),
                containing_video_segment_id="v21_seg_000001",
            )
        ]

        cleaned = _cleanup_caption_units(captions, {"v21_seg_000001": segment})

        self.assertEqual(cleaned[0].target_start_us, 100_000)
        self.assertEqual(cleaned[0].target_end_us, 600_000)

    def test_one_char_caption_merges_with_neighbor(self) -> None:
        source_graph = _graph_for_visual_merge_rows(
            [
                ("w001", "就", 0, 240_000),
                ("w002", "继续", 300_000, 700_000),
            ]
        )
        segment = replace(_segment(1, 0, 900_000), source_end_us=900_000, word_ids=["w001", "w002"], text="就继续")

        captions = SubtitleRenderer().render([segment], source_graph)

        self.assertEqual(len(captions), 1)
        self.assertGreater(len(captions[0].text), 1)

    def test_one_char_caption_count_zero_after_cleanup(self) -> None:
        source_graph = _graph_for_visual_merge_rows(
            [
                ("w001", "就", 0, 240_000),
                ("w002", "继续", 300_000, 700_000),
            ]
        )
        segment = replace(_segment(1, 0, 900_000), source_end_us=900_000, word_ids=["w001", "w002"], text="就继续")
        captions = SubtitleRenderer().render([segment], source_graph)
        report = build_caption_alignment_report(final_timeline=[segment], captions=captions)

        self.assertEqual(report["one_char_caption_count"], 0)
        self.assertEqual(report["residual_one_char_captions"], [])

    def test_visual_pacing_gate_allows_only_explicit_semantic_bridge_exceptions(self) -> None:
        allowed = build_visual_pacing_report(
            final_timeline=[replace(_segment(1, 0, 700_000), text="语义桥")],
            captions=[],
            executed=True,
            merge_report={"visual_pacing_executed": True},
        )
        blocked = build_visual_pacing_report(
            final_timeline=[
                replace(_segment(1, 0, 500_000), text="交配权"),
                replace(_segment(2, 500_000, 1_000_000), text="交配权"),
                replace(_segment(3, 1_000_000, 1_500_000), text="交配权"),
                replace(_segment(4, 1_500_000, 2_000_000), text="交配权"),
            ],
            captions=[],
            executed=True,
            merge_report={"visual_pacing_executed": True},
        )

        self.assertTrue(allowed["gate_passed"])
        self.assertEqual(allowed["visual_short_segment_count_lt_1200ms_after_blocking"], 0)
        self.assertEqual(allowed["semantic_bridge_reason_counts"], {"semantic_bridge_exception": 1})
        self.assertEqual(allowed["semantic_bridge_short_segment_details"][0]["text"], "语义桥")
        self.assertFalse(blocked["gate_passed"])
        self.assertEqual(blocked["visual_short_segment_count_lt_1200ms_after_blocking"], 4)

    def test_semantic_bridge_count_cap_blocks_abuse(self) -> None:
        timeline = [
            replace(_segment(index, (index - 1) * 700_000, index * 700_000), text=f"语义桥{index}")
            for index in range(1, 10)
        ]

        report = build_visual_pacing_report(
            final_timeline=timeline,
            captions=[],
            executed=True,
            merge_report={"visual_pacing_executed": True},
        )

        self.assertFalse(report["gate_passed"])
        self.assertEqual(report["semantic_bridge_short_segment_count"], 9)
        self.assertEqual(report["semantic_bridge_cap"], 8)
        self.assertIn("V21_VISUAL_SEMANTIC_BRIDGE_ABUSE", report["blocker_codes"])

    def test_cut_density_gate_blocks_bursty_timeline(self) -> None:
        timeline = [
            replace(_segment(index, (index - 1) * 1_200_000, index * 1_200_000), text=f"长段{index}")
            for index in range(1, 13)
        ]

        report = build_visual_pacing_report(
            final_timeline=timeline,
            captions=[],
            executed=True,
            merge_report={"visual_pacing_executed": True},
        )

        self.assertFalse(report["gate_passed"])
        self.assertGreater(report["cuts_per_minute"], report["cut_density_thresholds"]["max_cuts_per_minute"])
        self.assertIn("V21_VISUAL_CUT_DENSITY_FAILED", report["blocker_codes"])

    def test_semantic_bridge_requires_reason_details(self) -> None:
        report = build_visual_pacing_report(
            final_timeline=[replace(_segment(1, 0, 700_000), text="语义桥")],
            captions=[],
            executed=True,
            merge_report={"visual_pacing_executed": True},
        )

        detail = report["semantic_bridge_short_segment_details"][0]
        self.assertEqual(detail["semantic_bridge_reason"], "semantic_bridge_exception")
        self.assertEqual(detail["text"], "语义桥")
        self.assertEqual(detail["duration_us"], 700_000)
        self.assertEqual(detail["why_not_merge"], ["semantic_bridge_exception_preserved"])

    def test_weak_filler_cannot_be_semantic_bridge(self) -> None:
        report = build_visual_pacing_report(
            final_timeline=[replace(_segment(1, 0, 700_000), text="然后")],
            captions=[],
            executed=True,
            merge_report={"visual_pacing_executed": True},
        )

        self.assertEqual(report["semantic_bridge_short_segment_count"], 0)
        self.assertEqual(report["semantic_bridge_short_segment_details"], [])
        self.assertFalse(report["residual_visual_short_segments"][0]["semantic_bridge"])
        self.assertTrue(report["residual_visual_short_segments"][0]["weak_filler"])

    def test_safe_merge_candidate_is_merged_not_reported_as_semantic_bridge(self) -> None:
        materials, text_segments = _template_rows()
        source_graph = ArollEngine().ingest.build_source_graph(
            word_timeline=[
                {
                    "word_id": "w001",
                    "word_text": "语义桥",
                    "start_us": 0,
                    "end_us": 700_000,
                    "subtitle_index": 1,
                    "subtitle_uid": "s001",
                },
                {
                    "word_id": "w002",
                    "word_text": "继续内容",
                    "start_us": 700_000,
                    "end_us": 2_000_000,
                    "subtitle_index": 1,
                    "subtitle_uid": "s001",
                },
            ],
            subtitles=[
                {
                    "subtitle_uid": "s001",
                    "subtitle_index": 1,
                    "text": "语义桥继续内容",
                    "word_ids": ["w001", "w002"],
                }
            ],
            source_segments=[
                {
                    "id": "primary_window",
                    "material_id": "main",
                    "type": "video",
                    "source_start_us": 0,
                    "source_end_us": 2_000_000,
                }
            ],
            text_materials=materials,
            text_segments=text_segments,
        )
        timeline = [
            replace(_segment(1, 0, 700_000), source_end_us=700_000, word_ids=["w001"], text="语义桥"),
            replace(
                _segment(2, 700_000, 2_000_000),
                source_start_us=700_000,
                source_end_us=2_000_000,
                word_ids=["w002"],
                text="继续内容",
            ),
        ]

        normalized, report = VisualPacingNormalizer().normalize(timeline, source_graph)

        self.assertTrue(report["gate_passed"])
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0].text, "语义桥继续内容")
        self.assertEqual(report["semantic_bridge_safe_merge_candidate_count"], 0)
        self.assertEqual(report["semantic_bridge_short_segment_details"], [])

    def test_video_segments_can_be_fewer_than_captions_in_main_chain(self) -> None:
        result = _multi_caption_fake_result()
        report = ArollEngine().run(
            ArollRunInput(
                mode="write",
                draft_data=result.draft_data,
                word_timeline=result.word_timeline,
                subtitles=result.subtitles,
                source_segments=result.source_segments,
                source_materials=result.source_materials,
                text_materials=result.text_materials,
                text_segments=result.text_segments,
                postwrite_mode="simulated",
            )
        )

        self.assertEqual(report.status, "ok")
        self.assertLess(len(report.final_timeline), len(report.captions))
        self.assertGreater(report.validator_report["visual_pacing_gate"]["caption_per_video_segment_ratio"], 1.0)

    def test_caption_timeline_can_contain_multiple_captions_inside_one_video_segment(self) -> None:
        result = _multi_caption_fake_result()
        report = ArollEngine().run(
            ArollRunInput(
                mode="write",
                draft_data=result.draft_data,
                word_timeline=result.word_timeline,
                subtitles=result.subtitles,
                source_segments=result.source_segments,
                source_materials=result.source_materials,
                text_materials=result.text_materials,
                text_segments=result.text_segments,
                postwrite_mode="simulated",
            )
        )

        self.assertEqual(len(report.final_timeline), 1)
        self.assertGreater(len(report.captions), 1)
        self.assertTrue(all(caption.containing_video_segment_id == report.final_timeline[0].segment_id for caption in report.captions))
        self.assertTrue(all(report.final_timeline[0].target_start_us <= caption.target_start_us <= caption.target_end_us <= report.final_timeline[0].target_end_us for caption in report.captions))

    def test_resolved_template_map_count_matches_video_segment_count_not_caption_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = _multi_caption_fake_result(root=root)
            report = ArollEngine().run(
                ArollRunInput(
                    mode="write",
                    draft_data=result.draft_data,
                    word_timeline=result.word_timeline,
                    subtitles=result.subtitles,
                    source_segments=result.source_segments,
                    source_materials=result.source_materials,
                    text_materials=result.text_materials,
                    text_segments=result.text_segments,
                    postwrite_mode="simulated",
                )
            )

            preflight = DynamicSourceBindingPreflight(root_mirror_func=fake_root_mirror_not_required).preflight(
                draft_dir=draft_dir,
                real_draft_result=result,
                run_report=report,
                run_dir=root / "run",
            )

            self.assertTrue(preflight.success)
            self.assertEqual(preflight.report["resolved_template_map_count"], len(report.final_timeline))
            self.assertNotEqual(preflight.report["resolved_template_map_count"], len(report.captions))


if __name__ == "__main__":
    unittest.main()
