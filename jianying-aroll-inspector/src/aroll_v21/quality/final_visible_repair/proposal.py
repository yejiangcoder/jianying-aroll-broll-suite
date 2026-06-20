from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aroll_v21.ir.models import FinalTimelineSegment


@dataclass(frozen=True)
class TimelineRepairProposal:
    proposal_id: str
    issue_type: str
    confidence: float
    target_segment_id: str
    target_word_ids: list[str]
    target_source_start_us: int
    target_source_end_us: int
    target_text: str
    repair_action: str
    risk_tags: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TimelineRepairProposalValidation:
    valid: bool
    reason: str
    target_segment: FinalTimelineSegment | None = None
    target_word_ids: list[str] = field(default_factory=list)
    span_start_index: int = -1
    span_end_index: int = -1


def validate_timeline_repair_proposal(
    proposal: TimelineRepairProposal,
    final_timeline: list[FinalTimelineSegment],
) -> TimelineRepairProposalValidation:
    target_word_ids = [str(word_id) for word_id in proposal.target_word_ids if str(word_id)]
    if not target_word_ids:
        return TimelineRepairProposalValidation(valid=False, reason="target_word_ids_required")
    target_segment = _segment_by_id(final_timeline, proposal.target_segment_id)
    if target_segment is None:
        return TimelineRepairProposalValidation(valid=False, reason="target_segment_not_found")
    segment_word_ids = [str(word_id) for word_id in target_segment.word_ids if str(word_id)]
    missing_word_ids = [word_id for word_id in target_word_ids if word_id not in set(segment_word_ids)]
    if missing_word_ids:
        return TimelineRepairProposalValidation(
            valid=False,
            reason="target_word_ids_not_in_target_segment",
            target_segment=target_segment,
            target_word_ids=target_word_ids,
        )
    span = _contiguous_span(segment_word_ids, target_word_ids)
    if span is None:
        return TimelineRepairProposalValidation(
            valid=False,
            reason="target_word_ids_must_hit_contiguous_span",
            target_segment=target_segment,
            target_word_ids=target_word_ids,
        )
    span_start, span_end = span
    return TimelineRepairProposalValidation(
        valid=True,
        reason="ok",
        target_segment=target_segment,
        target_word_ids=target_word_ids,
        span_start_index=span_start,
        span_end_index=span_end,
    )


def _segment_by_id(
    final_timeline: list[FinalTimelineSegment],
    segment_id: str,
) -> FinalTimelineSegment | None:
    for segment in final_timeline:
        if str(segment.segment_id) == str(segment_id):
            return segment
    missing_segment: FinalTimelineSegment | None = None
    return missing_segment


def _contiguous_span(
    segment_word_ids: list[str],
    target_word_ids: list[str],
) -> tuple[int, int] | None:
    if len(target_word_ids) > len(segment_word_ids):
        missing_span: tuple[int, int] | None = None
        return missing_span
    width = len(target_word_ids)
    for index in range(0, len(segment_word_ids) - width + 1):
        if segment_word_ids[index : index + width] == target_word_ids:
            return index, index + width
    missing_span: tuple[int, int] | None = None
    return missing_span
