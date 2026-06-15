from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aroll_repair_applier import rebase_edl, set_clip_source_range
from aroll_safe_cut_boundary_gate import audit_safe_cut_boundaries


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _word_for_boundary(boundary_us: int, words: list[dict[str, Any]]) -> dict[str, Any] | None:
    for word in words:
        start = int(word.get("start_us") or 0)
        end = int(word.get("end_us") or 0)
        if start < boundary_us < end:
            return word
    return None


def _merge_overlapping_source_clips(clips: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    if not clips:
        return [], 0
    ordered = sorted(clips, key=lambda row: (int(row.get("source_start_us") or 0), int(row.get("source_end_us") or 0)))
    merged: list[dict[str, Any]] = [dict(ordered[0])]
    merge_count = 0
    for clip in ordered[1:]:
        current = merged[-1]
        cur_start = int(current.get("source_start_us") or 0)
        cur_end = int(current.get("source_end_us") or 0)
        start = int(clip.get("source_start_us") or 0)
        end = int(clip.get("source_end_us") or 0)
        current_material = str(current.get("source_material_id") or current.get("material_id") or "")
        clip_material = str(clip.get("source_material_id") or clip.get("material_id") or "")
        if start <= cur_end and (not current_material or not clip_material or current_material == clip_material):
            merged[-1] = set_clip_source_range(current, cur_start, max(cur_end, end))
            merged[-1]["source_reason"] = "safe_cut_boundary_merge_overlap"
            merge_count += 1
        else:
            merged.append(dict(clip))
    return merged, merge_count


def resolve_safe_cut_boundaries(
    *,
    final_edl: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
    output_path: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    before = audit_safe_cut_boundaries(word_timeline, final_edl=final_edl)
    words = sorted(word_timeline, key=lambda row: (int(row.get("start_us") or 0), int(row.get("end_us") or 0)))
    resolved: list[dict[str, Any]] = []
    expanded_left = 0
    expanded_right = 0
    unresolved: list[dict[str, Any]] = []

    for clip in final_edl:
        start = int(clip.get("source_start_us") or clip.get("source_timeline_start_us") or 0)
        end = int(clip.get("source_end_us") or clip.get("source_timeline_end_us") or 0)
        start_word = _word_for_boundary(start, words)
        end_word = _word_for_boundary(end, words)
        new_start = int(start_word.get("start_us")) if start_word else start
        new_end = int(end_word.get("end_us")) if end_word else end
        if new_start != start:
            expanded_left += 1
        if new_end != end:
            expanded_right += 1
        if new_end <= new_start:
            unresolved.append({"clip_id": clip.get("clip_id"), "source_start_us": start, "source_end_us": end, "reason": "resolved range is empty"})
            continue
        resolved.append(set_clip_source_range(clip, new_start, new_end))

    overlap_risk_before_merge = 0
    ordered = sorted(resolved, key=lambda row: (int(row.get("source_start_us") or 0), int(row.get("source_end_us") or 0)))
    for left, right in zip(ordered, ordered[1:]):
        if int(left.get("source_end_us") or 0) > int(right.get("source_start_us") or 0):
            overlap_risk_before_merge += 1
    merged, merge_count = _merge_overlapping_source_clips(ordered)
    repaired = rebase_edl(merged)
    after = audit_safe_cut_boundaries(word_timeline, final_edl=repaired)
    report = {
        "unsafe_boundary_before_count": int(before.get("unsafe_cut_boundary_count") or 0),
        "resolved_boundary_count": int(before.get("unsafe_cut_boundary_count") or 0) - int(after.get("unsafe_cut_boundary_count") or 0),
        "unresolved_boundary_count": int(after.get("unsafe_cut_boundary_count") or 0) + len(unresolved),
        "expanded_left_count": expanded_left,
        "expanded_right_count": expanded_right,
        "merged_adjacent_segment_count": merge_count,
        "introduced_repeat_risk_count": overlap_risk_before_merge,
        "safe_cut_boundary_resolver_passed": int(after.get("cut_inside_word_count") or 0) == 0 and not unresolved,
        "before": before,
        "after": after,
        "unresolved": unresolved,
    }
    if output_path:
        write_json(output_path, report)
    return repaired, report

