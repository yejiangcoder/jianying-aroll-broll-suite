from __future__ import annotations

from copy import deepcopy
from typing import Any


AUDIO_ENHANCEMENT_KEYS = {
    "volume",
    "volume_value",
    "loudness",
    "loudnesses",
    "realtime_denoise",
    "realtime_denoises",
    "audio_fade",
    "audio_fades",
    "vocal_separation",
    "vocal_separations",
    "sound_channel_mapping",
    "audio_channel",
    "audio_effect",
    "audio_effects",
}


def has_key_deep(value: Any, keys: set[str]) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in keys:
                return True
            if has_key_deep(child, keys):
                return True
    elif isinstance(value, list):
        return any(has_key_deep(item, keys) for item in value)
    return False


def audio_enhancement_signature(value: Any, path: str = "") -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if str(key) in AUDIO_ENHANCEMENT_KEYS:
                fields[child_path] = child
            fields.update(audio_enhancement_signature(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            fields.update(audio_enhancement_signature(child, f"{path}[{index}]"))
    return fields


def inspect_audio_enhancement(
    data: dict[str, Any],
    selected_main_video_track: dict[str, Any] | None,
    audio_tracks: list[dict[str, Any]] | None = None,
    filter_tracks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tracks = data.get("tracks") or []
    selected_track_id = str((selected_main_video_track or {}).get("track_id") or "")
    selected_track = None
    for track in tracks:
        if str(track.get("id") or "") == selected_track_id:
            selected_track = track
            break

    video_segment_enhancement_detected = False
    enhanced_segment_ids: list[str] = []
    if selected_track:
        for segment in selected_track.get("segments") or []:
            if has_key_deep(segment, AUDIO_ENHANCEMENT_KEYS):
                video_segment_enhancement_detected = True
                enhanced_segment_ids.append(str(segment.get("id") or ""))

    independent_audio_track_count = len(audio_tracks or [])
    global_filter_or_audio_effect_detected = bool(filter_tracks)
    fatal_reasons: list[str] = []
    manual_review: list[str] = []
    if independent_audio_track_count:
        fatal_reasons.append("INDEPENDENT_AUDIO_TRACK_UNSUPPORTED")
    if global_filter_or_audio_effect_detected:
        manual_review.append("GLOBAL_FILTER_OR_EFFECT_PRESENT")

    return {
        "video_segment_audio_enhancement_detected": video_segment_enhancement_detected,
        "video_segment_audio_enhancement_allowed": True,
        "enhanced_video_segment_ids": enhanced_segment_ids,
        "independent_audio_track_count": independent_audio_track_count,
        "independent_audio_track_supported": independent_audio_track_count == 0,
        "global_audio_or_filter_detected": global_filter_or_audio_effect_detected,
        "global_audio_or_filter_supported": not global_filter_or_audio_effect_detected,
        "audio_track_supported": independent_audio_track_count == 0,
        "filter_track_supported": not global_filter_or_audio_effect_detected,
        "fatal_reasons": fatal_reasons,
        "manual_review": manual_review,
        "note": "Video segment/material volume or audio enhancement is allowed if segment objects are cloned during writeback.",
        "selected_track_sample": deepcopy(selected_track) if selected_track and video_segment_enhancement_detected else None,
    }


def build_audio_enhancement_preservation_report(
    old_segments: list[dict[str, Any]],
    new_segments: list[dict[str, Any]],
    video_split_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    def _int_value(value: Any, default: int) -> int:
        return default if value is None else int(value)

    old_by_id = {str(segment.get("id") or ""): segment for segment in old_segments if segment.get("id")}
    split_rows = video_split_rows or []
    checked: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    enhanced_count = 0
    for row in split_rows:
        old_id = str(row.get("old_segment_id") or "")
        old_segment = old_by_id.get(old_id)
        if not old_segment:
            continue
        old_sig = audio_enhancement_signature(old_segment)
        if not old_sig:
            continue
        enhanced_count += 1
        new_segment = next(
            (
                segment
                for segment in new_segments
                if _int_value((segment.get("target_timerange") or {}).get("start"), -1)
                == _int_value(row.get("new_target_start_us"), -2)
                and str(segment.get("material_id") or "") == str(row.get("material_id") or "")
            ),
            None,
        )
        new_sig = audio_enhancement_signature(new_segment or {})
        missing_keys = sorted(key for key in old_sig if key not in new_sig)
        checked.append({"old_segment_id": old_id, "new_target_start_us": row.get("new_target_start_us"), "old_key_count": len(old_sig), "missing_keys": missing_keys})
        if missing_keys:
            missing.append({"old_segment_id": old_id, "missing_keys": missing_keys})
    fatal_reasons = ["AUDIO_ENHANCEMENT_FIELDS_DROPPED"] if missing else []
    return {
        "audio_enhancement_detected_count": enhanced_count,
        "checked_split_count": len(checked),
        "clone_preservation_passed": not missing,
        "missing_field_rows": missing,
        "checked_rows": checked[:200],
        "fatal_reasons": fatal_reasons,
    }
