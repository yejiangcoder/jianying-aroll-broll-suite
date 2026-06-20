from __future__ import annotations

from dataclasses import replace

from aroll_v21.ir.models import CanonicalSourceGraph, FinalTimelineSegment


def source_windows(source_graph: CanonicalSourceGraph) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    for row in source_graph.source_segments:
        if "video" not in str(row.get("track_type") or row.get("type") or "").lower():
            continue
        start = int(row.get("canonical_source_start_us") or row.get("target_start_us") or row.get("source_start_us") or 0)
        end = int(row.get("canonical_source_end_us") or row.get("target_end_us") or row.get("source_end_us") or 0)
        if end > start:
            windows.append((start, end))
    return sorted(set(windows))


def window_for_range(windows: list[tuple[int, int]], start: int, end: int) -> tuple[int, int] | None:
    matches = [window for window in windows if window[0] <= start and end <= window[1]]
    return matches[0] if len(matches) == 1 else None


def range_window_count(windows: list[tuple[int, int]], start: int, end: int) -> int:
    return sum(1 for window_start, window_end in windows if window_start <= int(start) and int(end) <= window_end)


def repack_segments(segments: list[FinalTimelineSegment]) -> list[FinalTimelineSegment]:
    cursor = 0
    repacked: list[FinalTimelineSegment] = []
    for index, segment in enumerate(segments, start=1):
        duration = max(0, int(segment.source_end_us) - int(segment.source_start_us))
        repacked.append(
            replace(
                segment,
                segment_id=f"v21_seg_{index:06d}",
                target_start_us=cursor,
                target_end_us=cursor + duration,
            )
        )
        cursor += duration
    return repacked


def repack_target_timeline(segments: list[FinalTimelineSegment]) -> list[FinalTimelineSegment]:
    repacked: list[FinalTimelineSegment] = []
    target_cursor = 0
    for index, segment in enumerate(segments, start=1):
        duration = segment.source_end_us - segment.source_start_us
        repacked.append(
            replace(
                segment,
                segment_id=f"v21_seg_{index:06d}",
                target_start_us=target_cursor,
                target_end_us=target_cursor + duration,
            )
        )
        target_cursor += duration
    return repacked
