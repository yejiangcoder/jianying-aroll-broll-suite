from __future__ import annotations

from typing import Any

from aroll_v21.ir.models import FinalTimelineSegment


CUT_DENSITY_MIN_SEGMENT_COUNT = 10
CUT_DENSITY_WINDOW_US = 5_000_000
MAX_CUTS_PER_MINUTE = 30.0
MAX_CUTS_IN_5S = 5
MAX_BURST_CUT_COUNT = 0


def _cut_density_report_from_merge_report(
    merge_report: dict[str, Any],
    final_timeline: list[FinalTimelineSegment],
) -> dict[str, Any]:
    report = _cut_density_report(final_timeline)
    for key in ("cuts_per_minute", "max_cuts_in_5s", "burst_cut_count"):
        if key in merge_report:
            report[key] = merge_report[key]
    report["gate_passed"] = not _cut_density_failed(report)
    return report


def _cut_density_report(segments: list[FinalTimelineSegment]) -> dict[str, Any]:
    ordered = sorted(segments, key=lambda row: (int(row.target_start_us), int(row.target_end_us), row.segment_id))
    cut_times = [int(segment.target_start_us) for segment in ordered[1:]]
    timeline_start = min([int(segment.target_start_us) for segment in ordered] or [0])
    timeline_end = max([int(segment.target_end_us) for segment in ordered] or [0])
    duration_us = max(0, timeline_end - timeline_start)
    cuts_per_minute = round((len(cut_times) * 60_000_000 / duration_us), 4) if duration_us > 0 else 0.0
    max_cuts_in_window = 0
    burst_cut_count = 0
    for index, start in enumerate(cut_times):
        end = start + CUT_DENSITY_WINDOW_US
        count = 0
        for value in cut_times[index:]:
            if value >= end:
                break
            count += 1
        max_cuts_in_window = max(max_cuts_in_window, count)
        if count > MAX_CUTS_IN_5S:
            burst_cut_count += 1
    report = {
        "enabled": len(ordered) >= CUT_DENSITY_MIN_SEGMENT_COUNT,
        "cut_count": len(cut_times),
        "timeline_duration_us": duration_us,
        "cuts_per_minute": cuts_per_minute,
        "max_cuts_in_5s": max_cuts_in_window,
        "burst_cut_count": burst_cut_count,
        "thresholds": {
            "min_segment_count": CUT_DENSITY_MIN_SEGMENT_COUNT,
            "max_cuts_per_minute": MAX_CUTS_PER_MINUTE,
            "max_cuts_in_5s": MAX_CUTS_IN_5S,
            "max_burst_cut_count": MAX_BURST_CUT_COUNT,
            "window_us": CUT_DENSITY_WINDOW_US,
        },
    }
    report["gate_passed"] = not _cut_density_failed(report)
    return report


def _cut_density_failed(report: dict[str, Any]) -> bool:
    if not bool(report.get("enabled")):
        return False
    return (
        float(report.get("cuts_per_minute") or 0.0) > MAX_CUTS_PER_MINUTE
        or int(report.get("max_cuts_in_5s") or 0) > MAX_CUTS_IN_5S
        or int(report.get("burst_cut_count") or 0) > MAX_BURST_CUT_COUNT
    )


def _cut_density_blockers(report: dict[str, Any]) -> list[str]:
    if _cut_density_failed(report):
        return ["V21_VISUAL_CUT_DENSITY_FAILED"]
    no_blockers: list[str] = []
    return no_blockers
