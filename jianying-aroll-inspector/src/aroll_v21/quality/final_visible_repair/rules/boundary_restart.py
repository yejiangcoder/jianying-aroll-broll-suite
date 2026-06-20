from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from aroll_text_normalize import normalize_text
from aroll_v21.ir.models import CanonicalSourceGraph, FinalTimelineSegment
from aroll_v21.quality.final_visible_repair.proposal import TimelineRepairProposal
from aroll_v21.quality.final_visible_repair.timeline_utils import ordered_segments, text_from_word_ids


MIN_BOUNDARY_RESTART_OVERLAP_CJK_CHARS = 3
MAX_BOUNDARY_RESTART_TARGET_GAP_US = 300_000


@dataclass(frozen=True)
class BoundaryRestartCandidate:
    prev_segment_id: str
    next_segment_id: str
    overlap_text: str
    overlap_char_count: int
    prev_suffix_word_ids: list[str]
    next_prefix_word_ids: list[str]
    gap_us: int
    reason: str

    def to_evidence(self) -> dict[str, Any]:
        return {
            "prev_segment_id": self.prev_segment_id,
            "next_segment_id": self.next_segment_id,
            "overlap_text": self.overlap_text,
            "overlap_char_count": self.overlap_char_count,
            "prev_suffix_word_ids": list(self.prev_suffix_word_ids),
            "next_prefix_word_ids": list(self.next_prefix_word_ids),
            "gap_us": int(self.gap_us),
            "reason": self.reason,
        }


def detect_boundary_restart_candidates(
    final_timeline: list[FinalTimelineSegment],
    source_graph: CanonicalSourceGraph,
    *,
    max_target_gap_us: int = MAX_BOUNDARY_RESTART_TARGET_GAP_US,
) -> list[BoundaryRestartCandidate]:
    candidates: list[BoundaryRestartCandidate] = []
    segments = ordered_segments(final_timeline)
    for index in range(len(segments) - 1):
        previous = segments[index]
        next_segment = segments[index + 1]
        candidate = _candidate_for_pair(
            previous,
            next_segment,
            source_graph,
            max_target_gap_us=max_target_gap_us,
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def build_boundary_restart_proposals(
    final_timeline: list[FinalTimelineSegment],
    source_graph: CanonicalSourceGraph,
) -> list[TimelineRepairProposal]:
    proposals: list[TimelineRepairProposal] = []
    for index, candidate in enumerate(detect_boundary_restart_candidates(final_timeline, source_graph), start=1):
        evidence = candidate.to_evidence()
        proposals.append(
            TimelineRepairProposal(
                proposal_id=f"boundary_restart_{index:06d}_{candidate.prev_segment_id}_{candidate.next_segment_id}",
                issue_type="boundary_restart",
                confidence=0.95,
                target_segment_id=candidate.prev_segment_id,
                target_word_ids=list(candidate.prev_suffix_word_ids),
                target_source_start_us=_word_source_start_us(candidate.prev_suffix_word_ids, source_graph),
                target_source_end_us=_word_source_end_us(candidate.prev_suffix_word_ids, source_graph),
                target_text=candidate.overlap_text,
                repair_action="suffix_trim",
                risk_tags=["adjacent_boundary_restart", "whole_word_suffix_trim"],
                evidence={
                    **evidence,
                    "confidence": "high",
                    "proposal_policy": "trim_previous_suffix_keep_next_prefix",
                },
            )
        )
    return proposals


def _candidate_for_pair(
    previous: FinalTimelineSegment,
    next_segment: FinalTimelineSegment,
    source_graph: CanonicalSourceGraph,
    *,
    max_target_gap_us: int,
) -> BoundaryRestartCandidate | None:
    gap_us = int(next_segment.target_start_us) - int(previous.target_end_us)
    if gap_us < 0 or gap_us > max_target_gap_us:
        no_candidate: BoundaryRestartCandidate | None = None
        return no_candidate
    previous_word_ids = [str(word_id) for word_id in previous.word_ids if str(word_id)]
    next_word_ids = [str(word_id) for word_id in next_segment.word_ids if str(word_id)]
    if len(previous_word_ids) < 2 or len(next_word_ids) < 2:
        no_candidate: BoundaryRestartCandidate | None = None
        return no_candidate
    previous_text = normalize_text(text_from_word_ids(previous_word_ids, source_graph) or previous.text)
    next_text = normalize_text(text_from_word_ids(next_word_ids, source_graph) or next_segment.text)
    if not previous_text or not next_text:
        no_candidate: BoundaryRestartCandidate | None = None
        return no_candidate
    max_word_count = min(len(previous_word_ids) - 1, len(next_word_ids) - 1)
    for count in range(max_word_count, 0, -1):
        previous_suffix_ids = previous_word_ids[-count:]
        next_prefix_ids = next_word_ids[:count]
        previous_suffix_text = normalize_text(text_from_word_ids(previous_suffix_ids, source_graph))
        next_prefix_text = normalize_text(text_from_word_ids(next_prefix_ids, source_graph))
        if not previous_suffix_text or previous_suffix_text != next_prefix_text:
            continue
        overlap_cjk_count = _cjk_char_count(previous_suffix_text)
        if overlap_cjk_count < MIN_BOUNDARY_RESTART_OVERLAP_CJK_CHARS:
            continue
        if not previous_text.endswith(previous_suffix_text) or not next_text.startswith(previous_suffix_text):
            continue
        next_remaining_text = next_text[len(previous_suffix_text) :]
        if _cjk_char_count(next_remaining_text) < 1:
            continue
        return BoundaryRestartCandidate(
            prev_segment_id=previous.segment_id,
            next_segment_id=next_segment.segment_id,
            overlap_text=previous_suffix_text,
            overlap_char_count=overlap_cjk_count,
            prev_suffix_word_ids=previous_suffix_ids,
            next_prefix_word_ids=next_prefix_ids,
            gap_us=gap_us,
            reason="previous suffix is restarted as next prefix and next segment continues with more complete expression",
        )
    no_candidate: BoundaryRestartCandidate | None = None
    return no_candidate


def _word_source_start_us(word_ids: list[str], source_graph: CanonicalSourceGraph) -> int:
    words_by_id = {word.word_id: word for word in source_graph.words}
    for word_id in word_ids:
        word = words_by_id.get(word_id)
        if word is not None:
            return int(word.source_start_us)
    return 0


def _word_source_end_us(word_ids: list[str], source_graph: CanonicalSourceGraph) -> int:
    words_by_id = {word.word_id: word for word in source_graph.words}
    for word_id in reversed(word_ids):
        word = words_by_id.get(word_id)
        if word is not None:
            return int(word.source_end_us)
    return 0


def _cjk_char_count(text: str) -> int:
    return len(re.findall(r"[\u3400-\u9fff]", str(text or "")))
