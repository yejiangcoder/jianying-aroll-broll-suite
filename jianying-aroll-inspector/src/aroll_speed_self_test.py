from __future__ import annotations

from typing import Any

from aroll_inspect import segment_end, segment_start, timerange_duration, timerange_start
from aroll_speed_mapping import (
    material_time_to_source_timeline,
    source_timeline_to_material_time,
    source_to_target_delta,
)


TWO_FRAME_TOLERANCE_US = 80_000


def _segment_speed(segment: dict[str, Any]) -> float:
    source_duration = timerange_duration(segment.get("source_timerange") or {})
    target_duration = timerange_duration(segment.get("target_timerange") or {})
    if target_duration <= 0:
        return 1.0
    return float(source_duration) / float(target_duration)


def _sample_points(start: int, end: int, max_points: int = 5) -> list[int]:
    if end <= start:
        return []
    if max_points <= 1:
        return [start]
    step = (end - start) / (max_points - 1)
    return sorted({int(round(start + step * index)) for index in range(max_points)})


def run_speed_mapping_self_test(
    main_track: dict[str, Any],
    subtitles: list[dict[str, Any]] | None = None,
    max_allowed_speed: float = 1.25,
) -> dict[str, Any]:
    subtitles = subtitles or []
    segments = main_track.get("segments") or []
    segment_results: list[dict[str, Any]] = []
    sample_results: list[dict[str, Any]] = []
    fatal_reasons: list[str] = []
    max_roundtrip_error = 0
    max_duration_error = 0
    speed_values: list[float] = []

    for index, segment in enumerate(segments):
        target_start = segment_start(segment)
        target_end = segment_end(segment)
        source_start = timerange_start(segment.get("source_timerange") or {})
        source_duration = timerange_duration(segment.get("source_timerange") or {})
        target_duration = timerange_duration(segment.get("target_timerange") or {})
        speed = _segment_speed(segment)
        if not any(abs(speed - value) <= 0.0001 for value in speed_values):
            speed_values.append(speed)
        expected_target_duration = source_to_target_delta(source_duration, speed)
        duration_error = abs(expected_target_duration - target_duration)
        max_duration_error = max(max_duration_error, duration_error)
        if duration_error > TWO_FRAME_TOLERANCE_US:
            fatal_reasons.append("SPEED_MAPPING_DURATION_SELF_TEST_FAILED")
        if abs(speed) > max_allowed_speed:
            fatal_reasons.append("CONSTANT_SPEED_EXCEEDS_MAX_ALLOWED")
        for point in _sample_points(target_start, target_end, 5):
            material = source_timeline_to_material_time(point, target_start, source_start, speed)
            roundtrip = material_time_to_source_timeline(material, source_start, target_start, speed)
            error = abs(roundtrip - point)
            max_roundtrip_error = max(max_roundtrip_error, error)
            sample_results.append(
                {
                    "segment_index": index,
                    "source_timeline_time_us": point,
                    "material_time_us": material,
                    "roundtrip_source_timeline_time_us": roundtrip,
                    "roundtrip_error_us": error,
                    "speed": speed,
                }
            )
            if error > TWO_FRAME_TOLERANCE_US:
                fatal_reasons.append("SPEED_MAPPING_ROUNDTRIP_SELF_TEST_FAILED")
        segment_results.append(
            {
                "segment_index": index,
                "segment_id": segment.get("id"),
                "speed": speed,
                "target_start_us": target_start,
                "target_end_us": target_end,
                "source_start_us": source_start,
                "source_duration_us": source_duration,
                "target_duration_us": target_duration,
                "expected_target_duration_us": expected_target_duration,
                "duration_error_us": duration_error,
            }
        )

    subtitle_samples = []
    for row in subtitles[:5]:
        point = int(row.get("start_us") or 0)
        segment = next((seg for seg in segments if segment_start(seg) <= point <= segment_end(seg)), None)
        if not segment:
            continue
        target_start = segment_start(segment)
        source_start = timerange_start(segment.get("source_timerange") or {})
        speed = _segment_speed(segment)
        material = source_timeline_to_material_time(point, target_start, source_start, speed)
        roundtrip = material_time_to_source_timeline(material, source_start, target_start, speed)
        subtitle_samples.append(
            {
                "subtitle_index": row.get("subtitle_index"),
                "subtitle_text": row.get("subtitle_text"),
                "source_timeline_time_us": point,
                "material_time_us": material,
                "roundtrip_error_us": abs(roundtrip - point),
            }
        )
    if len(speed_values) > 1:
        fatal_reasons.append("MAIN_VIDEO_HAS_MIXED_SPEED")

    fatal_reasons = sorted(set(fatal_reasons))
    return {
        "segment_count": len(segments),
        "tested_segment_count": len(segment_results),
        "speed_values": speed_values,
        "constant_speed": speed_values[0] if len(speed_values) == 1 else None,
        "max_roundtrip_error_us": max_roundtrip_error,
        "max_duration_error_us": max_duration_error,
        "subtitle_sample_count": len(subtitle_samples),
        "passed": not fatal_reasons,
        "fatal_reasons": fatal_reasons,
        "segments": segment_results,
        "sample_points": sample_results[:200],
        "subtitle_samples": subtitle_samples,
    }
