from __future__ import annotations

from typing import Any


def configure_writeback_dependencies(dependencies: dict[str, Any]) -> None:
    globals().update(dependencies)


def _segment_speed(self, segment: dict[str, Any], draft_data: dict[str, Any]) -> float:
    speed_report = segment.get("_resolved_speed_report")
    if isinstance(speed_report, dict) and speed_report.get("speed_safe") and speed_report.get("detected_speed") is not None:
        return float(speed_report.get("detected_speed") or 1.0)
    return SpeedResolver(draft_data).resolve(segment).speed


def _timerange_start(self, value: Any) -> int:
    return int(value.get("start") or 0) if isinstance(value, dict) else 0


def _timerange_duration(self, value: Any) -> int:
    return int(value.get("duration") or 0) if isinstance(value, dict) else 0


def _display_to_material_delta(self, display_delta_us: int, speed: float | int | str | None) -> int:
    return int(round(int(display_delta_us) * float(speed or 1.0)))


def _source_timeline_to_material_time(
    self,
    source_timeline_time_us: int,
    segment_target_start_us: int,
    segment_source_start_us: int,
    speed: float | int | str | None,
) -> int:
    display_offset = int(source_timeline_time_us) - int(segment_target_start_us)
    return int(segment_source_start_us) + self._display_to_material_delta(display_offset, speed)
