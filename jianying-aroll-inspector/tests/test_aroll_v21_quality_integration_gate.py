from __future__ import annotations

from dataclasses import replace

from aroll_v21.ir.models import CaptionRenderUnit
from aroll_v21.quality.caption_alignment import build_caption_alignment_report
from aroll_v21.quality.final_caption_visible_repeat import build_final_caption_visible_repeat_gate
from aroll_v21.quality.quality_gate import build_quality_gate_report
from aroll_v21.render.subtitle_renderer import SubtitleRenderer
from tests.test_aroll_v21_boundary_restart_repair import _boundary_restart_fixture
from tests.test_aroll_v21_repeated_island_repair import _graph_for_tokens, _high_confidence_fixture, _single_segment


def _semantic_gate_ok() -> dict[str, object]:
    return {
        "semantic_adjudication_gate_passed": True,
        "semantic_request_count": 0,
        "semantic_request_unresolved_count": 0,
        "blocker_codes": [],
    }


def test_final_visible_proposal_actions_are_reported_for_boundary_and_repeated_island() -> None:
    from aroll_v21.quality.final_visible_caption_repair import repair_final_visible_caption_issues

    boundary_graph, boundary_timeline = _boundary_restart_fixture()
    renderer = SubtitleRenderer()
    boundary_result = repair_final_visible_caption_issues(
        final_timeline=boundary_timeline,
        captions=renderer.render(boundary_timeline, boundary_graph),
        source_graph=boundary_graph,
        render_captions=lambda rows: renderer.render(rows, boundary_graph),
    )

    assert boundary_result.report["boundary_restart_repair_action_count"] == 1
    assert boundary_result.report["timeline_repair_proposal_action_count"] >= 1
    assert boundary_result.report["boundary_restart_repair_actions"][0]["proposal_id"]
    assert boundary_result.report["boundary_restart_repair_actions"][0]["coverage_report"] == {
        "missing_final_timeline_caption_word_count": 0,
        "prewrite_uncaptioned_spoken_word_count": 0,
    }

    island_graph, island_timeline = _high_confidence_fixture()
    island_result = repair_final_visible_caption_issues(
        final_timeline=island_timeline,
        captions=renderer.render(island_timeline, island_graph),
        source_graph=island_graph,
        render_captions=lambda rows: renderer.render(rows, island_graph),
    )

    assert island_result.report["repeated_island_repair_action_count"] == 1
    assert island_result.report["timeline_repair_proposal_action_count"] >= 1
    assert island_result.report["repeated_island_repair_actions"][0]["proposal_id"]
    assert island_result.report["repeated_island_repair_actions"][0]["coverage_report"] == {
        "missing_final_timeline_caption_word_count": 0,
        "prewrite_uncaptioned_spoken_word_count": 0,
    }


def test_final_visible_repairs_fatal_tiny_caption_residual_through_proposal() -> None:
    from aroll_v21.quality.final_visible_caption_repair import repair_final_visible_caption_issues

    graph = _graph_for_tokens(["咳咳", "继续表达"], step_us=700_000)
    base = _single_segment(graph)
    timeline = [
        replace(
            base,
            segment_id="v21_seg_000001",
            source_start_us=0,
            source_end_us=700_000,
            target_start_us=0,
            target_end_us=700_000,
            word_ids=["w001"],
            text="咳咳",
        ),
        replace(
            base,
            segment_id="v21_seg_000002",
            source_start_us=700_000,
            source_end_us=1_400_000,
            target_start_us=700_000,
            target_end_us=1_400_000,
            word_ids=["w002"],
            text="继续表达",
        ),
    ]
    renderer = SubtitleRenderer()

    result = repair_final_visible_caption_issues(
        final_timeline=timeline,
        captions=renderer.render(timeline, graph),
        source_graph=graph,
        render_captions=lambda rows: renderer.render(rows, graph),
    )

    assert result.report["final_visible_repair_success"] is True
    assert result.report["timeline_repair_proposal_action_count"] == 1
    action = result.report["timeline_repair_proposal_actions"][0]
    assert action["issue_type"] == "tiny_caption_residual"
    assert action["decision"] == "span_drop"
    assert action["coverage_report"] == {
        "missing_final_timeline_caption_word_count": 0,
        "prewrite_uncaptioned_spoken_word_count": 0,
    }
    assert [segment.text for segment in result.final_timeline] == ["继续表达"]
    assert [caption.text for caption in result.captions] == ["继续表达"]


def test_final_visible_repairs_contained_open_tail_short_fragment_through_proposal() -> None:
    from aroll_v21.quality.final_visible_caption_repair import repair_final_visible_caption_issues

    graph = _graph_for_tokens(["你", "变得", "更丑了", "你", "变得"], step_us=400_000)
    base = _single_segment(graph)
    timeline = [
        replace(
            base,
            segment_id="v21_seg_000001",
            source_start_us=0,
            source_end_us=1_200_000,
            target_start_us=0,
            target_end_us=1_200_000,
            word_ids=["w001", "w002", "w003"],
            text="你变得更丑了",
        ),
        replace(
            base,
            segment_id="v21_seg_000002",
            source_start_us=1_200_000,
            source_end_us=2_000_000,
            target_start_us=1_200_000,
            target_end_us=2_000_000,
            word_ids=["w004", "w005"],
            text="你变得",
        ),
    ]
    renderer = SubtitleRenderer()

    result = repair_final_visible_caption_issues(
        final_timeline=timeline,
        captions=renderer.render(timeline, graph),
        source_graph=graph,
        render_captions=lambda rows: renderer.render(rows, graph),
    )

    assert [segment.text for segment in result.final_timeline] == ["你变得更丑了"]
    assert [caption.text for caption in result.captions] == ["你变得更丑了"]
    action = result.report["timeline_repair_proposal_actions"][0]
    assert action["issue_type"] == "contained_short_caption_fragment"
    assert action["target_word_ids"] == ["w004", "w005"]
    assert action["coverage_report"] == {
        "missing_final_timeline_caption_word_count": 0,
        "prewrite_uncaptioned_spoken_word_count": 0,
    }


def test_final_visible_repairs_self_repair_aborted_phrase_inside_merged_segment_through_proposal() -> None:
    from aroll_v21.quality.final_visible_caption_repair import repair_final_visible_caption_issues

    tokens = ["怎么", "把", "输掉", "的", "尊严", "一点", "一点", "的", "那个", "一点", "一点", "的", "赢回来"]
    graph = _graph_for_tokens(tokens, step_us=240_000)
    base = _single_segment(graph)
    timeline = [
        replace(
            base,
            segment_id="v21_seg_000001",
            source_start_us=0,
            source_end_us=2_160_000,
            target_start_us=0,
            target_end_us=2_160_000,
            word_ids=["w001", "w002", "w003", "w004", "w005", "w006", "w007", "w008", "w009"],
            text="怎么把输掉的尊严一点一点的那个",
        ),
        replace(
            base,
            segment_id="v21_seg_000002",
            source_start_us=2_160_000,
            source_end_us=3_120_000,
            target_start_us=2_160_000,
            target_end_us=3_120_000,
            word_ids=["w010", "w011", "w012", "w013"],
            text="一点一点的赢回来",
        ),
    ]
    captions = [
        CaptionRenderUnit(
            caption_id="v21_cap_000001",
            timeline_segment_ids=["v21_seg_000001"],
            word_ids=["w001", "w002", "w003", "w004", "w005"],
            text="怎么把输掉的尊严",
            target_start_us=0,
            target_end_us=1_200_000,
            source_subtitle_uids=["s001"],
            style_template_id="canonical_caption_template",
            containing_video_segment_id="v21_seg_000001",
        ),
        CaptionRenderUnit(
            caption_id="v21_cap_000002",
            timeline_segment_ids=["v21_seg_000001"],
            word_ids=["w006", "w007", "w008", "w009"],
            text="一点一点的那个",
            target_start_us=1_200_000,
            target_end_us=2_160_000,
            source_subtitle_uids=["s001"],
            style_template_id="canonical_caption_template",
            containing_video_segment_id="v21_seg_000001",
        ),
        CaptionRenderUnit(
            caption_id="v21_cap_000003",
            timeline_segment_ids=["v21_seg_000002"],
            word_ids=["w010", "w011", "w012", "w013"],
            text="一点一点的赢回来",
            target_start_us=2_160_000,
            target_end_us=3_120_000,
            source_subtitle_uids=["s002"],
            style_template_id="canonical_caption_template",
            containing_video_segment_id="v21_seg_000002",
        ),
    ]
    renderer = SubtitleRenderer()

    result = repair_final_visible_caption_issues(
        final_timeline=timeline,
        captions=captions,
        source_graph=graph,
        render_captions=lambda rows: renderer.render(rows, graph),
    )

    visible_text = "".join(caption.text for caption in result.captions)
    assert "一点一点的那个" not in visible_text
    assert "一点一点的赢回来" in visible_text
    assert "".join(segment.text for segment in result.final_timeline) == "怎么把输掉的尊严一点一点的赢回来"
    action = [row for row in result.report["timeline_repair_proposal_actions"] if row["issue_type"] == "self_repair_aborted_phrase"][0]
    assert action["decision"] == "drop_left_keep_right"
    assert action["target_word_ids"] == ["w006", "w007", "w008", "w009"]
    assert action["coverage_report"] == {
        "missing_final_timeline_caption_word_count": 0,
        "prewrite_uncaptioned_spoken_word_count": 0,
    }


def test_final_visible_repairs_short_aborted_prefix_with_single_char_tail_mismatch() -> None:
    from aroll_v21.quality.final_visible_caption_repair import repair_final_visible_caption_issues

    graph = _graph_for_tokens(["开始", "甲", "开始", "加速", "处理"], step_us=360_000)
    base = _single_segment(graph)
    timeline = [
        replace(
            base,
            segment_id="v21_seg_000001",
            source_start_us=0,
            source_end_us=720_000,
            target_start_us=0,
            target_end_us=720_000,
            word_ids=["w001", "w002"],
            text="开始甲",
        ),
        replace(
            base,
            segment_id="v21_seg_000002",
            source_start_us=720_000,
            source_end_us=1_800_000,
            target_start_us=720_000,
            target_end_us=1_800_000,
            word_ids=["w003", "w004", "w005"],
            text="开始加速处理",
        ),
    ]
    renderer = SubtitleRenderer()

    result = repair_final_visible_caption_issues(
        final_timeline=timeline,
        captions=renderer.render(timeline, graph),
        source_graph=graph,
        render_captions=lambda rows: renderer.render(rows, graph),
    )

    assert [segment.text for segment in result.final_timeline] == ["开始加速处理"]
    assert [caption.text for caption in result.captions] == ["开始加速处理"]
    action = [row for row in result.report["timeline_repair_proposal_actions"] if row["issue_type"] == "short_aborted_prefix_caption"][0]
    assert action["decision"] == "span_drop"
    assert action["target_word_ids"] == ["w001", "w002"]
    assert action["coverage_report"] == {
        "missing_final_timeline_caption_word_count": 0,
        "prewrite_uncaptioned_spoken_word_count": 0,
    }


def test_final_visible_merges_open_tail_short_caption_with_next_caption() -> None:
    from aroll_v21.quality.final_visible_caption_repair import repair_final_visible_caption_issues

    graph = _graph_for_tokens(["大胆", "的", "去", "执行"], step_us=280_000)
    base = _single_segment(graph)
    timeline = [
        replace(
            base,
            segment_id="v21_seg_000001",
            source_start_us=0,
            source_end_us=560_000,
            target_start_us=0,
            target_end_us=560_000,
            word_ids=["w001", "w002"],
            text="大胆的",
        ),
        replace(
            base,
            segment_id="v21_seg_000002",
            source_start_us=560_000,
            source_end_us=1_120_000,
            target_start_us=560_000,
            target_end_us=1_120_000,
            word_ids=["w003", "w004"],
            text="去执行",
        ),
    ]
    renderer = SubtitleRenderer()

    result = repair_final_visible_caption_issues(
        final_timeline=timeline,
        captions=renderer.render(timeline, graph),
        source_graph=graph,
        render_captions=lambda rows: renderer.render(rows, graph),
    )
    coverage = build_caption_alignment_report(final_timeline=result.final_timeline, captions=result.captions)

    assert [segment.text for segment in result.final_timeline] == ["大胆的去执行"]
    assert [caption.text for caption in result.captions] == ["大胆的去执行"]
    assert coverage["missing_final_timeline_caption_word_count"] == 0
    assert coverage["prewrite_uncaptioned_spoken_word_count"] == 0
    assert any(row["issue_type"] == "open_tail_short_caption" for row in result.report["final_visible_repair_actions"])


def test_quality_gate_passes_through_repeat_and_tiny_classification_fields() -> None:
    captions = [
        CaptionRenderUnit(
            caption_id="v21_cap_000001",
            timeline_segment_ids=["v21_seg_000001"],
            word_ids=["w001"],
            text="集美",
            target_start_us=0,
            target_end_us=700_000,
            source_subtitle_uids=["s001"],
            style_template_id="canonical_caption_template",
            containing_video_segment_id="v21_seg_000001",
        ),
        CaptionRenderUnit(
            caption_id="v21_cap_000002",
            timeline_segment_ids=["v21_seg_000001"],
            word_ids=["w002"],
            text="很多集美都在讨论",
            target_start_us=12_000_000,
            target_end_us=13_000_000,
            source_subtitle_uids=["s002"],
            style_template_id="canonical_caption_template",
            containing_video_segment_id="v21_seg_000001",
        ),
    ]
    segment = replace(
        _boundary_restart_fixture()[1][0],
        segment_id="v21_seg_000001",
        source_start_us=0,
        source_end_us=13_000_000,
        target_start_us=0,
        target_end_us=13_000_000,
        word_ids=["w001", "w002"],
        text="集美很多集美都在讨论",
    )
    repeat_gate = build_final_caption_visible_repeat_gate(captions)
    caption_alignment = build_caption_alignment_report(final_timeline=[segment], captions=captions)

    quality = build_quality_gate_report(
        effective_speed_gate={"gate_passed": True, "blocker_codes": []},
        final_repeat_convergence_gate={"gate_passed": True, "blocker_codes": []},
        final_caption_visible_repeat_gate=repeat_gate,
        semantic_adjudication_gate=_semantic_gate_ok(),
        visual_pacing_gate={
            "gate_passed": True,
            "blocker_codes": [],
            "visual_pacing_executed": True,
            "visual_merge_safety_gate_passed": True,
        },
        caption_alignment_gate=caption_alignment,
        ready_for_user_manual_qc_preconditions_passed=True,
    )

    repeat_payload = quality["final_caption_visible_repeat_gate"]
    caption_payload = quality["caption_alignment_gate"]
    assert repeat_payload["containment_repeat_raw_count"] == 1
    assert repeat_payload["visible_repeat_allow_candidate_count"] == 1
    assert repeat_payload["repeat_classification_candidates"][0]["classification"] == "short_concept_reuse"
    assert caption_payload["tiny_caption_classification_count"] == 1
    assert caption_payload["tiny_caption_allow_count"] == 1
    assert caption_payload["tiny_caption_classifications"][0]["classification"] == "semantic_short_phrase"
