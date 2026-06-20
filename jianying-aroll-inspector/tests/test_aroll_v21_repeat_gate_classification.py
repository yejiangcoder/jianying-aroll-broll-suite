from __future__ import annotations

from aroll_v21.ir.models import CaptionRenderUnit, FinalTimelineSegment
from aroll_v21.quality.caption_alignment import build_caption_alignment_report
from aroll_v21.quality.final_caption_visible_repeat import build_final_caption_visible_repeat_gate


def _caption(index: int, start_us: int, end_us: int, text: str) -> CaptionRenderUnit:
    return CaptionRenderUnit(
        caption_id=f"v21_cap_{index:06d}",
        timeline_segment_ids=[f"v21_seg_{index:06d}"],
        word_ids=[f"w{index:03d}"],
        text=text,
        target_start_us=start_us,
        target_end_us=end_us,
        source_subtitle_uids=[f"s{index:03d}"],
        style_template_id="canonical_caption_template",
    )


def test_repeat_gate_distant_topic_containment_not_fatal() -> None:
    gate = build_final_caption_visible_repeat_gate(
        [
            _caption(1, 0, 700_000, "集美"),
            _caption(2, 20_000_000, 21_200_000, "很多集美今天都在讨论这个问题"),
        ]
    )

    assert gate["gate_passed"] is True
    assert gate["containment_repeat_count"] == 0
    assert gate["containment_repeat_raw_count"] == 1
    assert gate["visible_repeat_allow_candidate_count"] == 1
    candidate = gate["repeat_classification_candidates"][0]
    assert candidate["classification"] == "short_concept_reuse"
    assert candidate["distance_kind"] == "distant"
    assert candidate["severity"] == "allow"


def test_repeat_gate_distant_short_concept_recurrence_not_fatal() -> None:
    gate = build_final_caption_visible_repeat_gate(
        [
            _caption(1, 0, 900_000, "敢展示"),
            _caption(2, 18_000_000, 19_300_000, "敢展示自己并不等于重复表达"),
        ]
    )

    assert gate["gate_passed"] is True
    assert gate["containment_repeat_count"] == 0
    assert gate["visible_repeat_allow_candidate_count"] == 1
    assert gate["repeat_classification_candidates"][0]["classification"] == "short_concept_reuse"


def test_repeat_gate_repeated_address_or_topic_terms_across_video_not_fatal() -> None:
    gate = build_final_caption_visible_repeat_gate(
        [
            _caption(1, 0, 700_000, "朋友们"),
            _caption(2, 10_000_000, 11_000_000, "朋友们先看这个条件"),
            _caption(3, 22_000_000, 23_000_000, "朋友们最后再回到结论"),
        ]
    )

    assert gate["gate_passed"] is True
    assert gate["containment_repeat_count"] == 0
    assert gate["visible_repeat_allow_candidate_count"] >= 1
    assert all(
        candidate["severity"] != "fatal"
        for candidate in gate["repeat_classification_candidates"]
    )


def test_repeat_gate_distant_semantic_recurrence_warns_without_blocking() -> None:
    gate = build_final_caption_visible_repeat_gate(
        [
            _caption(1, 0, 1_000_000, "我们重新开始吧"),
            _caption(2, 16_000_000, 17_200_000, "大家都要重新开始"),
        ]
    )

    assert gate["gate_passed"] is True
    assert gate["ngram_repeat_count"] == 0
    assert gate["ngram_repeat_raw_count"] >= 1
    assert gate["visible_repeat_warning_candidate_count"] >= 1
    candidate = gate["visible_repeat_warning_candidates"][0]
    assert candidate["classification"] == "distant_semantic_recurrence"
    assert candidate["distance_kind"] == "distant"


def test_repeat_gate_adjacent_restart_still_blocks() -> None:
    gate = build_final_caption_visible_repeat_gate(
        [
            _caption(1, 0, 1_000_000, "咳咳就你骂"),
            _caption(2, 1_000_000, 2_600_000, "就你骂集美虚容啊"),
        ]
    )

    assert gate["gate_passed"] is False
    assert gate["prefix_suffix_overlap_count"] >= 1
    assert "V21_FINAL_CAPTION_VISIBLE_REPEAT_GATE_FAILED" in gate["blocker_codes"]
    candidate = gate["visible_repeat_candidates"][0]
    assert candidate["severity"] == "fatal"
    assert candidate["distance_kind"] == "adjacent"


def test_repeat_gate_near_restart_still_blocks_without_threshold_escape() -> None:
    gate = build_final_caption_visible_repeat_gate(
        [
            _caption(1, 0, 900_000, "我们重新开始"),
            _caption(2, 3_000_000, 3_900_000, "重新开始吧"),
        ]
    )

    assert gate["gate_passed"] is False
    assert gate["prefix_suffix_overlap_count"] >= 1
    assert gate["visible_repeat_candidates"][0]["distance_kind"] == "near"


def test_repeat_gate_adjacent_shared_ngram_without_boundary_restart_warns_only() -> None:
    gate = build_final_caption_visible_repeat_gate(
        [
            _caption(1, 0, 1_600_000, "他的购物车全是投资和享受"),
            _caption(2, 1_620_000, 2_300_000, "你的购物车"),
        ]
    )

    assert gate["gate_passed"] is True
    assert gate["ngram_repeat_count"] == 0
    assert gate["ngram_repeat_raw_count"] >= 1
    assert gate["visible_repeat_warning_candidate_count"] >= 1
    candidate = gate["visible_repeat_warning_candidates"][0]
    assert candidate["classification"] == "local_semantic_recurrence"
    assert candidate["distance_kind"] == "adjacent"


def test_repeat_gate_same_caption_restart_still_blocks() -> None:
    gate = build_final_caption_visible_repeat_gate(
        [
            _caption(1, 0, 900_000, "你是你们是极度恐慌"),
        ]
    )

    assert gate["gate_passed"] is False
    assert gate["restart_repeat_visible_count"] == 1
    assert gate["restart_repeat_visible_candidates"][0]["classification"] == "same_segment_restart"


def test_repeat_gate_medium_repeated_island_shape_not_fatal() -> None:
    gate = build_final_caption_visible_repeat_gate(
        [
            _caption(1, 0, 1_200_000, "我们讨论他们我们继续"),
        ]
    )

    assert gate["gate_passed"] is True
    assert gate["restart_repeat_visible_count"] == 0
    assert gate["visible_repeat_candidate_count"] == 0


def test_repeat_gate_classification_does_not_downgrade_caption_coverage_missing() -> None:
    caption = _caption(1, 0, 1_000_000, "短概念")
    report = build_caption_alignment_report(
        final_timeline=[
            FinalTimelineSegment(
                segment_id="v21_seg_000001",
                source_material_id="video",
                source_segment_id="src",
                source_start_us=0,
                source_end_us=1_000_000,
                target_start_us=0,
                target_end_us=1_000_000,
                word_ids=["w001", "w002"],
                text="短概念",
                decision_ids=[],
            )
        ],
        captions=[caption],
    )

    assert report["gate_passed"] is False
    assert report["missing_final_timeline_caption_word_count"] == 1
    assert "V21_FINAL_TIMELINE_CAPTION_WORD_COVERAGE_FAILED" in report["blocker_codes"]
