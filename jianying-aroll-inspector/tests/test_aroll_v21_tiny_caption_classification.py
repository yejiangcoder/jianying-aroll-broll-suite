from __future__ import annotations

from dataclasses import replace

from aroll_v21.ir.models import CaptionRenderUnit, FinalTimelineSegment
from aroll_v21.quality.caption_alignment import build_caption_alignment_report
from aroll_v21.quality.final_caption_visible_repeat import build_final_caption_visible_repeat_gate
from aroll_v21.quality.quality_gate import build_quality_gate_report
from aroll_v21.quality.subtitle_readability import subtitle_interval_report


def _caption(index: int, start_us: int, end_us: int, text: str) -> CaptionRenderUnit:
    return CaptionRenderUnit(
        caption_id=f"v21_cap_{index:06d}",
        timeline_segment_ids=["v21_seg_000001"],
        word_ids=[f"w{index:03d}"],
        text=text,
        target_start_us=start_us,
        target_end_us=end_us,
        source_subtitle_uids=[f"s{index:03d}"],
        style_template_id="canonical_caption_template",
        containing_video_segment_id="v21_seg_000001",
    )


def _segment_for(captions: list[CaptionRenderUnit]) -> FinalTimelineSegment:
    return FinalTimelineSegment(
        segment_id="v21_seg_000001",
        source_material_id="video",
        source_segment_id="src",
        source_start_us=0,
        source_end_us=max(int(caption.target_end_us) for caption in captions),
        target_start_us=0,
        target_end_us=max(int(caption.target_end_us) for caption in captions),
        word_ids=[word_id for caption in captions for word_id in caption.word_ids],
        text="".join(caption.text for caption in captions),
        decision_ids=[],
    )


def _semantic_gate_ok() -> dict[str, object]:
    return {
        "semantic_adjudication_gate_passed": True,
        "semantic_request_count": 0,
        "semantic_request_unresolved_count": 0,
        "blocker_codes": [],
    }


def test_single_valid_tiny_caption_not_fatal() -> None:
    report = subtitle_interval_report([_caption(1, 0, 700_000, "敢展示")])

    assert report["subtitle_readability_gate_passed"] is True
    assert report["tiny_caption_allow_count"] == 1
    assert report["tiny_caption_fatal_count"] == 0
    assert report["tiny_caption_classifications"][0]["classification"] == "semantic_short_phrase"


def test_topic_term_tiny_caption_not_fatal() -> None:
    report = subtitle_interval_report(
        [
            _caption(1, 0, 700_000, "集美"),
            _caption(2, 12_000_000, 12_700_000, "集美"),
        ]
    )

    assert report["subtitle_readability_gate_passed"] is True
    assert {row["classification"] for row in report["tiny_caption_classifications"]} == {"topic_term"}


def test_address_term_tiny_caption_not_fatal() -> None:
    report = subtitle_interval_report([_caption(1, 0, 700_000, "朋友")])

    assert report["subtitle_readability_gate_passed"] is True
    assert report["tiny_caption_allow_count"] == 1


def test_proper_noun_like_tiny_caption_not_fatal() -> None:
    report = subtitle_interval_report([_caption(1, 0, 700_000, "张三")])

    assert report["subtitle_readability_gate_passed"] is True
    assert report["tiny_caption_classifications"][0]["classification"] == "semantic_short_phrase"


def test_english_abbreviation_tiny_caption_not_fatal() -> None:
    report = subtitle_interval_report([_caption(1, 0, 700_000, "IPO")])

    assert report["subtitle_readability_gate_passed"] is True
    assert report["tiny_caption_classifications"][0]["classification"] == "english_abbreviation"


def test_numeric_abbreviation_tiny_caption_not_fatal() -> None:
    report = subtitle_interval_report([_caption(1, 0, 700_000, "3D")])

    assert report["subtitle_readability_gate_passed"] is True
    assert report["tiny_caption_classifications"][0]["classification"] == "numeric_abbreviation"


def test_valid_tiny_caption_does_not_count_into_fatal_density() -> None:
    report = subtitle_interval_report(
        [
            _caption(1, 0, 700_000, "的"),
            _caption(2, 800_000, 1_500_000, "乱花钱"),
            _caption(3, 1_600_000, 2_300_000, "了"),
        ]
    )

    assert report["tiny_caption_fatal_count"] == 2
    assert report["tiny_caption_residual_density_window_count"] == 0


def test_multiple_valid_tiny_captions_across_video_not_fatal() -> None:
    texts = ["敢展示", "集美", "驼起来", "乱花钱", "IPO", "大胆的", "3D"]
    captions = [
        _caption(index, (index - 1) * 900_000, index * 900_000 - 100_000, text)
        for index, text in enumerate(texts, start=1)
    ]

    report = subtitle_interval_report(captions)

    assert report["subtitle_readability_gate_passed"] is True
    assert report["captions_le_3_chars"] == len(texts)
    assert report["tiny_caption_fatal_count"] == 0
    assert report["tiny_caption_residual_density_window_count"] == 0


def test_local_residual_tiny_density_is_fatal() -> None:
    captions = [
        _caption(1, 0, 600_000, "的"),
        _caption(2, 700_000, 1_300_000, "了"),
        _caption(3, 1_400_000, 2_000_000, "在"),
    ]

    report = subtitle_interval_report(captions)

    assert report["subtitle_readability_gate_passed"] is False
    assert report["tiny_caption_residual_density_window_count"] == 1
    assert "V21_SUBTITLE_TINY_CAPTION_RESIDUAL_DENSITY" in report["blocker_codes"]
    window = report["tiny_caption_residual_density_windows"][0]
    assert window["density_window_id"]
    assert window["residual_tiny_caption_count"] == 3


def test_isolated_function_half_start_and_asr_residual_are_blockers() -> None:
    captions = [
        _caption(1, 0, 600_000, "的"),
        _caption(2, 700_000, 1_300_000, "你只"),
        _caption(3, 1_400_000, 2_000_000, "啊啊"),
    ]

    report = subtitle_interval_report(captions)
    classifications = {row["caption_text"]: row["classification"] for row in report["tiny_caption_classifications"]}

    assert report["subtitle_readability_gate_passed"] is False
    assert classifications["的"] == "isolated_function_word"
    assert classifications["你只"] == "half_start_fragment"
    assert classifications["啊啊"] == "asr_residual_fragment"
    assert report["tiny_caption_fatal_count"] == 3


def test_caption_coverage_missing_still_fatal_with_valid_tiny_classification() -> None:
    caption = _caption(1, 0, 700_000, "IPO")
    segment = _segment_for([caption])
    report = build_caption_alignment_report(
        final_timeline=[replace(segment, word_ids=["w001", "w999"])],
        captions=[caption],
    )

    assert report["tiny_caption_fatal_count"] == 0
    assert report["gate_passed"] is False
    assert report["missing_final_timeline_caption_word_count"] == 1
    assert "V21_FINAL_TIMELINE_CAPTION_WORD_COVERAGE_FAILED" in report["blocker_codes"]


def test_repeat_gate_fatal_not_overridden_by_tiny_classification() -> None:
    repeat_gate = build_final_caption_visible_repeat_gate(
        [
            _caption(1, 0, 700_000, "咳咳就你骂"),
            _caption(2, 700_000, 1_500_000, "就你骂集美虚容啊"),
        ]
    )
    caption_alignment = build_caption_alignment_report(
        final_timeline=[_segment_for([_caption(1, 0, 700_000, "IPO")])],
        captions=[_caption(1, 0, 700_000, "IPO")],
    )

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

    assert caption_alignment["tiny_caption_fatal_count"] == 0
    assert repeat_gate["gate_passed"] is False
    assert quality["gate_passed"] is False
    assert "V21_FINAL_CAPTION_VISIBLE_REPEAT_GATE_FAILED" in quality["blocker_codes"]


def test_tiny_caption_report_includes_classification_evidence() -> None:
    report = subtitle_interval_report([_caption(1, 0, 700_000, "IPO")])
    row = report["tiny_caption_classifications"][0]

    assert row["caption_id"] == "v21_cap_000001"
    assert row["segment_id"] == "v21_seg_000001"
    assert row["caption_text"] == "IPO"
    assert row["duration_us"] == 700_000
    assert row["char_count"] == 3
    assert row["word_ids"] == ["w001"]
    assert row["classification"] == "english_abbreviation"
    assert row["severity"] == "allow"
    assert row["classification_reason"]
    assert row["risk_tags"] == ["abbreviation"]
