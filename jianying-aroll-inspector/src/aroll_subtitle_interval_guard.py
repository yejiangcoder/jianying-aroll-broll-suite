from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


MIN_SUBTITLE_DURATION_US = 500_000
SUBTITLE_GAP_US = 20_000
MAX_CHARS = 18
HARD_MAX_CHARS = 20
MAX_DURATION_US = 3_200_000
HARD_MAX_DURATION_US = 3_500_000


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def text_len(text: str) -> int:
    return len(str(text or "").strip())


def interval_rows(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in sorted(plan, key=lambda item: int(item.get("target_start_us") or 0)):
        start = int(row.get("target_start_us") or 0)
        duration = int(row.get("target_duration_us") or 0)
        rows.append(row | {"target_end_us": start + duration})
    return rows


def overlap_stats(plan: list[dict[str, Any]]) -> dict[str, Any]:
    rows = interval_rows(plan)
    overlaps = []
    for prev, curr in zip(rows, rows[1:]):
        overlap = int(prev["target_end_us"]) - int(curr["target_start_us"])
        if overlap > 0:
            overlaps.append(
                {
                    "prev_fragment_id": prev.get("fragment_id"),
                    "next_fragment_id": curr.get("fragment_id"),
                    "prev_text": prev.get("fragment_text"),
                    "next_text": curr.get("fragment_text"),
                    "overlap_us": overlap,
                }
            )
    return {
        "overlap_count": len(overlaps),
        "max_overlap_us": max([int(row["overlap_us"]) for row in overlaps], default=0),
        "overlaps": overlaps,
    }


def apply_subtitle_interval_guard(plan: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    before = overlap_stats(plan)
    rows = [deepcopy(row) for row in interval_rows(plan)]
    fixed_rows = []
    manual_review = []
    fixed_count = 0
    for idx, row in enumerate(rows):
        if fixed_rows:
            prev = fixed_rows[-1]
            prev_start = int(prev["target_start_us"])
            prev_end = prev_start + int(prev["target_duration_us"])
            row_start = int(row["target_start_us"])
            if prev_end + SUBTITLE_GAP_US > row_start:
                new_prev_duration = row_start - SUBTITLE_GAP_US - prev_start
                if new_prev_duration >= MIN_SUBTITLE_DURATION_US:
                    prev["target_duration_us"] = new_prev_duration
                    fixed_count += 1
                else:
                    merged_text = str(prev.get("fragment_text") or "") + str(row.get("fragment_text") or "")
                    merged_duration = int(row["target_start_us"]) + int(row["target_duration_us"]) - prev_start
                    if text_len(merged_text) <= HARD_MAX_CHARS and merged_duration <= HARD_MAX_DURATION_US:
                        prev["fragment_text"] = merged_text
                        prev["text"] = merged_text
                        prev["target_duration_us"] = merged_duration
                        prev["source_end_us"] = row.get("source_end_us", prev.get("source_end_us"))
                        prev["source_subtitle_indices"] = sorted(set((prev.get("source_subtitle_indices") or []) + (row.get("source_subtitle_indices") or [])))
                        prev["source_subtitle_uids"] = list(dict.fromkeys((prev.get("source_subtitle_uids") or []) + (row.get("source_subtitle_uids") or [])))
                        prev["word_ids"] = list(dict.fromkeys((prev.get("word_ids") or []) + (row.get("word_ids") or [])))
                        fixed_count += 1
                        continue
                    adjusted_start = prev_end + SUBTITLE_GAP_US
                    remaining = int(row["target_start_us"]) + int(row["target_duration_us"]) - adjusted_start
                    if remaining >= MIN_SUBTITLE_DURATION_US:
                        row["target_start_us"] = adjusted_start
                        row["target_duration_us"] = remaining
                        fixed_count += 1
                    else:
                        manual_review.append(
                            {
                                "prev_fragment_id": prev.get("fragment_id"),
                                "next_fragment_id": row.get("fragment_id"),
                                "reason": "cannot fix subtitle overlap without too-short subtitle",
                            }
                        )
        fixed_rows.append(row)
    fixed_rows.sort(key=lambda row: int(row.get("target_start_us") or 0))
    for idx, row in enumerate(fixed_rows, start=1):
        row["fragment_id"] = f"dsub_{idx:04d}"
        row.pop("target_end_us", None)
    after = overlap_stats(fixed_rows)
    duration_issues = [
        row for row in fixed_rows
        if int(row.get("target_duration_us") or 0) < MIN_SUBTITLE_DURATION_US
        or int(row.get("target_duration_us") or 0) > HARD_MAX_DURATION_US
        or text_len(str(row.get("fragment_text") or "")) > HARD_MAX_CHARS
    ]
    report = {
        "overlap_count_before": before["overlap_count"],
        "fixed_overlap_count": fixed_count,
        "overlap_count_after": after["overlap_count"],
        "manual_review_overlap_count": len(manual_review),
        "max_overlap_us_before": before["max_overlap_us"],
        "subtitle_interval_overlap_count": after["overlap_count"],
        "visual_lane_stacking_risk": after["overlap_count"] > 0 or bool(manual_review),
        "manual_review": manual_review,
        "duration_or_length_issue_count": len(duration_issues),
        "before_overlaps": before["overlaps"],
        "after_overlaps": after["overlaps"],
    }
    return fixed_rows, report
