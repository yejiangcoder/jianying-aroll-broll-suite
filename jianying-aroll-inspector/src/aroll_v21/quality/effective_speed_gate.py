from __future__ import annotations

from typing import Any

from aroll_v21.contracts import EffectiveSpeedGateReport, EffectiveSpeedSegmentReport, contract_to_dict
from aroll_v21.ir.models import FinalTimelineSegment


EFFECTIVE_SPEED_DRIFT_TOLERANCE = 0.01


def build_effective_speed_gate(
    *,
    final_timeline: list[FinalTimelineSegment],
    resolved_template_map: dict[str, Any],
    draft_data: dict[str, Any],
    speed_resolver: Any | None = None,
    tolerance: float = EFFECTIVE_SPEED_DRIFT_TOLERANCE,
) -> dict[str, Any]:
    from aroll_v21.writeback.speed_resolver import SpeedResolver
    from aroll_v21.writeback.video_write_plan_projector import (
        project_video_segment_from_template,
        safe_handle_report_from_projected_segments,
        timerange_duration,
    )

    resolver = speed_resolver or SpeedResolver(draft_data)
    segment_reports: list[EffectiveSpeedSegmentReport] = []
    expected_speeds: list[float] = []
    effective_speeds: list[float] = []
    projected_rows: list[dict[str, Any]] = []
    drift_count = 0
    missing_projection_count = 0
    if not final_timeline:
        blocker_codes = ["V21_EFFECTIVE_SPEED_PROJECTED_ROWS_MISSING"]
        payload = contract_to_dict(
            EffectiveSpeedGateReport(
                gate_passed=False,
                expected_speeds=[],
                effective_speed_min=None,
                effective_speed_max=None,
                effective_speed_drift_count=0,
                segment_reports=[],
                blocker_codes=blocker_codes,
            )
        )
        payload["effective_speed_projected_row_missing_count"] = 0
        payload["effective_speed_projected_row_count"] = 0
        payload.update(safe_handle_report_from_projected_segments(projected_rows))
        return payload
    for segment in final_timeline:
        binding = resolved_template_map.get(segment.segment_id) or {}
        template = binding.get("current_video_segment_template") if isinstance(binding, dict) else {}
        if not isinstance(template, dict) or not template:
            missing_projection_count += 1
            continue
        speed = float(resolver.resolve(template, draft_data).speed)
        expected_speeds.append(speed)
        projected = project_video_segment_from_template(template, segment, len(segment_reports) + 1, speed)
        projected_rows.append(projected)
        source_duration = timerange_duration(projected.get("source_timerange"))
        target_duration = timerange_duration(projected.get("target_timerange"))
        effective_speed = round(source_duration / target_duration, 6) if target_duration > 0 else None
        drift_ratio = None
        gate_passed = effective_speed is not None
        if effective_speed is not None:
            effective_speeds.append(effective_speed)
            drift_ratio = abs(effective_speed - speed) / speed if speed else None
            gate_passed = drift_ratio is not None and drift_ratio <= tolerance
        if not gate_passed:
            drift_count += 1
        segment_reports.append(
            EffectiveSpeedSegmentReport(
                segment_id=segment.segment_id,
                expected_speed=round(speed, 6),
                effective_speed=effective_speed,
                source_duration_us=source_duration,
                target_duration_us=target_duration,
                drift_ratio=round(drift_ratio, 6) if drift_ratio is not None else None,
                gate_passed=gate_passed,
            )
        )
    blocker_codes = []
    if drift_count:
        blocker_codes.append("V21_EFFECTIVE_SPEED_DRIFT")
    if missing_projection_count or (final_timeline and not segment_reports):
        blocker_codes.append("V21_EFFECTIVE_SPEED_PROJECTED_ROWS_MISSING")
    payload = contract_to_dict(
        EffectiveSpeedGateReport(
            gate_passed=not blocker_codes,
            expected_speeds=sorted(set(round(speed, 6) for speed in expected_speeds)),
            effective_speed_min=min(effective_speeds, default=None),
            effective_speed_max=max(effective_speeds, default=None),
            effective_speed_drift_count=drift_count,
            segment_reports=segment_reports,
            blocker_codes=blocker_codes,
        )
    )
    payload["effective_speed_projected_row_missing_count"] = missing_projection_count
    payload["effective_speed_projected_row_count"] = len(projected_rows)
    payload.update(safe_handle_report_from_projected_segments(projected_rows))
    return payload
