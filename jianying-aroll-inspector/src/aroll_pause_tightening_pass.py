from __future__ import annotations

import json
import statistics
from copy import deepcopy
from pathlib import Path
from typing import Any


TARGET_KEEP_PAUSE_US = 220_000
MIN_SEGMENT_DURATION_US = 240_000


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def build_pause_tightening_candidates(
    postcut_audit: dict[str, Any],
    phase4c4_cut_plan: dict[str, Any],
    target_keep_pause_us: int = TARGET_KEEP_PAUSE_US,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for cut in phase4c4_cut_plan.get("cuts") or []:
        safety = cut.get("safety") or {}
        previous_keep = int(cut.get("kept_pause_us") or 0)
        speech_ratio = float(safety.get("speech_ratio") or 0)
        risk = str(safety.get("risk") or "high")
        if previous_keep <= target_keep_pause_us:
            rejected.append(
                {
                    "pause_id": cut.get("target_pause_id"),
                    "left_text": cut.get("left_text"),
                    "right_text": cut.get("right_text"),
                    "speech_ratio": speech_ratio,
                    "risk": risk,
                    "previous_keep_pause_us": previous_keep,
                    "new_keep_pause_us": previous_keep,
                    "planned_removed_us": 0,
                    "decision": "reject",
                    "reason": "already at or below target keep pause",
                }
            )
            continue
        if risk != "low" or speech_ratio >= 0.20:
            rejected.append(
                {
                    "pause_id": cut.get("target_pause_id"),
                    "left_text": cut.get("left_text"),
                    "right_text": cut.get("right_text"),
                    "speech_ratio": speech_ratio,
                    "risk": risk,
                    "previous_keep_pause_us": previous_keep,
                    "new_keep_pause_us": previous_keep,
                    "planned_removed_us": 0,
                    "decision": "manual_review",
                    "reason": "not low-risk enough for conservative tightening",
                }
            )
            continue
        planned_removed = previous_keep - target_keep_pause_us
        candidates.append(
            {
                "pause_id": cut.get("target_pause_id"),
                "cut_id": cut.get("cut_id"),
                "cut_type": cut.get("cut_type"),
                "source_clip_id": cut.get("source_clip_id"),
                "source_cut_intervals": cut.get("source_cut_intervals") or [],
                "target_start_us": None,
                "target_end_us": None,
                "duration_us": int(cut.get("target_removed_us") or 0) + previous_keep,
                "left_text": cut.get("left_text"),
                "right_text": cut.get("right_text"),
                "speech_ratio": speech_ratio,
                "risk": "low",
                "previous_keep_pause_us": previous_keep,
                "new_keep_pause_us": target_keep_pause_us,
                "planned_removed_us": planned_removed,
                "decision": "cut",
                "reason": f"tighten previously verified low-risk breath cut from {previous_keep // 1000}ms to {target_keep_pause_us // 1000}ms",
            }
        )

    # Current high-energy word gaps are explicitly rejected. They explain why
    # this pass is intentionally small.
    for pause in postcut_audit.get("pauses") or []:
        if pause.get("recommended_action") == "cut":
            continue
        if int(pause.get("duration_us") or 0) >= 120_000:
            rejected.append(
                {
                    "pause_id": pause.get("pause_id"),
                    "target_start_us": pause.get("target_start_us"),
                    "target_end_us": pause.get("target_end_us"),
                    "duration_us": pause.get("duration_us"),
                    "left_text": pause.get("left_text"),
                    "right_text": pause.get("right_text"),
                    "speech_ratio": pause.get("speech_ratio"),
                    "risk": "high" if float(pause.get("speech_ratio") or 0) >= 0.35 else "medium",
                    "previous_keep_pause_us": pause.get("duration_us"),
                    "new_keep_pause_us": pause.get("duration_us"),
                    "planned_removed_us": 0,
                    "decision": "reject",
                    "reason": "post-4C4 pause contains high energy or possible speech; do not tighten automatically",
                }
            )

    before = [int(row.get("previous_keep_pause_us") or 0) for row in candidates]
    after = [int(row.get("new_keep_pause_us") or 0) for row in candidates]
    return {
        "soft_pause_us": 120_000,
        "hard_pause_us": 180_000,
        "target_keep_pause_us": target_keep_pause_us,
        "复扫_pause_count": postcut_audit.get("detected_pause_count"),
        "candidate_pause_count": len(candidates),
        "actual_cut_count": len(candidates),
        "manual_review_count": sum(1 for row in rejected if row.get("decision") == "manual_review"),
        "rejected_count": len([row for row in rejected if row.get("decision") == "reject"]),
        "estimated_removed_pause_us": sum(int(row["planned_removed_us"]) for row in candidates),
        "estimated_removed_pause_s": round(sum(int(row["planned_removed_us"]) for row in candidates) / 1_000_000, 3),
        "average_pause_before_ms": round(statistics.mean(before) / 1000, 3) if before else 0,
        "average_pause_after_ms": round(statistics.mean(after) / 1000, 3) if after else 0,
        "candidates": candidates,
        "rejected": rejected,
        "top_10_compressed_pauses": sorted(candidates, key=lambda row: int(row["planned_removed_us"]), reverse=True)[:10],
    }


def _find_piece_ending_at(edl: list[dict[str, Any]], clip_id: str, source_end: int) -> dict[str, Any] | None:
    matches = [
        row for row in edl
        if str(row.get("parent_clip_id") or row.get("clip_id")) == clip_id
        and abs(int(row.get("source_end_us") or 0) - source_end) <= 2
    ]
    return matches[0] if matches else None


def _find_piece_starting_at(edl: list[dict[str, Any]], clip_id: str, source_start: int) -> dict[str, Any] | None:
    matches = [
        row for row in edl
        if str(row.get("parent_clip_id") or row.get("clip_id")) == clip_id
        and abs(int(row.get("source_start_us") or 0) - source_start) <= 2
    ]
    return matches[0] if matches else None


def apply_tightening_to_edl(edl: list[dict[str, Any]], candidate_report: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    new_edl = [deepcopy(row) for row in edl]
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for candidate in candidate_report.get("candidates") or []:
        planned_removed = int(candidate.get("planned_removed_us") or 0)
        if planned_removed <= 0:
            continue
        trim_left = planned_removed // 2
        trim_right = planned_removed - trim_left
        intervals = candidate.get("source_cut_intervals") or []
        if not intervals:
            skipped.append(candidate | {"skip_reason": "missing source_cut_intervals"})
            continue
        first = intervals[0]
        last = intervals[-1]
        left_piece = _find_piece_ending_at(new_edl, str(first.get("clip_id") or ""), int(first.get("source_cut_start_us") or 0))
        right_piece = _find_piece_starting_at(new_edl, str(last.get("clip_id") or ""), int(last.get("source_cut_end_us") or 0))
        if left_piece is None or right_piece is None:
            skipped.append(candidate | {"skip_reason": "adjacent edl pieces not found"})
            continue
        left_duration_after = int(left_piece["source_end_us"]) - int(left_piece["source_start_us"]) - trim_left
        right_duration_after = int(right_piece["source_end_us"]) - int(right_piece["source_start_us"]) - trim_right
        if left_duration_after < MIN_SEGMENT_DURATION_US or right_duration_after < MIN_SEGMENT_DURATION_US:
            skipped.append(candidate | {"skip_reason": "would make adjacent segment too short"})
            continue
        left_piece["source_end_us"] = int(left_piece["source_end_us"]) - trim_left
        left_piece["source_timeline_end_us"] = int(left_piece["source_end_us"])
        left_piece["cut_end_us"] = int(left_piece["source_end_us"])
        left_piece["material_start_us"] = None
        left_piece["material_end_us"] = None
        right_piece["source_start_us"] = int(right_piece["source_start_us"]) + trim_right
        right_piece["source_timeline_start_us"] = int(right_piece["source_start_us"])
        right_piece["cut_start_us"] = int(right_piece["source_start_us"])
        right_piece["material_start_us"] = None
        right_piece["material_end_us"] = None
        applied.append(candidate | {"trim_left_us": trim_left, "trim_right_us": trim_right})

    target_start = 0
    for row in sorted(new_edl, key=lambda item: int(item.get("target_start_us") or 0)):
        duration = int(row["source_end_us"]) - int(row["source_start_us"])
        if duration <= 0:
            raise RuntimeError(f"NON_POSITIVE_TIGHTENED_CLIP:{row.get('clip_id')}")
        row["target_start_us"] = target_start
        row["target_duration_us"] = duration
        row["final_target_start_us"] = target_start
        row["final_target_duration_us"] = duration
        row["final_target_end_us"] = target_start + duration
        row["source_timeline_start_us"] = int(row.get("source_start_us") or 0)
        row["source_timeline_end_us"] = int(row.get("source_end_us") or 0)
        row["source_reason"] = "phase4c5_pause_tightening"
        target_start += duration

    return new_edl, {
        "applied_count": len(applied),
        "skipped_count": len(skipped),
        "applied": applied,
        "skipped": skipped,
        "actual_removed_us": sum(int(row.get("planned_removed_us") or 0) for row in applied),
    }


def write_rejected_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Pause Tightening Rejected / Manual Review",
        "",
        "## Rejected current post-4C4 pauses",
    ]
    for row in report.get("rejected") or []:
        lines.append(
            f"- {row.get('pause_id')} | {row.get('left_text')} -> {row.get('right_text')} | "
            f"risk={row.get('risk')} speech_ratio={row.get('speech_ratio')} | {row.get('reason')}"
        )
    path.write_text("\n".join(lines) + "\n", "utf-8")
