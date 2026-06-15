from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aroll_repair_proposal import RepairProposal, proposal_to_dict


MIN_KEEP_PART_US = 80_000


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def word_map(word_timeline: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("word_id") or ""): row for row in word_timeline if str(row.get("word_id") or "")}


def source_range_for_word_ids(word_ids: list[str], words_by_id: dict[str, dict[str, Any]]) -> tuple[int, int]:
    starts: list[int] = []
    ends: list[int] = []
    for word_id in word_ids:
        word = words_by_id.get(str(word_id)) or {}
        start = int(word.get("start_us") or 0)
        end = int(word.get("end_us") or 0)
        if end > start:
            starts.append(start)
            ends.append(end)
    return (min(starts), max(ends)) if starts and ends else (0, 0)


def set_clip_source_range(clip: dict[str, Any], start: int, end: int) -> dict[str, Any]:
    out = dict(clip)
    out["source_start_us"] = start
    out["source_end_us"] = end
    out["cut_start_us"] = start
    out["cut_end_us"] = end
    out["source_timeline_start_us"] = start
    out["source_timeline_end_us"] = end
    return out


def rebase_edl(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    target = 0
    out: list[dict[str, Any]] = []
    for idx, clip in enumerate(clips, start=1):
        start = int(clip.get("source_start_us") or clip.get("source_timeline_start_us") or 0)
        end = int(clip.get("source_end_us") or clip.get("source_timeline_end_us") or 0)
        if end - start < MIN_KEEP_PART_US:
            continue
        cloned = set_clip_source_range(clip, start, end)
        duration = end - start
        cloned["clip_id"] = f"{clip.get('clip_id') or 'clip'}_r{idx:04d}"
        cloned["target_start_us"] = target
        cloned["target_duration_us"] = duration
        cloned["final_target_start_us"] = target
        cloned["final_target_duration_us"] = duration
        cloned["final_target_end_us"] = target + duration
        out.append(cloned)
        target += duration
    return out


def apply_source_drop_ranges_to_edl(
    final_edl: list[dict[str, Any]],
    drop_ranges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    normalized: list[tuple[int, int, dict[str, Any]]] = []
    for row in drop_ranges:
        start = int(row.get("source_start_us") or 0)
        end = int(row.get("source_end_us") or 0)
        if end > start:
            normalized.append((start, end, row))
    normalized.sort(key=lambda item: (item[0], item[1]))
    out: list[dict[str, Any]] = []
    split_count = 0
    removed_count = 0
    for clip in final_edl:
        clip_start = int(clip.get("source_start_us") or clip.get("source_timeline_start_us") or 0)
        clip_end = int(clip.get("source_end_us") or clip.get("source_timeline_end_us") or 0)
        parts = [(clip_start, clip_end)]
        for drop_start, drop_end, _row in normalized:
            next_parts: list[tuple[int, int]] = []
            for part_start, part_end in parts:
                if drop_end <= part_start or drop_start >= part_end:
                    next_parts.append((part_start, part_end))
                    continue
                if part_start < drop_start:
                    next_parts.append((part_start, max(part_start, drop_start)))
                if drop_end < part_end:
                    next_parts.append((min(part_end, drop_end), part_end))
                removed_count += 1
            parts = [(start, end) for start, end in next_parts if end - start >= MIN_KEEP_PART_US]
        if len(parts) > 1:
            split_count += len(parts) - 1
        for part_start, part_end in parts:
            out.append(set_clip_source_range(clip, part_start, part_end))
    return rebase_edl(out), {
        "drop_range_count": len(normalized),
        "removed_overlap_count": removed_count,
        "split_count": split_count,
    }


def _source_ranges_for_word_ids(word_ids: list[str], words_by_id: dict[str, dict[str, Any]]) -> list[tuple[int, int]]:
    word_rows: list[dict[str, Any]] = []
    for word_id in word_ids:
        word = words_by_id.get(str(word_id))
        if word:
            word_rows.append(word)
    word_rows.sort(key=lambda row: (int(row.get("start_us") or 0), int(row.get("end_us") or 0)))
    ranges: list[tuple[int, int]] = []
    for word in word_rows:
        start = int(word.get("start_us") or 0)
        end = int(word.get("end_us") or 0)
        if end <= start:
            continue
        if ranges and start <= ranges[-1][1] + 80_000:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))
    return ranges


def _proposal_remove_ranges(proposal: dict[str, Any], words_by_id: dict[str, dict[str, Any]]) -> tuple[list[tuple[int, int]], str]:
    word_ids = [str(word_id) for word_id in proposal.get("remove_word_ids") or [] if str(word_id)]
    if word_ids:
        ranges = _source_ranges_for_word_ids(word_ids, words_by_id)
        if ranges:
            return ranges, ""
        return [], "remove_word_ids_unmapped"
    start = proposal.get("remove_source_start_us")
    end = proposal.get("remove_source_end_us")
    if start is not None and end is not None and int(end) > int(start):
        return [(int(start), int(end))], ""
    return [], "missing_remove_range"


def apply_repair_proposals(
    *,
    final_edl: list[dict[str, Any]],
    display_subtitle_plan: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
    proposals: list[RepairProposal | dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    words_by_id = word_map(word_timeline)
    rows = [proposal_to_dict(proposal) for proposal in proposals]
    drop_ranges: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    conservative: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []

    for proposal in rows:
        repair_type = str(proposal.get("repair_type") or "")
        if repair_type == "conservative_keep":
            conservative.append(proposal)
            continue
        if repair_type == "block":
            blocked.append(proposal | {"block_reason": "proposal_requested_block"})
            continue
        if repair_type == "snap_boundary_to_word":
            conservative.append(proposal | {"note": "handled_by_safe_cut_boundary_resolver"})
            continue
        if repair_type not in {
            "remove_duplicate_word_island",
            "drop_contained_final_repeat",
            "overlap_merge_final_repeat",
        }:
            blocked.append(proposal | {"block_reason": "unknown_repair_type"})
            continue
        ranges, error = _proposal_remove_ranges(proposal, words_by_id)
        if error:
            blocked.append(proposal | {"block_reason": error})
            continue
        for start, end in ranges:
            drop_ranges.append(
                {
                    "source_start_us": start,
                    "source_end_us": end,
                    "proposal_id": proposal.get("proposal_id"),
                    "repair_type": repair_type,
                    "reason": proposal.get("reason"),
                }
            )
        applied.append(proposal | {"resolved_source_ranges": [{"source_start_us": start, "source_end_us": end} for start, end in ranges]})

    repaired_edl, edl_apply_report = apply_source_drop_ranges_to_edl(final_edl, drop_ranges)
    report = {
        "proposal_count": len(rows),
        "applied_count": len(applied),
        "skipped_conservative_keep_count": len(conservative),
        "blocked_count": len(blocked),
        "remove_range_count": len(drop_ranges),
        "unmapped_proposal_count": len([row for row in blocked if str(row.get("block_reason") or "").endswith("unmapped")]),
        "applier_passed": len(blocked) == 0,
        "applied_proposals": applied,
        "conservative_keep_proposals": conservative,
        "blocked_proposals": blocked,
        "drop_ranges": drop_ranges,
        "edl_apply_report": edl_apply_report,
    }
    return repaired_edl, report
