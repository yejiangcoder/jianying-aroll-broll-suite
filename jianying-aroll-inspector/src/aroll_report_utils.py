from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any


def write_decision_merge_report(path: Path, merge_report: dict[str, Any], selected_rows: list[dict[str, Any]]) -> None:
    if isinstance(merge_report, str):
        lines = [merge_report.rstrip(), "", "## Selected rows preview"]
        for row in selected_rows[:30]:
            lines.append(f"- {row.get('subtitle_index')}: {row.get('text')}")
        path.write_text("\n".join(lines) + "\n", "utf-8")
        return
    lines = [
        "# A-Roll Decision Merge Report",
        "",
        f"- merged_count: {merge_report.get('merged_count')}",
        f"- drop_count: {merge_report.get('drop_count')}",
        f"- micro_cleanup_count: {merge_report.get('micro_cleanup_count')}",
        f"- selected_row_count: {len(selected_rows)}",
        "",
        "## Selected rows preview",
    ]
    for row in selected_rows[:30]:
        lines.append(f"- {row.get('subtitle_index')}: {row.get('text')}")
    path.write_text("\n".join(lines) + "\n", "utf-8")


def _clip_piece_too_short(start_us: int, end_us: int, cut_start: int, cut_end: int, min_piece_us: int) -> bool:
    left = cut_start - start_us
    right = end_us - cut_end
    return (0 < left < min_piece_us) or (0 < right < min_piece_us)


def filter_breath_plan_for_min_pieces(
    raw_plan: dict[str, Any],
    edl: list[dict[str, Any]],
    min_piece_us: int,
) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for cut in raw_plan.get("cuts") or []:
        cut_start = int(cut.get("source_cut_start_us") or 0)
        cut_end = int(cut.get("source_cut_end_us") or 0)
        if cut_end <= cut_start:
            rejected.append(cut | {"reject_reason": "non_positive_cut"})
            continue
        clip = next(
            (
                row
                for row in edl
                if int(row.get("source_start_us") or 0) <= cut_start and int(row.get("source_end_us") or 0) >= cut_end
            ),
            None,
        )
        if not clip:
            rejected.append(cut | {"reject_reason": "no_containing_clip"})
            continue
        if _clip_piece_too_short(int(clip["source_start_us"]), int(clip["source_end_us"]), cut_start, cut_end, min_piece_us):
            rejected.append(cut | {"reject_reason": "would_create_tiny_piece"})
            continue
        accepted.append(cut)
    durations = [int(row.get("source_cut_end_us") or 0) - int(row.get("source_cut_start_us") or 0) for row in accepted]
    return {
        "breath_cut_count": len(accepted),
        "cuts": accepted,
        "rejected_count": len(rejected),
        "rejected": rejected,
        "removed_duration_us": sum(durations),
        "median_cut_us": int(statistics.median(durations)) if durations else 0,
    }
