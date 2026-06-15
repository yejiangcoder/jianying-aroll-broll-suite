from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SAFE_EDGE_TOLERANCE_US = 40_000


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


def _inside_word(boundary_us: int, word: dict[str, Any] | None) -> bool:
    if not word:
        return False
    start = int(word.get("start_us") or 0)
    end = int(word.get("end_us") or 0)
    return (boundary_us - start) > SAFE_EDGE_TOLERANCE_US and (end - boundary_us) > SAFE_EDGE_TOLERANCE_US


def _drop_ranges(*plans: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for plan in plans:
        for row in plan.get("drop_decisions") or []:
            rows.append(
                {
                    "source": row.get("source") or "drop_decision",
                    "source_start_us": row.get("source_start_us"),
                    "source_end_us": row.get("source_end_us"),
                    "subtitle_index": row.get("subtitle_index"),
                    "text": row.get("drop_text"),
                    "decision_plan_candidate_id": row.get("decision_plan_candidate_id"),
                }
            )
        for row in plan.get("drop_segments") or []:
            rows.append(
                {
                    "source": "final_audit_drop_segment",
                    "source_start_us": row.get("source_start_us"),
                    "source_end_us": row.get("source_end_us"),
                    "subtitle_ids": row.get("subtitle_ids"),
                    "text": row.get("reason"),
                    "issue_id": row.get("issue_id"),
                }
            )
    return rows


def audit_safe_cut_boundaries(
    word_timeline: list[dict[str, Any]],
    *plans: dict[str, Any],
    final_edl: list[dict[str, Any]] | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    words = sorted(word_timeline, key=lambda row: (int(row.get("start_us") or 0), int(row.get("end_us") or 0)))
    cut_inside: list[dict[str, Any]] = []
    unsafe_final: list[dict[str, Any]] = []
    unsafe_drop: list[dict[str, Any]] = []
    min_left_pad: int | None = None
    min_right_pad: int | None = None
    drop_checked = 0
    final_checked = 0

    def check_boundary(row: dict[str, Any], side: str, boundary: int, bucket: list[dict[str, Any]]) -> None:
        nonlocal min_left_pad, min_right_pad
        word = _word_for_boundary(boundary, words)
        if not word:
            return
        left_pad = boundary - int(word.get("start_us") or 0)
        right_pad = int(word.get("end_us") or 0) - boundary
        min_left_pad = left_pad if min_left_pad is None else min(min_left_pad, left_pad)
        min_right_pad = right_pad if min_right_pad is None else min(min_right_pad, right_pad)
        if _inside_word(boundary, word):
            sample = row | {
                "boundary_side": side,
                "boundary_us": boundary,
                "word_id": word.get("word_id"),
                "word_text": word.get("word_text"),
                "word_start_us": word.get("start_us"),
                "word_end_us": word.get("end_us"),
                "left_pad_us": left_pad,
                "right_pad_us": right_pad,
            }
            bucket.append(sample)
            cut_inside.append(sample)

    for clip in final_edl or []:
        start = int(clip.get("source_start_us") or clip.get("source_timeline_start_us") or 0)
        end = int(clip.get("source_end_us") or clip.get("source_timeline_end_us") or 0)
        if end <= start:
            continue
        final_checked += 2
        check_boundary({"source": "final_edl", "clip_id": clip.get("clip_id"), "source_start_us": start, "source_end_us": end}, "left", start, unsafe_final)
        check_boundary({"source": "final_edl", "clip_id": clip.get("clip_id"), "source_start_us": start, "source_end_us": end}, "right", end, unsafe_final)

    for row in _drop_ranges(*plans):
        start = int(row.get("source_start_us") or 0)
        end = int(row.get("source_end_us") or 0)
        if end <= start:
            continue
        drop_checked += 2
        for side, boundary in (("left", start), ("right", end)):
            check_boundary(row, side, boundary, unsafe_drop)

    report = {
        "checked_cut_boundary_count": final_checked + drop_checked,
        "final_edl_boundary_checked_count": final_checked,
        "drop_plan_boundary_checked_count": drop_checked,
        "unsafe_cut_boundary_count": len(cut_inside),
        "cut_inside_word_count": len(cut_inside),
        "unsafe_final_edl_boundary_count": len(unsafe_final),
        "unsafe_drop_boundary_count": len(unsafe_drop),
        "min_left_pad_us": min_left_pad if min_left_pad is not None else 0,
        "min_right_pad_us": min_right_pad if min_right_pad is not None else 0,
        "safe_cut_boundary_gate_passed": len(cut_inside) == 0,
        "unsafe_boundary_samples": cut_inside[:100],
        "unsafe_final_edl_boundaries": unsafe_final[:100],
        "unsafe_drop_boundaries": unsafe_drop[:100],
    }
    if output_path:
        write_json(output_path, report)
    return report
