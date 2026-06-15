from __future__ import annotations

from typing import Any


def summarize_subtitle_plan(plan: list[dict[str, Any]]) -> dict[str, Any]:
    reason_counts: dict[str, int] = {}
    cloned_count = 0
    empty_text_count = 0
    total_duration_us = 0
    for row in plan:
        reason = str(row.get("reason") or "unknown")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if row.get("requires_cloned_material"):
            cloned_count += 1
        if not str(row.get("fragment_text") or "").strip():
            empty_text_count += 1
        total_duration_us += int(row.get("target_duration_us") or 0)
    return {
        "fragment_count": len(plan),
        "requires_cloned_material_count": cloned_count,
        "empty_text_count": empty_text_count,
        "total_duration_us": total_duration_us,
        "reason_counts": reason_counts,
    }


def validate_subtitle_plan(plan: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    previous_end = 0
    for row in plan:
        fragment_id = str(row.get("fragment_id") or "")
        text = str(row.get("fragment_text") or "")
        start = int(row.get("target_start_us") or 0)
        duration = int(row.get("target_duration_us") or 0)
        if not text.strip():
            warnings.append(f"{fragment_id}: empty fragment_text")
        if duration <= 0:
            warnings.append(f"{fragment_id}: non-positive target_duration_us")
        if start < previous_end:
            warnings.append(f"{fragment_id}: target timeline overlap")
        previous_end = max(previous_end, start + duration)
    return warnings

