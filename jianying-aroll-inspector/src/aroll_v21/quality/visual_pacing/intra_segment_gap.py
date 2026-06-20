from __future__ import annotations

from dataclasses import replace
from typing import Any

from aroll_text_normalize import normalize_text
from aroll_v21.ir.models import CanonicalSourceGraph, FinalTimelineSegment

NORMAL_INTRA_SEGMENT_BREATH_GAP_US = 220_000
LARGE_INTRA_SEGMENT_GAP_US = 450_000
MIN_SPLIT_SIDE_DURATION_US = 500_000
DROPPABLE_BOUNDARY_FILLERS = {"啊", "呃", "嗯", "呐", "呢", "嘛", "吧", "咳"}


def split_large_intra_segment_gaps(
    segments: list[FinalTimelineSegment],
    source_graph: CanonicalSourceGraph,
    windows: list[tuple[str, int, int]],
) -> tuple[list[FinalTimelineSegment], dict[str, Any]]:
    word_lookup = {word.word_id: word for word in source_graph.words}
    split_segments: list[FinalTimelineSegment] = []
    candidates: list[dict[str, Any]] = []
    split_rows: list[dict[str, Any]] = []
    max_gap_us = 0
    unsafe_count = 0

    for segment in segments:
        pieces, segment_candidates, segment_splits = _split_segment_large_gaps(segment, word_lookup, windows)
        split_segments.extend(pieces)
        candidates.extend(segment_candidates)
        split_rows.extend(segment_splits)
        max_gap_us = max(max_gap_us, *[int(row.get("gap_us") or 0) for row in segment_candidates], 0)
        unsafe_count += sum(1 for row in segment_candidates if not bool(row.get("applied")))

    return split_segments, {
        "large_intra_segment_gap_candidate_count": len(candidates),
        "large_intra_segment_gap_split_count": len(split_rows),
        "large_intra_segment_gap_unsafe_count": unsafe_count,
        "large_intra_segment_gap_max_us": max_gap_us,
        "large_intra_segment_gap_normal_breath_us": NORMAL_INTRA_SEGMENT_BREATH_GAP_US,
        "large_intra_segment_gap_threshold_us": LARGE_INTRA_SEGMENT_GAP_US,
        "large_intra_segment_gap_min_split_side_duration_us": MIN_SPLIT_SIDE_DURATION_US,
        "large_intra_segment_gap_candidates": candidates,
        "large_intra_segment_gap_splits": split_rows,
    }


def empty_large_intra_segment_gap_report() -> dict[str, Any]:
    return {
        "large_intra_segment_gap_candidate_count": 0,
        "large_intra_segment_gap_split_count": 0,
        "large_intra_segment_gap_unsafe_count": 0,
        "large_intra_segment_gap_max_us": 0,
        "large_intra_segment_gap_normal_breath_us": NORMAL_INTRA_SEGMENT_BREATH_GAP_US,
        "large_intra_segment_gap_threshold_us": LARGE_INTRA_SEGMENT_GAP_US,
        "large_intra_segment_gap_min_split_side_duration_us": MIN_SPLIT_SIDE_DURATION_US,
        "large_intra_segment_gap_candidates": [],
        "large_intra_segment_gap_splits": [],
    }


def _split_segment_large_gaps(
    segment: FinalTimelineSegment,
    word_lookup: dict[str, Any],
    windows: list[tuple[str, int, int]],
) -> tuple[list[FinalTimelineSegment], list[dict[str, Any]], list[dict[str, Any]]]:
    words = [word_lookup[word_id] for word_id in segment.word_ids if word_id in word_lookup]
    if len(words) < 2:
        return [segment], [], []
    candidates: list[dict[str, Any]] = []
    split_after_indexes: set[int] = set()
    for index, (left_word, right_word) in enumerate(zip(words, words[1:])):
        gap_us = int(getattr(right_word, "source_start_us", 0) or 0) - int(getattr(left_word, "source_end_us", 0) or 0)
        if gap_us <= NORMAL_INTRA_SEGMENT_BREATH_GAP_US:
            continue
        candidate = _candidate_row(segment, left_word, right_word, gap_us)
        if gap_us < LARGE_INTRA_SEGMENT_GAP_US:
            candidate["applied"] = False
            candidate["reason"] = "below_split_threshold"
            candidates.append(candidate)
            continue
        safety_reason = _split_safety_reason(segment, words, index, windows)
        if safety_reason:
            candidate["applied"] = False
            candidate["reason"] = safety_reason
            candidates.append(candidate)
            continue
        candidate["applied"] = True
        candidate["reason"] = "large_intra_segment_gap_split"
        candidates.append(candidate)
        split_after_indexes.add(index)
    if not split_after_indexes:
        return [segment], candidates, []

    runs: list[list[Any]] = []
    current_run: list[Any] = []
    for index, word in enumerate(words):
        current_run.append(word)
        if index in split_after_indexes:
            runs.append(current_run)
            current_run = []
    if current_run:
        runs.append(current_run)
    kept_runs, dropped_boundary_filler_runs = _drop_boundary_filler_runs(runs)
    if not kept_runs:
        return [segment], candidates, []
    split_rows = [
        {
            "original_segment_id": segment.segment_id,
            "split_segment_count": len(kept_runs),
            "removed_gap_count": len(split_after_indexes),
            "removed_gap_us": int(row.get("gap_us") or 0),
            "left_word_id": str(row.get("left_word_id") or ""),
            "right_word_id": str(row.get("right_word_id") or ""),
            "dropped_boundary_filler_word_ids": [
                str(getattr(word, "word_id", "") or "") for run in dropped_boundary_filler_runs for word in run
            ],
        }
        for row in candidates
        if row.get("applied")
    ]
    return [_segment_from_run(segment, run, dropped_boundary_filler_runs) for run in kept_runs], candidates, split_rows


def _split_safety_reason(
    segment: FinalTimelineSegment,
    words: list[Any],
    split_after_index: int,
    windows: list[tuple[str, int, int]],
) -> str:
    left_run = words[: split_after_index + 1]
    right_run = words[split_after_index + 1 :]
    if not left_run or not right_run:
        return "empty_split_side"
    if _single_char_side_would_survive(left_run):
        return "single_char_left_side_would_survive"
    if _single_char_side_would_survive(right_run):
        return "single_char_right_side_would_survive"
    if _run_duration(left_run) < MIN_SPLIT_SIDE_DURATION_US:
        return "left_side_too_short"
    if _run_duration(right_run) < MIN_SPLIT_SIDE_DURATION_US:
        return "right_side_too_short"
    left_window = _source_window_id_for_range(
        windows,
        int(getattr(left_run[0], "source_start_us", 0) or 0),
        int(getattr(left_run[-1], "source_end_us", 0) or 0),
    )
    right_window = _source_window_id_for_range(
        windows,
        int(getattr(right_run[0], "source_start_us", 0) or 0),
        int(getattr(right_run[-1], "source_end_us", 0) or 0),
    )
    segment_window = _source_window_id_for_range(windows, int(segment.source_start_us), int(segment.source_end_us))
    if not left_window or not right_window or not segment_window:
        return "source_window_unresolved"
    if left_window != right_window or left_window != segment_window:
        return "cross_source_window"
    return ""


def _segment_from_run(
    segment: FinalTimelineSegment,
    words: list[Any],
    dropped_boundary_filler_runs: list[list[Any]],
) -> FinalTimelineSegment:
    dropped_word_ids = [str(getattr(word, "word_id", "") or "") for run in dropped_boundary_filler_runs for word in run]
    return replace(
        segment,
        source_start_us=int(getattr(words[0], "source_start_us")),
        source_end_us=int(getattr(words[-1], "source_end_us")),
        target_start_us=0,
        target_end_us=0,
        word_ids=[str(getattr(word, "word_id")) for word in words],
        text="".join(str(getattr(word, "text", "") or "") for word in words),
        decision_ids=sorted(set([*segment.decision_ids, "visual_pacing_large_intra_segment_gap_split"])),
        spoken_source_start_us=None,
        spoken_source_end_us=None,
        clip_source_start_us=None,
        clip_source_end_us=None,
        lead_handle_us=0,
        tail_handle_us=0,
        debug_hints=dict(segment.debug_hints)
        | {
            "visual_pacing_large_intra_segment_gap_split": True,
            "visual_pacing_large_intra_segment_gap_dropped_boundary_filler_word_ids": dropped_word_ids,
        },
    )


def _candidate_row(segment: FinalTimelineSegment, left_word: Any, right_word: Any, gap_us: int) -> dict[str, Any]:
    return {
        "segment_id": segment.segment_id,
        "text": segment.text,
        "gap_us": max(0, int(gap_us)),
        "source_start_us": int(getattr(left_word, "source_end_us", 0) or 0),
        "source_end_us": int(getattr(right_word, "source_start_us", 0) or 0),
        "left_word_id": str(getattr(left_word, "word_id", "") or ""),
        "left_word_text": str(getattr(left_word, "text", "") or ""),
        "right_word_id": str(getattr(right_word, "word_id", "") or ""),
        "right_word_text": str(getattr(right_word, "text", "") or ""),
    }


def _run_duration(words: list[Any]) -> int:
    return max(0, int(getattr(words[-1], "source_end_us", 0) or 0) - int(getattr(words[0], "source_start_us", 0) or 0))


def _drop_boundary_filler_runs(runs: list[list[Any]]) -> tuple[list[list[Any]], list[list[Any]]]:
    if len(runs) <= 1:
        return runs, []
    kept: list[list[Any]] = []
    dropped: list[list[Any]] = []
    last_index = len(runs) - 1
    for index, run in enumerate(runs):
        if index in {0, last_index} and _is_droppable_boundary_filler_run(run):
            dropped.append(run)
            continue
        kept.append(run)
    return kept, dropped


def _single_char_side_would_survive(words: list[Any]) -> bool:
    text = normalize_text("".join(str(getattr(word, "text", "") or "") for word in words))
    return len(text) == 1 and text not in DROPPABLE_BOUNDARY_FILLERS


def _is_droppable_boundary_filler_run(words: list[Any]) -> bool:
    text = normalize_text("".join(str(getattr(word, "text", "") or "") for word in words))
    return text in DROPPABLE_BOUNDARY_FILLERS


def _source_window_id_for_range(windows: list[tuple[str, int, int]], start: int, end: int) -> str:
    for window_id, window_start, window_end in windows:
        if int(window_start) <= int(start) and int(end) <= int(window_end):
            return str(window_id)
    return ""
