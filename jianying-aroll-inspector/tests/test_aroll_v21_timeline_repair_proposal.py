from __future__ import annotations

from dataclasses import replace

from aroll_v21.ir.models import CaptionRenderUnit
from aroll_v21.quality.final_visible_repair import (
    TimelineRepairProposal,
    apply_timeline_repair_proposal,
    validate_timeline_repair_proposal,
)
from tests.test_aroll_v21_caption_word_coverage_gate import _segment, _source_graph


def _proposal(**overrides) -> TimelineRepairProposal:  # type: ignore[no-untyped-def]
    values = {
        "proposal_id": "proposal_001",
        "issue_type": "unit_test_quality_issue",
        "confidence": 0.95,
        "target_segment_id": "v21_seg_000001",
        "target_word_ids": ["w1"],
        "target_source_start_us": 0,
        "target_source_end_us": 400_000,
        "target_text": "甲",
        "repair_action": "trim_word_span",
        "risk_tags": ["unit_test"],
        "evidence": {"source": "unit_test"},
    }
    values.update(overrides)
    return TimelineRepairProposal(**values)


class _BadCoverageRenderer:
    def render(self, final_timeline, source_graph):  # type: ignore[no-untyped-def]
        segment = final_timeline[0]
        return [
            CaptionRenderUnit(
                caption_id="v21_cap_000001",
                timeline_segment_ids=[segment.segment_id],
                word_ids=["w2"],
                text="乙",
                target_start_us=int(segment.target_start_us),
                target_end_us=int(segment.target_end_us),
                source_subtitle_uids=["s2"],
                style_template_id="canonical_caption_template",
                containing_video_segment_id=segment.segment_id,
            )
        ]


def test_timeline_repair_proposal_without_word_ids_does_not_apply() -> None:
    proposal = _proposal(target_word_ids=[])

    validation = validate_timeline_repair_proposal(proposal, [_segment()])
    result = apply_timeline_repair_proposal(proposal, [_segment()], _source_graph())

    assert validation.valid is False
    assert validation.reason == "target_word_ids_required"
    assert result.applied is False
    assert result.blocker_code == "V21_TIMELINE_REPAIR_PROPOSAL_INVALID"


def test_timeline_repair_proposal_target_word_ids_not_in_segment_does_not_apply() -> None:
    proposal = _proposal(target_word_ids=["missing_word"])

    validation = validate_timeline_repair_proposal(proposal, [_segment()])
    result = apply_timeline_repair_proposal(proposal, [_segment()], _source_graph())

    assert validation.valid is False
    assert validation.reason == "target_word_ids_not_in_target_segment"
    assert result.applied is False


def test_timeline_repair_proposal_apply_rerenders_and_reruns_coverage_audit() -> None:
    source_graph = _source_graph()
    segment = _segment()
    proposal = _proposal(target_word_ids=["w1"])

    result = apply_timeline_repair_proposal(proposal, [segment], source_graph)

    assert result.applied is True
    assert result.coverage_report["missing_final_timeline_caption_word_count"] == 0
    assert result.coverage_report["prewrite_uncaptioned_spoken_word_count"] == 0
    assert result.captions
    assert result.final_timeline[0].word_ids == ["w2", "w3"]
    assert "proposal_001" in result.final_timeline[0].decision_ids


def test_timeline_repair_proposal_apply_fails_when_rerendered_coverage_is_inconsistent() -> None:
    source_graph = _source_graph()
    segment = replace(_segment(), word_ids=["w1", "w2", "w3"])
    proposal = _proposal(target_word_ids=["w1"])

    result = apply_timeline_repair_proposal(
        proposal,
        [segment],
        source_graph,
        renderer=_BadCoverageRenderer(),  # type: ignore[arg-type]
    )

    assert result.applied is False
    assert result.blocker_code == "V21_TIMELINE_REPAIR_CAPTION_WORD_COVERAGE_FAILED"
    assert result.coverage_report["missing_final_timeline_caption_word_count"] == 1
