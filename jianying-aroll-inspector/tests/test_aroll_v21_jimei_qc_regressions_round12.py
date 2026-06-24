from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput
from aroll_v21.compiler import RoughCutQualityNormalizer
from aroll_v21.ir.models import (
    CanonicalSourceGraph,
    CanonicalWord,
    CaptionRenderUnit,
    DecisionPlan,
    FinalTimelineSegment,
    SourceGraphInvariantReport,
)
from aroll_v21.quality.final_caption_visible_repeat import build_final_caption_visible_repeat_gate
from aroll_v21.quality.final_visible_caption_repair import repair_final_visible_caption_issues
from aroll_v21.quality.visual_pacing.normalizer import VisualPacingNormalizer
from aroll_v21.render.subtitle_renderer import SubtitleRenderer


ROOT = Path(__file__).resolve().parents[1]


def _caption(index: int, text: str, start_us: int = 0, end_us: int | None = None) -> CaptionRenderUnit:
    end = end_us if end_us is not None else start_us + max(300_000, len(text) * 80_000)
    return CaptionRenderUnit(
        caption_id=f"v21_cap_{index:06d}",
        timeline_segment_ids=[f"v21_seg_{index:06d}"],
        word_ids=[f"w{index:03d}"],
        text=text,
        target_start_us=start_us,
        target_end_us=end,
        source_subtitle_uids=[f"s{index:03d}"],
        style_template_id="canonical_caption_template",
        containing_video_segment_id=f"v21_seg_{index:06d}",
    )


def _word(word_id: str, text: str, start_us: int, end_us: int, subtitle_index: int) -> CanonicalWord:
    return CanonicalWord(
        word_id=word_id,
        text=text,
        normalized_text=text,
        source_start_us=start_us,
        source_end_us=end_us,
        source_material_id="main",
        source_segment_id="clip_1",
        subtitle_uid=f"s{subtitle_index:03d}",
        subtitle_index=subtitle_index,
        char_start=None,
        char_end=None,
        confidence=None,
        is_cuttable_left=True,
        is_cuttable_right=True,
    )


def _graph(words: list[CanonicalWord], source_end_us: int | None = None) -> CanonicalSourceGraph:
    end_us = source_end_us if source_end_us is not None else max((word.source_end_us for word in words), default=0) + 500_000
    return CanonicalSourceGraph(
        words=words,
        edit_units=[],
        subtitle_rows=[],
        source_materials=[{"source_material_id": "main", "type": "video", "duration_us": end_us}],
        source_segments=[{"id": "clip_1", "material_id": "main", "type": "video", "source_start_us": 0, "source_end_us": end_us}],
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


def _segment(index: int, word_ids: list[str], text: str, start_us: int, end_us: int) -> FinalTimelineSegment:
    return FinalTimelineSegment(
        segment_id=f"v21_seg_{index:06d}",
        source_material_id="main",
        source_segment_id="clip_1",
        source_start_us=start_us,
        source_end_us=end_us,
        target_start_us=start_us,
        target_end_us=end_us,
        word_ids=word_ids,
        text=text,
        decision_ids=[],
    )


def _repair(timeline: list[FinalTimelineSegment], graph: CanonicalSourceGraph):
    renderer = SubtitleRenderer()
    captions = renderer.render(timeline, graph)
    return repair_final_visible_caption_issues(
        final_timeline=timeline,
        captions=captions,
        source_graph=graph,
        render_captions=lambda current: renderer.render(current, graph),
    )


def _run_text(text: str) -> object:
    payload = json.loads((ROOT / "fixtures" / "real_materials" / "normal_caption_template.json").read_text("utf-8"))
    return ArollEngine().run(
        ArollRunInput(
            source_segments=[{"id": "clip_1", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1_000_000}],
            word_timeline=[
                {"word_id": "w1", "word_text": text, "start_us": 0, "end_us": 1_000_000, "subtitle_uid": "s1", "subtitle_index": 1}
            ],
            subtitles=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": text, "word_ids": ["w1"]}],
            text_materials=[payload["material"]],
            text_segments=[payload["segment"]],
        )
    )


class ArollV21JimeiQcRound12Regressions(unittest.TestCase):
    def test_q01_opening_vocalization_residual_is_dropped(self) -> None:
        graph = _graph(
            [
                _word("w001", "嗯啊", 0, 700_000, 1),
                _word("w002", "后面完整内容", 1_200_000, 2_200_000, 2),
            ]
        )
        result = _repair([
            _segment(1, ["w001"], "嗯啊", 0, 700_000),
            _segment(2, ["w002"], "后面完整内容", 1_200_000, 2_200_000),
        ], graph)

        self.assertEqual("".join(caption.text for caption in result.captions), "后面完整内容")
        self.assertTrue(result.report["final_visible_repair_success"], result.report)

    def test_q02_dense_subthreshold_breath_gaps_are_split(self) -> None:
        words = [
            _word("w001", "第一句", 0, 600_000, 1),
            _word("w002", "第二句", 800_000, 1_400_000, 1),
            _word("w003", "第三句", 1_610_000, 2_210_000, 1),
            _word("w004", "第四句", 2_440_000, 3_040_000, 1),
            _word("w005", "第五句", 3_260_000, 3_860_000, 1),
        ]
        graph = _graph(words, 4_200_000)
        normalized, visual = VisualPacingNormalizer().normalize(
            [_segment(1, [word.word_id for word in words], "第一句第二句第三句第四句第五句", 0, 3_860_000)],
            graph,
        )

        self.assertGreaterEqual(len(normalized), 4)
        self.assertGreaterEqual(visual["large_intra_segment_gap_split_count"], 3)
        self.assertIn("dense_intra_segment_gap_split", {row["reason"] for row in visual["large_intra_segment_gap_candidates"]})

    def test_q03_device_prompt_text_blocks_final_gate(self) -> None:
        gate = build_final_caption_visible_repeat_gate([_caption(1, "配置模式请断电重启设备", 0, 1_000_000)])

        self.assertFalse(gate["gate_passed"])
        self.assertIn("V21_FINAL_SEMANTIC_INTEGRITY_GATE_FAILED", gate["blocker_codes"])
        self.assertEqual(gate["semantic_integrity_reason_counts"]["non_primary_device_prompt_residual"], 1)

    def test_q04_device_prompt_between_content_is_removed_without_joining_wrong_clause(self) -> None:
        graph = _graph(
            [
                _word("w001", "想要资源", 0, 700_000, 1),
                _word("w002", "配置模式请断电重启设备", 1_000_000, 2_000_000, 2),
                _word("w003", "阶层跃迁", 2_300_000, 3_000_000, 3),
            ]
        )
        result = _repair([
            _segment(1, ["w001"], "想要资源", 0, 700_000),
            _segment(2, ["w002"], "配置模式请断电重启设备", 1_000_000, 2_000_000),
            _segment(3, ["w003"], "阶层跃迁", 2_300_000, 3_000_000),
        ], graph)

        visible = "".join(caption.text for caption in result.captions)
        self.assertNotIn("断电重启", visible)
        self.assertIn("想要资源", visible)
        self.assertIn("阶层跃迁", visible)

    def test_q05_short_abandoned_open_clause_blocks_final_gate(self) -> None:
        gate = build_final_caption_visible_repeat_gate([_caption(1, "她这副是", 0, 600_000), _caption(2, "后面重新开始", 700_000, 1_500_000)])

        self.assertFalse(gate["gate_passed"])
        self.assertEqual(gate["semantic_integrity_reason_counts"]["short_abandoned_open_clause"], 1)

    def test_q06_action_aspect_fragment_before_object_head_is_not_dropped_as_junk(self) -> None:
        graph = _graph(
            [
                _word("w001", "前面完整内容", 0, 1_000_000, 1),
                _word("w002", "抱着", 1_500_000, 2_000_000, 2),
                _word("w003", "个破游戏就当享受了", 2_400_000, 3_600_000, 3),
            ]
        )
        result = _repair([
            _segment(1, ["w001"], "前面完整内容", 0, 1_000_000),
            _segment(2, ["w002"], "抱着", 1_500_000, 2_000_000),
            _segment(3, ["w003"], "个破游戏就当享受了", 2_400_000, 3_600_000),
        ], graph)

        self.assertIn("抱着个破游戏", "".join(caption.text for caption in result.captions))

    def test_q06_contextual_classifier_head_is_allowed_when_previous_caption_supplies_verb(self) -> None:
        gate = build_final_caption_visible_repeat_gate(
            [
                _caption(1, "抱着", 1_500_000, 2_000_000),
                _caption(2, "个破游戏就当享受了", 2_240_000, 3_600_000),
            ]
        )

        self.assertTrue(gate["gate_passed"], gate)
        self.assertEqual(gate["semantic_integrity_count"], 0)

    def test_q06_visual_pacing_merges_action_head_across_redundant_restart_gap(self) -> None:
        words = [
            _word("w001", "抱着", 0, 320_000, 1),
            _word("w002", "个", 320_000, 480_000, 1),
            _word("w003", "破", 480_000, 600_000, 1),
            _word("w004", "游戏", 600_000, 820_000, 1),
            _word("w005", "就", 820_000, 960_000, 1),
            _word("w006", "抱着", 1_200_000, 1_480_000, 1),
            _word("w007", "个", 1_480_000, 1_620_000, 2),
            _word("w008", "破", 1_620_000, 1_760_000, 2),
            _word("w009", "游戏", 1_760_000, 2_000_000, 2),
            _word("w010", "就", 2_000_000, 2_160_000, 2),
            _word("w011", "当", 2_160_000, 2_320_000, 2),
            _word("w012", "享受", 2_320_000, 2_700_000, 2),
            _word("w013", "了", 2_700_000, 3_000_000, 2),
        ]
        normalized, visual = VisualPacingNormalizer().normalize(
            [
                _segment(1, ["w001"], "抱着", 0, 320_000),
                _segment(2, ["w007", "w008", "w009", "w010", "w011", "w012", "w013"], "个破游戏就当享受了", 1_480_000, 3_000_000),
            ],
            _graph(words, 3_400_000),
        )

        self.assertEqual([segment.text for segment in normalized], ["抱着", "个破游戏就当享受了"])
        self.assertTrue(visual["gate_passed"], visual)
        self.assertEqual(visual["visual_pacing_merged_count"], 1)
        self.assertGreaterEqual(visual["large_intra_segment_gap_split_count"], 1)
        self.assertTrue(all(int(segment.source_end_us) - int(segment.source_start_us) < 2_000_000 for segment in normalized))
        self.assertEqual(visual["visual_short_segment_count_lt_1200ms_after_blocking"], 0)
        self.assertEqual(visual["unsafe_merge_group_count"], 0)

    def test_q06_visual_pacing_deduplicates_child_records_before_merge_safety(self) -> None:
        graph = _graph(
            [
                _word("w001", "第一段", 0, 500_000, 1),
                _word("w002", "第二段", 580_000, 1_000_000, 2),
            ],
            1_200_000,
        )
        segment = replace(
            _segment(1, ["w001", "w002"], "第一段第二段", 0, 1_000_000),
            debug_hints={
                "visual_pacing_child_segments": [
                    {"segment_id": "child_1", "source_start_us": 0, "source_end_us": 500_000, "target_start_us": 0, "target_end_us": 500_000, "word_ids": ["w001"]},
                    {"segment_id": "child_1", "source_start_us": 0, "source_end_us": 500_000, "target_start_us": 0, "target_end_us": 500_000, "word_ids": ["w001"]},
                    {"segment_id": "child_2", "source_start_us": 580_000, "source_end_us": 1_000_000, "target_start_us": 500_000, "target_end_us": 1_000_000, "word_ids": ["w002"]},
                    {"segment_id": "child_2", "source_start_us": 580_000, "source_end_us": 1_000_000, "target_start_us": 500_000, "target_end_us": 1_000_000, "word_ids": ["w002"]},
                ]
            },
        )

        _normalized, visual = VisualPacingNormalizer().normalize([segment], graph)

        self.assertTrue(visual["visual_merge_safety_gate_passed"], visual["visual_merge_groups"])
        self.assertEqual(visual["unsafe_merge_group_count"], 0)
        self.assertEqual(visual["visual_merge_groups"][0]["child_segment_ids"], ["child_1", "child_2"])

    def test_q07_non_opening_content_segment_gets_adaptive_lead_handle(self) -> None:
        words = [
            _word("w001", "前面完整内容", 0, 900_000, 1),
            _word("w002", "美其名曰为未来存钱", 2_000_000, 3_000_000, 2),
        ]
        normalized, blockers = RoughCutQualityNormalizer().normalize(
            [
                _segment(1, ["w001"], "前面完整内容", 0, 900_000),
                _segment(2, ["w002"], "美其名曰为未来存钱", 2_000_000, 3_000_000),
            ],
            _graph(words, 3_500_000),
            DecisionPlan(decisions=[]),
        )

        self.assertEqual(blockers, [])
        self.assertEqual(normalized[0].lead_handle_us, 0)
        self.assertEqual(normalized[1].lead_handle_us, 320_000)
        self.assertTrue(normalized[1].debug_hints["safe_handle_adaptive_content_lead_enabled"])

    def test_q08_repeated_interjection_tail_is_trimmed_to_one(self) -> None:
        graph = _graph(
            [
                _word("w001", "结果到了结婚的时候", 0, 1_000_000, 1),
                _word("w002", "哦", 1_000_000, 1_120_000, 1),
                _word("w003", "哦", 1_120_000, 1_240_000, 1),
            ]
        )
        result = _repair([_segment(1, ["w001", "w002", "w003"], "结果到了结婚的时候哦哦", 0, 1_240_000)], graph)

        self.assertEqual("".join(caption.text for caption in result.captions), "结果到了结婚的时候哦")

    def test_q08_fused_repeated_interjection_word_is_removed_when_it_cannot_be_split(self) -> None:
        graph = _graph(
            [
                _word("w001", "结果到了结婚的时候", 0, 1_000_000, 1),
                _word("w002", "哦哦", 1_000_000, 1_600_000, 1),
            ]
        )
        result = _repair([_segment(1, ["w001", "w002"], "结果到了结婚的时候哦哦", 0, 1_600_000)], graph)

        self.assertTrue(result.report["final_visible_repair_success"], result.report)
        self.assertEqual("".join(caption.text for caption in result.captions), "结果到了结婚的时候")

    def test_q09_single_char_false_start_after_price_context_is_trimmed(self) -> None:
        graph = _graph(
            [
                _word("w001", "3000块的水光针", 0, 900_000, 1),
                _word("w002", "大", 900_000, 1_000_000, 1),
            ]
        )
        result = _repair([_segment(1, ["w001", "w002"], "3000块的水光针大", 0, 1_000_000)], graph)

        self.assertEqual("".join(caption.text for caption in result.captions), "3000块的水光针")

    def test_q10_truncated_single_word_prefix_tail_blocks_final_gate(self) -> None:
        gate = build_final_caption_visible_repeat_gate([_caption(1, "一节课600块钱的普", 0, 1_000_000)])

        self.assertFalse(gate["gate_passed"])
        self.assertEqual(gate["semantic_integrity_reason_counts"]["truncated_nominal_prefix_tail"], 1)

    def test_q10_truncated_nominal_tail_repair_drops_de_plus_single_tail(self) -> None:
        graph = _graph(
            [
                _word("w001", "一节课600块钱", 0, 800_000, 1),
                _word("w002", "的", 800_000, 920_000, 1),
                _word("w003", "普", 920_000, 1_200_000, 1),
            ]
        )
        result = _repair([_segment(1, ["w001", "w002", "w003"], "一节课600块钱的普", 0, 1_200_000)], graph)

        self.assertTrue(result.report["final_visible_repair_success"], result.report)
        self.assertEqual("".join(caption.text for caption in result.captions), "一节课600块钱")

    def test_q10_common_nominal_tail_without_amount_context_is_not_blocked(self) -> None:
        gate = build_final_caption_visible_repeat_gate([_caption(1, "而你连给自己买双像样的鞋", 0, 1_000_000)])

        self.assertTrue(gate["gate_passed"], gate)
        self.assertEqual(gate["semantic_integrity_count"], 0)

    def test_q10_immediate_predicate_continuation_is_not_blocked_as_open_tail(self) -> None:
        gate = build_final_caption_visible_repeat_gate(
            [
                _caption(1, "你花了小一万去给", 0, 1_000_000),
                _caption(2, "自己女朋友送ProMax", 1_050_000, 2_000_000),
            ]
        )

        self.assertTrue(gate["gate_passed"], gate)
        self.assertEqual(gate["semantic_integrity_count"], 0)

    def test_q11_legal_reduplicated_modifier_is_preserved(self) -> None:
        report = _run_text("死贵死贵的海蓝之谜")

        self.assertEqual(report.status, "ok", [blocker.code for blocker in report.blocker_report.blockers])
        self.assertEqual("".join(caption.text for caption in report.captions), "死贵死贵的海蓝之谜")
        self.assertNotIn("hidden_audio_repeat", {cluster.repeat_type for cluster in report.repeat_clusters})

    def test_q12_open_coordination_tail_is_trimmed_before_completed_restart(self) -> None:
        graph = _graph(
            [
                _word("w001", "他的购物车是投资", 0, 700_000, 1),
                _word("w002", "和", 700_000, 820_000, 1),
                _word("w003", "享", 820_000, 940_000, 1),
                _word("w004", "全是投资和享受你的购物车", 1_000_000, 2_200_000, 2),
            ]
        )
        result = _repair([
            _segment(1, ["w001", "w002", "w003"], "他的购物车是投资和享", 0, 940_000),
            _segment(2, ["w004"], "全是投资和享受你的购物车", 1_000_000, 2_200_000),
        ], graph)

        visible = "".join(caption.text for caption in result.captions)
        self.assertNotIn("投资和享全是", visible)
        self.assertIn("他的购物车是投资", visible)
        self.assertIn("投资和享受", visible)

    def test_dangling_discourse_connector_tail_blocks_final_gate(self) -> None:
        gate = build_final_caption_visible_repeat_gate([_caption(1, "这件事应该到此为止但是", 0, 1_000_000)])

        self.assertFalse(gate["gate_passed"])
        self.assertEqual(gate["semantic_integrity_reason_counts"]["dangling_discourse_connector_tail"], 1)

    def test_dangling_discourse_connector_tail_is_trimmed_as_whole_word(self) -> None:
        graph = _graph(
            [
                _word("w001", "前面完整表达", 0, 700_000, 1),
                _word("w002", "反而", 700_000, 980_000, 1),
            ]
        )
        result = _repair([_segment(1, ["w001", "w002"], "前面完整表达反而", 0, 980_000)], graph)

        self.assertTrue(result.report["final_visible_repair_success"], result.report)
        self.assertEqual("".join(caption.text for caption in result.captions), "前面完整表达")

    def test_head_false_start_before_gap_is_dropped_by_visual_pacing(self) -> None:
        words = [
            _word("w001", "怎", 0, 40_000, 1),
            _word("w002", "那么", 480_000, 800_000, 1),
            _word("w003", "怎么", 800_000, 1_040_000, 1),
            _word("w004", "破", 1_120_000, 1_400_000, 1),
        ]
        normalized, visual = VisualPacingNormalizer().normalize(
            [_segment(1, [word.word_id for word in words], "怎那么怎么破", 0, 1_400_000)],
            _graph(words, 1_800_000),
        )

        self.assertTrue(visual["gate_passed"], visual)
        self.assertEqual([segment.text for segment in normalized], ["那么怎么破"])
        self.assertIn("head_false_start_gap_drop", {row["reason"] for row in visual["large_intra_segment_gap_candidates"]})

    def test_repeated_single_pronoun_tail_after_gap_is_dropped_by_visual_pacing(self) -> None:
        words = [
            _word("w001", "集美", 0, 320_000, 1),
            _word("w002", "她", 400_000, 480_000, 1),
            _word("w003", "发", 480_000, 640_000, 1),
            _word("w004", "精修", 680_000, 960_000, 1),
            _word("w005", "图", 1_000_000, 1_440_000, 1),
            _word("w006", "她", 2_000_000, 2_040_000, 2),
        ]
        normalized, visual = VisualPacingNormalizer().normalize(
            [_segment(1, [word.word_id for word in words], "集美她发精修图她", 0, 2_040_000)],
            _graph(words, 2_400_000),
        )

        self.assertTrue(visual["gate_passed"], visual)
        self.assertEqual([segment.text for segment in normalized], ["集美她发精修图"])
        self.assertIn("tail_single_pronoun_gap_drop", {row["reason"] for row in visual["large_intra_segment_gap_candidates"]})

    def test_previous_complete_prefix_retry_caption_is_dropped(self) -> None:
        graph = _graph(
            [
                _word("w001", "1万块的热玛吉5代", 0, 1_400_000, 1),
                _word("w002", "然后1万块的热玛吉", 1_500_000, 2_800_000, 2),
                _word("w003", "一节课600块钱", 2_900_000, 4_000_000, 3),
            ],
            4_300_000,
        )
        result = _repair(
            [
                _segment(1, ["w001"], "1万块的热玛吉5代", 0, 1_400_000),
                _segment(2, ["w002"], "然后1万块的热玛吉", 1_500_000, 2_800_000),
                _segment(3, ["w003"], "一节课600块钱", 2_900_000, 4_000_000),
            ],
            graph,
        )

        visible = "".join(caption.text for caption in result.captions)
        self.assertTrue(result.report["final_visible_repair_success"], result.report)
        self.assertIn("1万块的热玛吉5代", visible)
        self.assertNotIn("然后1万块的热玛吉", visible)
        self.assertIn("一节课600块钱", visible)

    def test_final_target_aborted_caption_restart_is_trimmed_from_segment_tail(self) -> None:
        graph = _graph(
            [
                _word("w001", "各种卑微的舔狗发言", 0, 1_800_000, 1),
                _word("w002", "各种发外卖", 1_900_000, 2_700_000, 2),
                _word("w003", "什么各种发红包点外卖", 2_700_000, 5_100_000, 3),
            ],
            5_500_000,
        )
        timeline = [
            _segment(1, ["w001", "w002"], "各种卑微的舔狗发言各种发外卖", 0, 2_700_000),
            _segment(2, ["w003"], "什么各种发红包点外卖", 2_700_000, 5_100_000),
        ]
        captions = [
            replace(_caption(1, "各种卑微的舔狗发言", 0, 1_800_000), word_ids=["w001"], timeline_segment_ids=["v21_seg_000001"]),
            replace(_caption(2, "各种发外卖", 1_900_000, 2_700_000), word_ids=["w002"], timeline_segment_ids=["v21_seg_000001"]),
            replace(_caption(3, "什么各种发红包点外卖", 2_700_000, 5_100_000), word_ids=["w003"], timeline_segment_ids=["v21_seg_000002"]),
        ]
        plan = DecisionPlan(decisions=[])

        cleaned = ArollEngine()._drop_final_target_aborted_caption_restarts(timeline, captions, graph, plan)

        self.assertEqual([segment.text for segment in cleaned], ["各种卑微的舔狗发言", "什么各种发红包点外卖"])
        self.assertEqual(cleaned[0].word_ids, ["w001"])
        self.assertTrue(
            any(row.get("decision") == "drop_aborted_caption_restart" and row.get("applied") for row in plan.decision_trace),
            plan.decision_trace,
        )


if __name__ == "__main__":
    unittest.main()
