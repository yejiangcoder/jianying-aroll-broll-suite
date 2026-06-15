from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any


TARGET_KEEP_PAUSE_US = 220_000
SPEECH_PAD_LEFT_US = 100_000
SPEECH_PAD_RIGHT_US = 100_000
AUDIO_ISLAND_HALF_KEEP_US = TARGET_KEEP_PAUSE_US // 2


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def build_breath_cut_plan(audit: dict[str, Any]) -> dict[str, Any]:
    cuts: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []
    for pause in audit.get("pauses") or []:
        if pause.get("recommended_action") != "cut":
            if int(pause.get("duration_us") or 0) >= 220_000:
                manual_review.append(pause)
            continue
        duration = int(pause["duration_us"])
        left_word = pause.get("left_word") or {}
        right_word = pause.get("right_word") or {}
        left_clip = str(pause.get("source_clip_id_left") or "")
        right_clip = str(pause.get("source_clip_id_right") or "")
        pause_type = str(pause.get("pause_type") or "unknown")
        if pause.get("detection_source") == "audio_silence_island":
            source_intervals = [
                {
                    "clip_id": str(row.get("clip_id") or ""),
                    "source_start_us": int(row.get("source_start_us") or 0),
                    "source_end_us": int(row.get("source_end_us") or 0),
                }
                for row in (pause.get("source_intervals") or [])
                if int(row.get("source_end_us") or 0) > int(row.get("source_start_us") or 0)
            ]
            if not source_intervals:
                source_intervals = [
                    {
                        "clip_id": left_clip,
                        "source_start_us": int(pause.get("mapped_source_start_us") or 0),
                        "source_end_us": int(pause.get("mapped_source_end_us") or 0),
                    }
                ]
            cut_intervals: list[dict[str, Any]] = []
            for interval_index, interval in enumerate(source_intervals):
                start = int(interval["source_start_us"])
                end = int(interval["source_end_us"])
                cut_start = start
                cut_end = end
                if interval_index == 0:
                    cut_start += AUDIO_ISLAND_HALF_KEEP_US
                if interval_index == len(source_intervals) - 1:
                    cut_end -= AUDIO_ISLAND_HALF_KEEP_US
                if cut_end > cut_start:
                    cut_intervals.append(
                        {
                            "clip_id": interval["clip_id"],
                            "source_cut_start_us": cut_start,
                            "source_cut_end_us": cut_end,
                        }
                    )
            removed = sum(int(row["source_cut_end_us"]) - int(row["source_cut_start_us"]) for row in cut_intervals)
            if removed <= 0:
                manual_review.append(pause | {"reject_reason": "audio island too short after target keep"})
                continue
            if len({str(row["clip_id"]) for row in source_intervals}) == 1:
                cut_type = "split_clip_remove_internal_pause" if pause_type in {"intra_clip", "intra_subtitle_group"} else "trim_clip_edge"
                cuts.append(
                    {
                        "cut_id": f"bc_{len(cuts) + 1:03d}",
                        "target_pause_id": pause.get("pause_id"),
                        "cut_type": cut_type,
                        "source_clip_id": source_intervals[0]["clip_id"],
                        "source_cut_start_us": min(int(i["source_cut_start_us"]) for i in cut_intervals),
                        "source_cut_end_us": max(int(i["source_cut_end_us"]) for i in cut_intervals),
                        "source_cut_intervals": cut_intervals,
                        "target_removed_us": removed,
                        "kept_pause_us": max(0, duration - removed),
                        "safety": {
                            "left_pad_us": AUDIO_ISLAND_HALF_KEEP_US,
                            "right_pad_us": AUDIO_ISLAND_HALF_KEEP_US,
                            "speech_ratio": pause.get("speech_ratio"),
                            "risk": "low" if float(pause.get("speech_ratio") or 0) < 0.15 else "medium",
                        },
                        "left_text": pause.get("left_text"),
                        "right_text": pause.get("right_text"),
                    }
                )
                continue
            cuts.append(
                {
                    "cut_id": f"bc_{len(cuts) + 1:03d}",
                    "target_pause_id": pause.get("pause_id"),
                    "cut_type": "inter_clip_compress",
                    "source_clip_id": f"{left_clip}|{right_clip}",
                    "source_cut_start_us": min(int(i["source_cut_start_us"]) for i in cut_intervals),
                    "source_cut_end_us": max(int(i["source_cut_end_us"]) for i in cut_intervals),
                    "source_cut_intervals": cut_intervals,
                    "target_removed_us": removed,
                    "kept_pause_us": max(0, duration - removed),
                    "safety": {
                        "left_pad_us": AUDIO_ISLAND_HALF_KEEP_US,
                        "right_pad_us": AUDIO_ISLAND_HALF_KEEP_US,
                        "speech_ratio": pause.get("speech_ratio"),
                        "risk": "low" if float(pause.get("speech_ratio") or 0) < 0.15 else "medium",
                    },
                    "left_text": pause.get("left_text"),
                    "right_text": pause.get("right_text"),
                }
            )
            continue
        if left_clip == right_clip:
            source_start = int(left_word.get("source_end_us") or pause.get("mapped_source_start_us") or 0) + SPEECH_PAD_LEFT_US
            source_end = int(right_word.get("source_start_us") or pause.get("mapped_source_end_us") or source_start) - SPEECH_PAD_RIGHT_US
            if source_end <= source_start:
                manual_review.append(pause | {"reject_reason": "cut interval non-positive after safety pads"})
                continue
            cut_type = "split_clip_remove_internal_pause" if pause_type in {"intra_clip", "intra_subtitle_group"} else "trim_clip_edge"
            removed = source_end - source_start
            kept = max(0, duration - removed)
            cuts.append(
                {
                    "cut_id": f"bc_{len(cuts) + 1:03d}",
                    "target_pause_id": pause.get("pause_id"),
                    "cut_type": cut_type,
                    "source_clip_id": left_clip,
                    "source_cut_start_us": source_start,
                    "source_cut_end_us": source_end,
                    "target_removed_us": removed,
                    "kept_pause_us": kept,
                    "safety": {
                        "left_pad_us": SPEECH_PAD_LEFT_US,
                        "right_pad_us": SPEECH_PAD_RIGHT_US,
                        "speech_ratio": pause.get("speech_ratio"),
                        "risk": "low" if float(pause.get("speech_ratio") or 0) < 0.15 else "medium",
                    },
                    "left_text": pause.get("left_text"),
                    "right_text": pause.get("right_text"),
                }
            )
            continue
        # Inter-clip pause: trim tail from left clip and head from right clip.
        left_source_start = int(left_word.get("source_end_us") or pause.get("mapped_source_start_us") or 0) + SPEECH_PAD_LEFT_US
        right_source_end = int(right_word.get("source_start_us") or pause.get("mapped_source_end_us") or 0) - SPEECH_PAD_RIGHT_US
        removed = 0
        intervals: list[dict[str, Any]] = []
        if left_source_start < int(pause.get("mapped_source_end_us") or left_source_start):
            intervals.append({"clip_id": left_clip, "source_cut_start_us": left_source_start, "source_cut_end_us": int(pause.get("mapped_source_end_us") or left_source_start)})
        if int(pause.get("mapped_source_start_us") or right_source_end) < right_source_end:
            intervals.append({"clip_id": right_clip, "source_cut_start_us": int(pause.get("mapped_source_start_us") or right_source_end), "source_cut_end_us": right_source_end})
        for interval in intervals:
            removed += max(0, int(interval["source_cut_end_us"]) - int(interval["source_cut_start_us"]))
        if removed <= 0:
            manual_review.append(pause | {"reject_reason": "inter-clip cut interval non-positive"})
            continue
        cuts.append(
            {
                "cut_id": f"bc_{len(cuts) + 1:03d}",
                "target_pause_id": pause.get("pause_id"),
                "cut_type": "inter_clip_compress",
                "source_clip_id": f"{left_clip}|{right_clip}",
                "source_cut_start_us": min(int(i["source_cut_start_us"]) for i in intervals),
                "source_cut_end_us": max(int(i["source_cut_end_us"]) for i in intervals),
                "source_cut_intervals": intervals,
                "target_removed_us": removed,
                "kept_pause_us": max(0, duration - removed),
                "safety": {
                    "left_pad_us": SPEECH_PAD_LEFT_US,
                    "right_pad_us": SPEECH_PAD_RIGHT_US,
                    "speech_ratio": pause.get("speech_ratio"),
                    "risk": "low" if float(pause.get("speech_ratio") or 0) < 0.15 else "medium",
                },
                "left_text": pause.get("left_text"),
                "right_text": pause.get("right_text"),
            }
        )
    type_counts: dict[str, int] = {}
    for row in cuts:
        key = str(row.get("cut_type") or "")
        type_counts[key] = type_counts.get(key, 0) + 1
    removed_values = [int(row.get("target_removed_us") or 0) for row in cuts]
    before_values = [int(row.get("duration_us") or 0) for row in audit.get("pauses") or [] if int(row.get("duration_us") or 0) >= 140_000]
    after_values = []
    cut_by_pause = {str(row["target_pause_id"]): row for row in cuts}
    for pause in audit.get("pauses") or []:
        duration = int(pause.get("duration_us") or 0)
        if duration < 140_000:
            continue
        cut = cut_by_pause.get(str(pause.get("pause_id")))
        after_values.append(int(cut.get("kept_pause_us") or duration) if cut else duration)
    return {
        "breath_cut_count": len(cuts),
        "inter_clip_compress_count": type_counts.get("inter_clip_compress", 0),
        "split_clip_remove_internal_pause_count": type_counts.get("split_clip_remove_internal_pause", 0),
        "trim_clip_edge_count": type_counts.get("trim_clip_edge", 0),
        "manual_review_count": len(manual_review),
        "estimated_removed_pause_us": sum(removed_values),
        "estimated_removed_pause_s": round(sum(removed_values) / 1_000_000, 3),
        "average_pause_before_ms": round(statistics.mean(before_values) / 1000, 3) if before_values else 0,
        "average_pause_after_ms": round(statistics.mean(after_values) / 1000, 3) if after_values else 0,
        "cuts": cuts,
        "manual_review": manual_review,
    }


def intervals_by_clip(cut_plan: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_clip: dict[str, list[dict[str, Any]]] = {}
    for cut in cut_plan.get("cuts") or []:
        intervals = cut.get("source_cut_intervals") or [
            {
                "clip_id": cut.get("source_clip_id"),
                "source_cut_start_us": cut.get("source_cut_start_us"),
                "source_cut_end_us": cut.get("source_cut_end_us"),
            }
        ]
        for interval in intervals:
            clip_id = str(interval.get("clip_id") or "")
            if not clip_id:
                continue
            by_clip.setdefault(clip_id, []).append(
                {
                    "source_cut_start_us": int(interval["source_cut_start_us"]),
                    "source_cut_end_us": int(interval["source_cut_end_us"]),
                    "cut_id": cut.get("cut_id"),
                    "target_pause_id": cut.get("target_pause_id"),
                }
            )
    for rows in by_clip.values():
        rows.sort(key=lambda row: int(row["source_cut_start_us"]))
    return by_clip


def apply_breath_cuts_to_edl(clips: list[dict[str, Any]], cut_plan: dict[str, Any]) -> list[dict[str, Any]]:
    by_clip = intervals_by_clip(cut_plan)
    new_clips: list[dict[str, Any]] = []
    target_start = 0
    for clip in sorted(clips, key=lambda row: int(row.get("target_start_us") or 0)):
        clip_id = str(clip.get("clip_id") or "")
        source_start = int(clip["source_start_us"])
        source_end = int(clip["source_end_us"])
        cursor = source_start
        piece_index = 0
        for cut in by_clip.get(clip_id, []):
            cut_start = max(source_start, int(cut["source_cut_start_us"]))
            cut_end = min(source_end, int(cut["source_cut_end_us"]))
            if cut_end <= cut_start:
                continue
            if cut_start > cursor:
                piece_index += 1
                duration = cut_start - cursor
                new_clips.append(
                    clip | {
                        "clip_id": f"{clip_id}_p{piece_index:02d}",
                        "source_start_us": cursor,
                        "source_end_us": cut_start,
                        "source_timeline_start_us": cursor,
                        "source_timeline_end_us": cut_start,
                        "cut_start_us": cursor,
                        "cut_end_us": cut_start,
                        "target_start_us": target_start,
                        "target_duration_us": duration,
                        "final_target_start_us": target_start,
                        "final_target_duration_us": duration,
                        "final_target_end_us": target_start + duration,
                        "material_start_us": None,
                        "material_end_us": None,
                        "source_reason": "phase4c4_breath_cut",
                        "parent_clip_id": clip_id,
                    }
                )
                target_start += duration
            cursor = max(cursor, cut_end)
        if cursor < source_end:
            piece_index += 1
            duration = source_end - cursor
            new_clips.append(
                clip | {
                    "clip_id": f"{clip_id}_p{piece_index:02d}",
                    "source_start_us": cursor,
                    "source_end_us": source_end,
                    "source_timeline_start_us": cursor,
                    "source_timeline_end_us": source_end,
                    "cut_start_us": cursor,
                    "cut_end_us": source_end,
                    "target_start_us": target_start,
                    "target_duration_us": duration,
                    "final_target_start_us": target_start,
                    "final_target_duration_us": duration,
                    "final_target_end_us": target_start + duration,
                    "material_start_us": None,
                    "material_end_us": None,
                    "source_reason": "phase4c4_breath_cut",
                    "parent_clip_id": clip_id,
                }
            )
            target_start += duration
    return new_clips


def map_source_to_new_target(source_us: int, clips: list[dict[str, Any]]) -> int | None:
    # If source falls inside a removed breath interval, anchor to the nearest
    # following clip start. Subtitle starts/ends should normally be speech-boundary
    # times, so this is only a defensive fallback.
    for clip in clips:
        start = int(clip.get("source_timeline_start_us") or clip["source_start_us"])
        end = int(clip.get("source_timeline_end_us") or clip["source_end_us"])
        if start <= source_us <= end:
            return int(clip["target_start_us"]) + (source_us - start)
    future = [clip for clip in clips if int(clip.get("source_timeline_start_us") or clip["source_start_us"]) > source_us]
    if future:
        nearest = min(future, key=lambda row: int(row.get("source_timeline_start_us") or row["source_start_us"]))
        return int(nearest["target_start_us"])
    return None


def rebase_subtitle_plan(subtitle_plan: list[dict[str, Any]], clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rebased: list[dict[str, Any]] = []
    for row in subtitle_plan:
        source_start = int(row["source_start_us"])
        source_end = int(row["source_end_us"])
        target_start = map_source_to_new_target(source_start, clips)
        target_end = map_source_to_new_target(source_end, clips)
        if target_start is None or target_end is None:
            continue
        cloned = dict(row)
        cloned["target_start_us"] = target_start
        cloned["target_duration_us"] = max(0, target_end - target_start)
        cloned["reason"] = "phase4c4_rebased_grouped_subtitle"
        rebased.append(cloned)
    return rebased
