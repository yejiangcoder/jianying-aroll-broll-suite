from __future__ import annotations

from typing import Any

from aroll_v21.quality.visual_pacing.intra_segment_gap import empty_large_intra_segment_gap_report


SEMANTIC_BRIDGE_SHORT_SEGMENT_CAP = 8


def configure_visual_pacing_report_dependencies(dependencies: dict[str, Any]) -> None:
    globals().update(dependencies)

def _reason_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        reason = str(row.get("merge_candidate_reason") or row.get("short_segment_status") or "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))



def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return int(round(ordered[lower] * (1 - weight) + ordered[upper] * weight))


def build_visual_pacing_report(
    *,
    final_timeline: list[FinalTimelineSegment],
    captions: list[CaptionRenderUnit],
    executed: bool = False,
    merge_report: dict[str, Any] | None = None,
    source_graph: CanonicalSourceGraph | None = None,
) -> dict[str, Any]:
    merge_report = dict(merge_report or {})
    timeline_changed_after_visual_pacing = int(merge_report.get("final_visible_repair_action_count") or 0) > 0
    before_short = int(merge_report.get("visual_short_segment_count_lt_1200ms_before") or _short_count(final_timeline))
    after_short = (
        _short_count(final_timeline)
        if timeline_changed_after_visual_pacing
        else int(merge_report.get("visual_short_segment_count_lt_1200ms_after") or _short_count(final_timeline))
    )
    semantic_bridge_count = (
        sum(1 for segment in final_timeline if _is_allowed_semantic_bridge_exception(segment))
        if timeline_changed_after_visual_pacing
        else int(
            merge_report.get("semantic_bridge_short_segment_count")
            or sum(1 for segment in final_timeline if _is_allowed_semantic_bridge_exception(segment))
        )
    )
    if timeline_changed_after_visual_pacing:
        blocking_short_count = _blocking_short_count(final_timeline)
    elif merge_report.get("visual_short_segment_count_lt_1200ms_after_blocking") is not None:
        blocking_short_count = int(merge_report.get("visual_short_segment_count_lt_1200ms_after_blocking") or 0)
    elif merge_report.get("semantic_bridge_short_segment_count") is not None:
        blocking_short_count = max(0, after_short - semantic_bridge_count)
    else:
        blocking_short_count = _blocking_short_count(final_timeline)
    allowed_blocking_short_count = int(
        merge_report.get("visual_pacing_allowed_short_segment_threshold")
        if isinstance(merge_report.get("visual_pacing_allowed_short_segment_threshold"), int)
        else _allowed_blocking_short_count(final_timeline)
    )
    blocker_codes = [] if timeline_changed_after_visual_pacing else list(merge_report.get("visual_pacing_blocker_codes") or [])
    safety_report = (
        _build_visual_merge_safety_report(final_timeline, source_graph, unsafe_merge_attempt_count=0)
        if timeline_changed_after_visual_pacing and source_graph is not None
        else _safety_report_from_merge_report(merge_report, final_timeline, captions)
    )
    if not executed:
        blocker_codes.append("V21_VISUAL_PACING_NOT_EXECUTED")
    unsafe_merge_attempt_count = int(
        safety_report.get("visual_pacing_blocked_unsafe_merge_attempt_count")
        or merge_report.get("visual_pacing_blocked_unsafe_merge_attempt_count")
        or 0
    )
    if _short_segments_exceed_gate_limit(
        blocking_short_count=blocking_short_count,
        allowed_blocking_short_count=allowed_blocking_short_count,
        unsafe_merge_attempt_count=unsafe_merge_attempt_count,
    ):
        blocker_codes.append("V21_VISUAL_PACING_SHORT_SEGMENTS_REMAIN")
    if not bool(safety_report.get("gate_passed")):
        blocker_codes.extend(str(code) for code in safety_report.get("blocker_codes") or [])
    semantic_bridge_cap = _semantic_bridge_segment_cap(len(final_timeline))
    if timeline_changed_after_visual_pacing and source_graph is not None:
        safe_merge_candidates = _semantic_bridge_safe_merge_candidates(final_timeline, source_graph)
    elif timeline_changed_after_visual_pacing:
        safe_merge_candidates = []
    else:
        safe_merge_candidates = list(merge_report.get("semantic_bridge_safe_merge_candidates") or [])
    blocker_codes.extend(
        _semantic_bridge_gate_blockers(
            semantic_bridge_count=semantic_bridge_count,
            semantic_bridge_cap=semantic_bridge_cap,
            safe_merge_candidate_count=len(safe_merge_candidates),
        )
    )
    cut_density_report = _cut_density_report_from_merge_report(merge_report, final_timeline)
    large_intra_segment_gap_report = dict(
        merge_report.get("large_intra_segment_gap_report")
        or {
            "large_intra_segment_gap_candidate_count": merge_report.get("large_intra_segment_gap_candidate_count"),
            "large_intra_segment_gap_split_count": merge_report.get("large_intra_segment_gap_split_count"),
            "large_intra_segment_gap_unsafe_count": merge_report.get("large_intra_segment_gap_unsafe_count"),
            "large_intra_segment_gap_max_us": merge_report.get("large_intra_segment_gap_max_us"),
            "large_intra_segment_gap_normal_breath_us": merge_report.get("large_intra_segment_gap_normal_breath_us"),
            "large_intra_segment_gap_threshold_us": merge_report.get("large_intra_segment_gap_threshold_us"),
            "large_intra_segment_gap_min_split_side_duration_us": merge_report.get(
                "large_intra_segment_gap_min_split_side_duration_us"
            ),
            "large_intra_segment_gap_candidates": merge_report.get("large_intra_segment_gap_candidates"),
            "large_intra_segment_gap_splits": merge_report.get("large_intra_segment_gap_splits"),
        }
    )
    blocker_codes.extend(_cut_density_blockers(cut_density_report))
    return _visual_report(
        final_timeline=final_timeline,
        captions=captions,
        gate_passed=not blocker_codes,
        executed=executed,
        attempted=int(merge_report.get("visual_pacing_merge_attempted_count") or 0),
        merged=int(merge_report.get("visual_pacing_merged_count") or 0),
        before_short=before_short,
        after_short=after_short,
        semantic_bridge_count=semantic_bridge_count,
        blocker_codes=sorted(set(blocker_codes)),
        hidden_repeat_dropped_word_count=int(merge_report.get("visual_pacing_hidden_repeat_dropped_word_count") or 0),
        hidden_repeat_split_segment_count=int(merge_report.get("visual_pacing_hidden_repeat_split_segment_count") or 0),
        boundary_overlap_dropped_word_count=int(merge_report.get("visual_pacing_boundary_overlap_dropped_word_count") or 0),
        safety_report=safety_report,
        blocking_short_count=blocking_short_count,
        allowed_blocking_short_count=allowed_blocking_short_count,
        dropped_weak_filler_count=int(merge_report.get("visual_pacing_weak_filler_dropped_count") or 0),
        merged_weak_filler_micro_segment_count=int(merge_report.get("merged_weak_filler_micro_segment_count") or 0),
        dropped_weak_filler_micro_segment_count=int(merge_report.get("dropped_weak_filler_micro_segment_count") or 0),
        padded_short_count=int(merge_report.get("visual_pacing_residual_short_padded_count") or 0),
        semantic_bridge_cap=semantic_bridge_cap,
        semantic_bridge_safe_merge_candidates=safe_merge_candidates,
        cut_density_report=cut_density_report,
        large_intra_segment_gap_report=large_intra_segment_gap_report,
    )


def _visual_report(
    *,
    final_timeline: list[FinalTimelineSegment],
    captions: list[CaptionRenderUnit],
    gate_passed: bool,
    executed: bool,
    attempted: int,
    merged: int,
    before_short: int,
    after_short: int,
    semantic_bridge_count: int,
    blocker_codes: list[str],
    hidden_repeat_dropped_word_count: int = 0,
    hidden_repeat_split_segment_count: int = 0,
    boundary_overlap_dropped_word_count: int = 0,
    safety_report: dict[str, Any] | None = None,
    blocking_short_count: int | None = None,
    allowed_blocking_short_count: int | None = None,
    dropped_weak_filler_count: int = 0,
    merged_weak_filler_micro_segment_count: int = 0,
    dropped_weak_filler_micro_segment_count: int = 0,
    padded_short_count: int = 0,
    semantic_bridge_cap: int = SEMANTIC_BRIDGE_SHORT_SEGMENT_CAP,
    semantic_bridge_safe_merge_candidates: list[dict[str, Any]] | None = None,
    cut_density_report: dict[str, Any] | None = None,
    large_intra_segment_gap_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    durations = [_duration(segment) for segment in final_timeline]
    ratio = round(len(captions) / len(final_timeline), 4) if final_timeline else 0.0
    safety_for_residuals = safety_report or _empty_safety_report()
    safe_merge_candidates = list(semantic_bridge_safe_merge_candidates or [])
    cut_density = cut_density_report or _cut_density_report(final_timeline)
    intra_gap = empty_large_intra_segment_gap_report()
    intra_gap.update({key: value for key, value in dict(large_intra_segment_gap_report or {}).items() if value is not None})
    residual_short_segments = _residual_visual_short_segments(
        final_timeline,
        safety_for_residuals,
        semantic_bridge_safe_merge_candidates=safe_merge_candidates,
    )
    semantic_bridge_details = [row for row in residual_short_segments if bool(row.get("semantic_bridge"))]
    report = contract_to_dict(
        VisualPacingReport(
            gate_passed=gate_passed,
            final_video_segment_count=len(final_timeline),
            caption_count=len(captions),
            visual_short_segment_count_lt_1200ms=after_short,
            median_segment_duration_us=int(median(durations)) if durations else 0,
            p10_segment_duration_us=_percentile(durations, 10),
            caption_per_video_segment_ratio=ratio,
            blocker_codes=sorted(set(blocker_codes)),
        )
    )
    report.update(
        {
            "visual_pacing_executed": executed,
            "visual_pacing_merge_attempted_count": attempted,
            "visual_pacing_merged_count": merged,
            "visual_short_segment_count_lt_1200ms_before": before_short,
            "visual_short_segment_count_lt_1200ms_after": after_short,
            "visual_short_segment_count_lt_1200ms_after_blocking": _blocking_short_count(final_timeline)
            if blocking_short_count is None
            else int(blocking_short_count),
            "semantic_bridge_short_segment_count": semantic_bridge_count,
            "visual_pacing_allowed_short_segment_threshold": _allowed_blocking_short_count(final_timeline)
            if allowed_blocking_short_count is None
            else int(allowed_blocking_short_count),
            "visual_pacing_allowed_short_segment_policy": "explicit_semantic_bridge_only",
            "visual_pacing_blocker_codes": sorted(set(blocker_codes)),
            "visual_pacing_hidden_repeat_dropped_word_count": hidden_repeat_dropped_word_count,
            "visual_pacing_hidden_repeat_split_segment_count": hidden_repeat_split_segment_count,
            "visual_pacing_boundary_overlap_dropped_word_count": boundary_overlap_dropped_word_count,
            "visual_pacing_weak_filler_dropped_count": int(dropped_weak_filler_count),
            "merged_weak_filler_micro_segment_count": int(merged_weak_filler_micro_segment_count),
            "dropped_weak_filler_micro_segment_count": int(dropped_weak_filler_micro_segment_count),
            "visual_pacing_residual_short_padded_count": int(padded_short_count),
            "residual_visual_short_segments": residual_short_segments,
            "semantic_bridge_short_segment_details": semantic_bridge_details,
            "semantic_bridge_reason_counts": _reason_counts(semantic_bridge_details),
            "semantic_bridge_cap": int(semantic_bridge_cap),
            "semantic_bridge_safe_merge_candidate_count": len(safe_merge_candidates),
            "semantic_bridge_safe_merge_candidates": safe_merge_candidates,
            "cuts_per_minute": float(cut_density.get("cuts_per_minute") or 0.0),
            "max_cuts_in_5s": int(cut_density.get("max_cuts_in_5s") or 0),
            "burst_cut_count": int(cut_density.get("burst_cut_count") or 0),
            "cut_density_gate_enabled": bool(cut_density.get("enabled")),
            "cut_density_gate_passed": bool(cut_density.get("gate_passed")),
            "cut_density_thresholds": dict(cut_density.get("thresholds") or {}),
            "cut_density_window_us": CUT_DENSITY_WINDOW_US,
            "large_intra_segment_gap_candidate_count": int(intra_gap.get("large_intra_segment_gap_candidate_count") or 0),
            "large_intra_segment_gap_split_count": int(intra_gap.get("large_intra_segment_gap_split_count") or 0),
            "large_intra_segment_gap_unsafe_count": int(intra_gap.get("large_intra_segment_gap_unsafe_count") or 0),
            "large_intra_segment_gap_max_us": int(intra_gap.get("large_intra_segment_gap_max_us") or 0),
            "large_intra_segment_gap_normal_breath_us": int(intra_gap.get("large_intra_segment_gap_normal_breath_us") or 0),
            "large_intra_segment_gap_threshold_us": int(intra_gap.get("large_intra_segment_gap_threshold_us") or 0),
            "large_intra_segment_gap_min_split_side_duration_us": int(
                intra_gap.get("large_intra_segment_gap_min_split_side_duration_us") or 0
            ),
            "large_intra_segment_gap_candidates": list(intra_gap.get("large_intra_segment_gap_candidates") or []),
            "large_intra_segment_gap_splits": list(intra_gap.get("large_intra_segment_gap_splits") or []),
            "large_intra_segment_gap_report": intra_gap,
        }
    )
    safety_report = _safety_report_with_caption_ids(safety_report or _empty_safety_report(), captions)
    report.update(
        {
            "visual_merge_safety_gate_passed": bool(safety_report.get("gate_passed")),
            "unsafe_merge_group_count": int(safety_report.get("unsafe_merge_group_count") or 0),
            "dropped_content_reintroduced_count": int(safety_report.get("dropped_content_reintroduced_count") or 0),
            "max_bridged_gap_us": int(safety_report.get("max_bridged_gap_us") or 0),
            "total_bridged_gap_us": int(safety_report.get("total_bridged_gap_us") or 0),
            "unspoken_bridge_ratio": float(safety_report.get("unspoken_bridge_ratio") or 0.0),
            "visual_merge_safety_report": safety_report,
            "visual_merge_groups": list(safety_report.get("merge_groups") or []),
        }
    )
    return report


def _safety_report_from_merge_report(
    merge_report: dict[str, Any],
    final_timeline: list[FinalTimelineSegment],
    captions: list[CaptionRenderUnit],
) -> dict[str, Any]:
    existing = merge_report.get("visual_merge_safety_report")
    if isinstance(existing, dict):
        return _safety_report_with_caption_ids(existing, captions)
    merged_count = int(merge_report.get("visual_pacing_merged_count") or 0)
    ratio = len(captions) / len(final_timeline) if final_timeline else 0.0
    if merged_count > 0 or ratio > 10.0:
        return contract_to_dict(
            VisualMergeSafetyReport(
                gate_passed=False,
                unsafe_merge_group_count=1,
                blocker_codes=["V21_VISUAL_PACING_MISSING_MERGE_SAFETY_PROOF"],
            )
        )
    return _empty_safety_report()


def _empty_safety_report() -> dict[str, Any]:
    return contract_to_dict(VisualMergeSafetyReport())


def _safety_report_with_caption_ids(
    safety_report: dict[str, Any],
    captions: list[CaptionRenderUnit],
) -> dict[str, Any]:
    if not captions:
        return dict(safety_report)
    caption_ids_by_segment: dict[str, list[str]] = {}
    for caption in captions:
        segment_id = str(caption.containing_video_segment_id or "")
        if not segment_id:
            for timeline_segment_id in caption.timeline_segment_ids:
                caption_ids_by_segment.setdefault(str(timeline_segment_id), []).append(caption.caption_id)
            continue
        caption_ids_by_segment.setdefault(segment_id, []).append(caption.caption_id)
    payload = dict(safety_report)
    groups = []
    for row in list(payload.get("merge_groups") or []):
        group = dict(row)
        segment_id = str(group.get("video_segment_id") or "")
        group["child_caption_ids"] = sorted(set(caption_ids_by_segment.get(segment_id) or []))
        groups.append(group)
    payload["merge_groups"] = groups
    return payload


def _build_visual_merge_safety_report(
    segments: list[FinalTimelineSegment],
    source_graph: CanonicalSourceGraph,
    *,
    unsafe_merge_attempt_count: int,
) -> dict[str, Any]:
    windows = _source_windows(source_graph)
    word_lookup = {word.word_id: word for word in source_graph.words}
    groups = [
        _build_segment_merge_group(segment, source_graph, windows, word_lookup)
        for segment in segments
    ]
    unsafe_count = sum(1 for group in groups if not group.merge_safe)
    dropped_content_count = sum(1 for group in groups if group.dropped_word_ids_crossed or group.dropped_segment_ids_crossed)
    max_gap = max([group.max_bridged_gap_us for group in groups] or [0])
    total_gap = sum(group.total_bridged_gap_us for group in groups)
    ratio = max([group.unspoken_bridge_ratio for group in groups] or [0.0])
    blocker_codes: list[str] = []
    if unsafe_count or dropped_content_count or max_gap > MAX_SAFE_BRIDGE_GAP_US or ratio > MAX_UNSPOKEN_BRIDGE_RATIO:
        blocker_codes.append("V21_VISUAL_PACING_UNSAFE_MERGE")
    report = contract_to_dict(
        VisualMergeSafetyReport(
            gate_passed=not blocker_codes,
            merge_groups=groups,
            unsafe_merge_group_count=unsafe_count,
            dropped_content_reintroduced_count=dropped_content_count,
            max_bridged_gap_us=max_gap,
            total_bridged_gap_us=total_gap,
            unspoken_bridge_ratio=round(ratio, 6),
            blocker_codes=blocker_codes,
        )
    )
    report["visual_pacing_blocked_unsafe_merge_attempt_count"] = int(unsafe_merge_attempt_count)
    report["max_safe_bridge_gap_us"] = MAX_SAFE_BRIDGE_GAP_US
    report["max_unspoken_bridge_ratio"] = MAX_UNSPOKEN_BRIDGE_RATIO
    return report
