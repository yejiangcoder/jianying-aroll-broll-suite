from __future__ import annotations

import re
from dataclasses import dataclass, replace

from aroll_v21.ir.models import CanonicalSourceGraph, CaptionRenderUnit, FinalTimelineSegment
from aroll_v21.quality.caption_alignment import build_caption_alignment_report
from aroll_v21.quality.final_visible_repair.proposal import (
    TimelineRepairProposal,
    validate_timeline_repair_proposal,
)
from aroll_v21.quality.final_visible_repair.timeline_utils import repack_timeline, text_from_word_ids
from aroll_v21.render.subtitle_renderer import SubtitleRenderer


SUPPORTED_REPAIR_ACTIONS = {
    "drop",
    "drop_word_span",
    "trim",
    "trim_word_span",
    "suffix_trim",
    "internal_drop",
    "span_drop",
}


@dataclass(frozen=True)
class TimelineRepairMaterializationResult:
    applied: bool
    proposal_id: str
    reason: str
    final_timeline: list[FinalTimelineSegment]
    captions: list[CaptionRenderUnit]
    coverage_report: dict
    blocker_code: str = ""


def apply_timeline_repair_proposal(
    proposal: TimelineRepairProposal,
    final_timeline: list[FinalTimelineSegment],
    source_graph: CanonicalSourceGraph,
    *,
    renderer: SubtitleRenderer | None = None,
) -> TimelineRepairMaterializationResult:
    validation = validate_timeline_repair_proposal(proposal, final_timeline)
    if not validation.valid or validation.target_segment is None:
        return _blocked_result(
            proposal,
            final_timeline,
            reason=validation.reason,
            blocker_code="V21_TIMELINE_REPAIR_PROPOSAL_INVALID",
        )
    if proposal.repair_action not in SUPPORTED_REPAIR_ACTIONS:
        return _blocked_result(
            proposal,
            final_timeline,
            reason="unsupported_repair_action",
            blocker_code="V21_TIMELINE_REPAIR_PROPOSAL_UNSUPPORTED_ACTION",
        )
    repaired_timeline = _materialize_word_span_repair(
        final_timeline,
        validation.target_segment,
        validation.span_start_index,
        validation.span_end_index,
        source_graph,
        proposal,
    )
    if repaired_timeline == final_timeline:
        return _blocked_result(
            proposal,
            final_timeline,
            reason="target_word_span_not_safe_to_materialize",
            blocker_code="V21_TIMELINE_REPAIR_PROPOSAL_UNSAFE_SPAN",
        )
    active_renderer = renderer or SubtitleRenderer()
    rendered_captions = active_renderer.render(repaired_timeline, source_graph)
    coverage_report = build_caption_alignment_report(
        final_timeline=repaired_timeline,
        captions=rendered_captions,
    )
    missing_word_count = int(coverage_report.get("missing_final_timeline_caption_word_count") or 0)
    uncaptioned_word_count = int(coverage_report.get("prewrite_uncaptioned_spoken_word_count") or 0)
    if missing_word_count or uncaptioned_word_count:
        return TimelineRepairMaterializationResult(
            applied=False,
            proposal_id=proposal.proposal_id,
            reason="caption_word_coverage_inconsistent_after_apply",
            final_timeline=repaired_timeline,
            captions=rendered_captions,
            coverage_report=coverage_report,
            blocker_code="V21_TIMELINE_REPAIR_CAPTION_WORD_COVERAGE_FAILED",
        )
    return TimelineRepairMaterializationResult(
        applied=True,
        proposal_id=proposal.proposal_id,
        reason="applied",
        final_timeline=repaired_timeline,
        captions=rendered_captions,
        coverage_report=coverage_report,
    )


def _materialize_word_span_repair(
    final_timeline: list[FinalTimelineSegment],
    target_segment: FinalTimelineSegment,
    span_start_index: int,
    span_end_index: int,
    source_graph: CanonicalSourceGraph,
    proposal: TimelineRepairProposal,
) -> list[FinalTimelineSegment]:
    segment_word_ids = [str(word_id) for word_id in target_segment.word_ids if str(word_id)]
    if span_start_index < 0 or span_end_index <= span_start_index:
        return list(final_timeline)
    internal_drop = span_start_index != 0 and span_end_index != len(segment_word_ids)
    if internal_drop and proposal.repair_action not in {"internal_drop", "span_drop"}:
        return list(final_timeline)
    kept_word_ids = [
        word_id
        for index, word_id in enumerate(segment_word_ids)
        if index < span_start_index or index >= span_end_index
    ]
    repaired: list[FinalTimelineSegment] = []
    for segment in final_timeline:
        if str(segment.segment_id) != str(target_segment.segment_id):
            repaired.append(segment)
            continue
        if not kept_word_ids:
            continue
        if internal_drop:
            repaired.extend(_split_segment_around_internal_drop(segment, span_start_index, span_end_index, source_graph, proposal))
            continue
        repaired.append(_segment_for_kept_words(segment, kept_word_ids, source_graph, proposal))
    return repack_timeline(repaired)


def _split_segment_around_internal_drop(
    segment: FinalTimelineSegment,
    span_start_index: int,
    span_end_index: int,
    source_graph: CanonicalSourceGraph,
    proposal: TimelineRepairProposal,
) -> list[FinalTimelineSegment]:
    segment_word_ids = [str(word_id) for word_id in segment.word_ids if str(word_id)]
    runs = [
        segment_word_ids[:span_start_index],
        segment_word_ids[span_end_index:],
    ]
    repaired: list[FinalTimelineSegment] = []
    for index, run_word_ids in enumerate([run for run in runs if run], start=1):
        segment_id = f"{segment.segment_id}_{_proposal_id_suffix(proposal.proposal_id)}_{index:02d}"
        repaired.append(_segment_for_kept_words(segment, run_word_ids, source_graph, proposal, segment_id=segment_id))
    return repaired


def _segment_for_kept_words(
    segment: FinalTimelineSegment,
    kept_word_ids: list[str],
    source_graph: CanonicalSourceGraph,
    proposal: TimelineRepairProposal,
    *,
    segment_id: str | None = None,
) -> FinalTimelineSegment:
    words_by_id = {word.word_id: word for word in source_graph.words}
    words = [words_by_id[word_id] for word_id in kept_word_ids if word_id in words_by_id]
    if len(words) != len(kept_word_ids):
        return segment
    source_start_us = int(words[0].source_start_us)
    source_end_us = int(words[-1].source_end_us)
    target_start_us = int(segment.target_start_us)
    target_end_us = int(segment.target_end_us)
    if source_start_us > int(segment.source_start_us):
        target_start_us = min(
            target_end_us,
            target_start_us + max(0, source_start_us - int(segment.source_start_us)),
        )
    if source_end_us < int(segment.source_end_us):
        target_end_us = max(
            target_start_us,
            int(segment.target_start_us) + max(0, source_end_us - int(segment.source_start_us)),
        )
    if target_end_us <= target_start_us:
        target_end_us = target_start_us + max(1, source_end_us - source_start_us)
    return replace(
        segment,
        segment_id=segment_id or segment.segment_id,
        source_start_us=source_start_us,
        source_end_us=source_end_us,
        target_start_us=target_start_us,
        target_end_us=target_end_us,
        word_ids=list(kept_word_ids),
        text=text_from_word_ids(kept_word_ids, source_graph),
        decision_ids=[*segment.decision_ids, proposal.proposal_id],
        spoken_source_start_us=source_start_us,
        spoken_source_end_us=source_end_us,
        clip_source_start_us=source_start_us if segment.clip_source_start_us is not None else segment.clip_source_start_us,
        clip_source_end_us=source_end_us if segment.clip_source_end_us is not None else segment.clip_source_end_us,
        debug_hints={
            **dict(segment.debug_hints or {}),
            "timeline_repair_proposal_id": proposal.proposal_id,
            "timeline_repair_action": proposal.repair_action,
        },
    )


def _proposal_id_suffix(proposal_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", str(proposal_id or "repair")).strip("_")
    return safe[:48] or "repair"


def _blocked_result(
    proposal: TimelineRepairProposal,
    final_timeline: list[FinalTimelineSegment],
    *,
    reason: str,
    blocker_code: str,
) -> TimelineRepairMaterializationResult:
    return TimelineRepairMaterializationResult(
        applied=False,
        proposal_id=proposal.proposal_id,
        reason=reason,
        final_timeline=list(final_timeline),
        captions=list(),
        coverage_report=dict(),
        blocker_code=blocker_code,
    )
