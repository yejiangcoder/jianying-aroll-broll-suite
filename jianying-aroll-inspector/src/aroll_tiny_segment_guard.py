from __future__ import annotations

import json
from pathlib import Path
from typing import Any


MIN_VIDEO_SEGMENT_US = 500_000
PREFERRED_MIN_VIDEO_SEGMENT_US = 700_000
MIN_SEMANTIC_BRIDGE_US = 350_000
WEAK_TINY_TEXT = {"啊", "呃", "嗯", "呐", "呢", "吧", "嘛", "就", "的", "是", "在", "这个", "那个", "然后"}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def compact_text(text: str) -> str:
    return "".join(str(text or "").split())


def row_text(row: dict[str, Any]) -> str:
    return str(row.get("fragment_text") or row.get("text") or row.get("subtitle_text") or "")


def is_allowed_semantic_bridge(
    clip: dict[str, Any],
    overlapping_subtitles: list[dict[str, Any]],
    duration_us: int,
) -> tuple[bool, str]:
    if duration_us < MIN_SEMANTIC_BRIDGE_US:
        return False, ""
    subtitle_texts = [compact_text(text) for text in (clip.get("subtitle_texts") or []) if compact_text(text)]
    if len(subtitle_texts) != 1:
        return False, ""
    text = subtitle_texts[0]
    if len(text) < 3 or len(text) > 6:
        return False, ""
    if text in WEAK_TINY_TEXT:
        return False, ""
    if overlapping_subtitles and not any(compact_text(row_text(row)) == text for row in overlapping_subtitles):
        return True, "short semantic bridge carried by video clip; subtitle interval was adjusted separately"
    return True, "short semantic bridge subtitle; keep instead of treating as artifact"


def audit_tiny_segments(
    final_edl: list[dict[str, Any]],
    display_plan: list[dict[str, Any]],
    min_segment_us: int = MIN_VIDEO_SEGMENT_US,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    allowed: list[dict[str, Any]] = []
    for clip in final_edl:
        duration = int(clip.get("target_duration_us") or 0)
        if duration >= min_segment_us:
            continue
        source_start = int(clip.get("source_start_us") or 0)
        source_end = int(clip.get("source_end_us") or 0)
        target_start = int(clip.get("target_start_us") or 0)
        target_end = target_start + duration
        overlapping_subtitles = [
            row for row in display_plan
            if int(row.get("target_start_us") or 0) < target_end
            and int(row.get("target_start_us") or 0) + int(row.get("target_duration_us") or 0) > target_start
        ]
        row = {
            "issue_id": f"tiny_{len(issues) + len(allowed) + 1:03d}",
            "issue_type": "tiny_artifact_segment",
            "clip_id": clip.get("clip_id"),
            "fragment_id": clip.get("fragment_id"),
            "source_start_us": source_start,
            "source_end_us": source_end,
            "target_start_us": target_start,
            "target_end_us": target_end,
            "duration_us": duration,
            "subtitle_texts": clip.get("subtitle_texts") or [],
            "overlapping_subtitle_ids": [item.get("fragment_id") for item in overlapping_subtitles],
            "confidence": "high",
            "recommended_action": "remove_tiny_artifact",
            "reason": f"video segment duration {duration}us is below {min_segment_us}us",
        }
        allow, allow_reason = is_allowed_semantic_bridge(clip, overlapping_subtitles, duration)
        if allow:
            row["confidence"] = "allowed"
            row["recommended_action"] = "keep_semantic_bridge"
            row["reason"] = allow_reason
            allowed.append(row)
            continue
        issues.append(row)
    return {
        "min_video_segment_us": min_segment_us,
        "preferred_min_video_segment_us": PREFERRED_MIN_VIDEO_SEGMENT_US,
        "tiny_segment_count": len(issues) + len(allowed),
        "unhandled_tiny_artifact_segment_count": len(issues),
        "unauthorized_segment_under_500ms": len(issues),
        "tiny_artifact_issues": issues,
        "allowed_tiny_segments": allowed,
        "min_segment_duration_us": min([int(row.get("target_duration_us") or 0) for row in final_edl], default=0),
    }
