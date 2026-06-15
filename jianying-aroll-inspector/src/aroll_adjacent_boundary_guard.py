from __future__ import annotations

from copy import deepcopy
from typing import Any


MAX_SOURCE_OVERLAP_US = 180_000
WORD_GAP_SEARCH_PAD_US = 120_000


def word_gap_boundary(
    word_timeline: list[dict[str, Any]],
    overlap_start_us: int,
    overlap_end_us: int,
) -> int | None:
    words = sorted(
        [
            word
            for word in word_timeline
            if int(word.get("end_us") or 0) >= overlap_start_us - WORD_GAP_SEARCH_PAD_US
            and int(word.get("start_us") or 0) <= overlap_end_us + WORD_GAP_SEARCH_PAD_US
        ],
        key=lambda word: (int(word.get("start_us") or 0), int(word.get("end_us") or 0)),
    )
    best: tuple[int, int] | None = None
    for left, right in zip(words, words[1:]):
        left_end = int(left.get("end_us") or 0)
        right_start = int(right.get("start_us") or 0)
        if right_start < left_end:
            continue
        boundary = (left_end + right_start) // 2
        if overlap_start_us <= boundary <= overlap_end_us:
            gap = right_start - left_end
            if best is None or gap < best[0]:
                best = (gap, boundary)
    return best[1] if best else None


def rebase_targets(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    target_start = 0
    rebased: list[dict[str, Any]] = []
    for clip in clips:
        cloned = deepcopy(clip)
        duration = int(cloned.get("source_timeline_end_us") or cloned.get("source_end_us") or 0) - int(cloned.get("source_timeline_start_us") or cloned.get("source_start_us") or 0)
        if duration <= 0:
            continue
        cloned["target_start_us"] = target_start
        cloned["target_duration_us"] = duration
        cloned["final_target_start_us"] = target_start
        cloned["final_target_duration_us"] = duration
        cloned["final_target_end_us"] = target_start + duration
        cloned["cut_start_us"] = int(cloned.get("source_timeline_start_us") or cloned.get("source_start_us") or 0)
        cloned["cut_end_us"] = int(cloned.get("source_timeline_end_us") or cloned.get("source_end_us") or 0)
        target_start += duration
        rebased.append(cloned)
    return rebased


def normalize_adjacent_source_overlaps(
    clips: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    normalized = [deepcopy(clip) for clip in clips]
    fixes: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []

    for index in range(len(normalized) - 1):
        left = normalized[index]
        right = normalized[index + 1]
        if str(left.get("source_material_id") or left.get("material_id") or "") != str(right.get("source_material_id") or right.get("material_id") or ""):
            continue
        left_end = int(left.get("source_timeline_end_us") or left.get("source_end_us") or 0)
        right_start = int(right.get("source_timeline_start_us") or right.get("source_start_us") or 0)
        left_material_end = int(left.get("material_end_us") or left_end)
        right_material_start = int(right.get("material_start_us") or right_start)
        overlap = left_material_end - right_material_start
        if overlap <= 0:
            continue
        source_overlap = left_end - right_start
        row = {
            "left_clip_id": left.get("clip_id"),
            "right_clip_id": right.get("clip_id"),
            "left_texts": left.get("subtitle_texts") or [],
            "right_texts": right.get("subtitle_texts") or [],
            "old_left_source_end_us": left_end,
            "old_right_source_start_us": right_start,
            "source_overlap_us": source_overlap,
            "old_left_material_end_us": left_material_end,
            "old_right_material_start_us": right_material_start,
            "material_overlap_us": overlap,
        }
        if overlap > MAX_SOURCE_OVERLAP_US:
            manual_review.append(row | {"reason": "source overlap exceeds safe auto-normalize threshold"})
            continue
        if source_overlap <= 0:
            manual_review.append(row | {"reason": "material overlap detected but source timeline has no overlap"})
            continue
        boundary = word_gap_boundary(word_timeline, right_start, left_end)
        if boundary is None:
            manual_review.append(row | {"reason": "no word gap boundary found inside source overlap"})
            continue
        if boundary <= int(left.get("source_start_us") or 0) or boundary >= int(right.get("source_end_us") or 0):
            manual_review.append(row | {"reason": "computed boundary would make a clip non-positive"})
            continue
        left["source_end_us"] = boundary
        left["source_timeline_end_us"] = boundary
        right["source_start_us"] = boundary
        right["source_timeline_start_us"] = boundary
        fixes.append(
            row
            | {
                "new_boundary_us": boundary,
                "new_left_source_end_us": boundary,
                "new_right_source_start_us": boundary,
                "reason": "normalize adjacent source overlap at nearest word gap",
            }
        )

    normalized = rebase_targets(normalized)
    report = {
        "adjacent_source_overlap_count": len(fixes) + len(manual_review),
        "fixed_count": len(fixes),
        "manual_review_count": len(manual_review),
        "fixes": fixes,
        "manual_review": manual_review,
    }
    return normalized, report
