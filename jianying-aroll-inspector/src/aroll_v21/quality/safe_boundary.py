from __future__ import annotations

from typing import Any

from aroll_text_normalize import normalize_text
from aroll_v21.ir.models import FinalTimelineSegment


BOUNDARY_TOLERANCE_US = 1


def source_range_aligned_to_word_boundaries(
    *,
    segment: FinalTimelineSegment,
    word_lookup: dict[str, Any],
    tolerance_us: int = BOUNDARY_TOLERANCE_US,
) -> bool:
    words = [word_lookup[word_id] for word_id in segment.word_ids if word_id in word_lookup]
    if not words:
        return False
    return (
        abs(int(segment.source_start_us) - int(getattr(words[0], "source_start_us", 0))) <= tolerance_us
        and abs(int(segment.source_end_us) - int(getattr(words[-1], "source_end_us", 0))) <= tolerance_us
    )


def whole_word_boundary_report(
    *,
    segments: list[FinalTimelineSegment],
    word_lookup: dict[str, Any],
) -> dict[str, Any]:
    unsafe = [
        segment.segment_id
        for segment in segments
        if not source_range_aligned_to_word_boundaries(segment=segment, word_lookup=word_lookup)
    ]
    return {
        "whole_word_boundary_gate_passed": not unsafe,
        "unsafe_boundary_segment_ids": unsafe,
        "unsafe_boundary_count": len(unsafe),
        "blocker_codes": ["V21_SAFE_BOUNDARY_NOT_WHOLE_WORD"] if unsafe else [],
    }


def trailing_word_ids_for_suffix_overlap(
    *,
    segment: FinalTimelineSegment,
    word_lookup: dict[str, Any],
    overlap: str,
) -> list[str]:
    suffix = ""
    ids: list[str] = []
    for word_id in reversed(segment.word_ids):
        word = word_lookup.get(word_id)
        if word is None:
            missing_word_result: list[str] = []
            return missing_word_result
        suffix = normalize_text(str(getattr(word, "text", "") or "")) + suffix
        ids.insert(0, word_id)
        if suffix == overlap:
            return ids
        if len(suffix) > len(overlap):
            overrun_result: list[str] = []
            return overrun_result
    no_overlap_result: list[str] = []
    return no_overlap_result
