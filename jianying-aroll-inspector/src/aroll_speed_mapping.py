from __future__ import annotations


EPSILON = 0.0001


def normalize_speed(speed: float | int | str | None) -> float:
    if speed is None:
        return 1.0
    try:
        value = float(speed)
    except Exception as exc:
        raise ValueError(f"INVALID_SPEED:{speed}") from exc
    if abs(value) <= EPSILON:
        raise ValueError("INVALID_ZERO_SPEED")
    return value


def is_one_x(speed: float | int | str | None) -> bool:
    return abs(normalize_speed(speed) - 1.0) <= EPSILON


def source_to_target_delta(source_delta_us: int, speed: float | int | str | None) -> int:
    value = normalize_speed(speed)
    return int(round(int(source_delta_us) / value))


def target_to_source_delta(target_delta_us: int, speed: float | int | str | None) -> int:
    value = normalize_speed(speed)
    return int(round(int(target_delta_us) * value))


def display_to_material_delta(display_delta_us: int, speed: float | int | str | None) -> int:
    return target_to_source_delta(display_delta_us, speed)


def material_to_display_delta(material_delta_us: int, speed: float | int | str | None) -> int:
    return source_to_target_delta(material_delta_us, speed)


def material_source_to_timeline_source(
    material_source_us: int,
    segment_source_start_us: int = 0,
    segment_target_start_us: int = 0,
    speed: float | int | str | None = 1.0,
) -> int:
    source_delta = int(material_source_us) - int(segment_source_start_us)
    return int(segment_target_start_us) + source_to_target_delta(source_delta, speed)


def timeline_source_to_material_source(
    timeline_source_us: int,
    segment_source_start_us: int = 0,
    segment_target_start_us: int = 0,
    speed: float | int | str | None = 1.0,
) -> int:
    target_delta = int(timeline_source_us) - int(segment_target_start_us)
    return int(segment_source_start_us) + target_to_source_delta(target_delta, speed)


def source_timeline_to_material_time(
    source_timeline_time_us: int,
    segment_target_start_us: int,
    segment_source_start_us: int,
    speed: float | int | str | None,
) -> int:
    display_offset = int(source_timeline_time_us) - int(segment_target_start_us)
    return int(segment_source_start_us) + display_to_material_delta(display_offset, speed)


def material_time_to_source_timeline(
    material_time_us: int,
    segment_source_start_us: int,
    segment_target_start_us: int,
    speed: float | int | str | None,
) -> int:
    material_offset = int(material_time_us) - int(segment_source_start_us)
    return int(segment_target_start_us) + material_to_display_delta(material_offset, speed)


def edl_display_duration_us(clip: dict) -> int:
    return int(clip.get("source_timeline_end_us") or clip.get("source_end_us") or 0) - int(
        clip.get("source_timeline_start_us") or clip.get("source_start_us") or 0
    )


def ensure_clip_time_fields(clip: dict, speed: float | int | str | None = 1.0) -> dict:
    source_start = int(clip.get("source_timeline_start_us") or clip.get("source_start_us") or clip.get("cut_start_us") or 0)
    source_end = int(clip.get("source_timeline_end_us") or clip.get("source_end_us") or clip.get("cut_end_us") or source_start)
    material_start = int(clip.get("material_start_us") if clip.get("material_start_us") is not None else source_start)
    material_end = int(clip.get("material_end_us") if clip.get("material_end_us") is not None else material_start + display_to_material_delta(source_end - source_start, speed))
    final_start = int(clip.get("final_target_start_us") or clip.get("target_start_us") or 0)
    final_duration = int(clip.get("final_target_duration_us") or clip.get("target_duration_us") or (source_end - source_start))
    clip["source_timeline_start_us"] = source_start
    clip["source_timeline_end_us"] = source_end
    clip["material_start_us"] = material_start
    clip["material_end_us"] = material_end
    clip["speed"] = normalize_speed(speed)
    clip["final_target_start_us"] = final_start
    clip["final_target_duration_us"] = final_duration
    clip["final_target_end_us"] = final_start + final_duration
    clip["target_start_us"] = final_start
    clip["target_duration_us"] = final_duration
    clip["source_start_us"] = source_start
    clip["source_end_us"] = source_end
    clip["cut_start_us"] = source_start
    clip["cut_end_us"] = source_end
    return clip
