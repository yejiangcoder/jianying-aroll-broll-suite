from __future__ import annotations

from typing import Any


def configure_writeback_dependencies(dependencies: dict[str, Any]) -> None:
    globals().update(dependencies)


def _post_write_actual_draft_audit(
    self,
    *,
    draft_dir: Path,
    actual_draft_content_path: Path,
    run_dir: Path,
    run_report: RunReport,
    expected_video_track_id: str,
    expected_text_track_id: str,
    expected_video_segments: list[dict[str, Any]],
    expected_text_segments: list[dict[str, Any]],
    target_writes: dict[str, bool],
    require_target_writes_committed: bool = True,
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    audit: dict[str, Any] = {
        "post_write_actual_draft_audit_required_on_commit": True,
        "executed": False,
        "gate_passed": False,
        "actual_draft_loaded": False,
        "actual_draft_path": str(actual_draft_content_path),
        "actual_draft_source": "",
        "only_specified_draft_written": False,
        "actual_video_rows_match_plan": False,
        "actual_caption_rows_match_plan": False,
        "expected_caption_rows_present": False,
        "actual_has_no_extra_caption_like_text_segments": False,
        "actual_caption_rows_exact_match_plan": False,
        "actual_text_residue_gate_passed": False,
        "actual_audio_coverage_gate_passed": False,
        "actual_visible_text_repeat_gate_passed": False,
        "actual_effective_speed_gate_passed": False,
        "actual_visual_pacing_gate_passed": False,
        "actual_caption_gui_readability_gate_passed": False,
        "actual_final_caption_visible_repeat_gate_passed": False,
        "actual_caption_alignment_gate_passed": False,
        "failure_reasons": failures,
        "blocker_codes": [],
    }

    def fail(reason: str, **context: Any) -> None:
        failures.append({"reason": reason, **context})

    target_paths_within_draft = bool(target_writes) and all(
        self._is_within(Path(path), draft_dir) for path in target_writes
    )
    target_commit_state_ok = (not require_target_writes_committed) or all(bool(value) for value in target_writes.values())
    only_specified = target_paths_within_draft and target_commit_state_ok
    audit["only_specified_draft_written"] = only_specified
    audit["target_writes_committed_required"] = bool(require_target_writes_committed)
    audit["target_paths_within_draft"] = target_paths_within_draft
    if not only_specified:
        fail("only_specified_draft_written_failed", target_writes=dict(target_writes))

    actual_data, load_report = self._load_actual_draft_content(actual_draft_content_path, run_dir)
    audit.update(load_report)
    if actual_data is None:
        fail("actual_draft_missing_or_unreadable", error=load_report.get("actual_draft_load_error", ""))
        return _finalize_post_write_actual_draft_audit(audit)

    audit["executed"] = True
    video_track = self._track_by_id(actual_data, expected_video_track_id)
    text_track = self._track_by_id(actual_data, expected_text_track_id)
    if video_track is None:
        fail("actual_video_track_missing", expected_video_track_id=expected_video_track_id)
        actual_video_segments: list[dict[str, Any]] = []
    else:
        actual_video_segments = [row for row in video_track.get("segments") or [] if isinstance(row, dict)]
    if text_track is None:
        fail("actual_caption_track_missing", expected_text_track_id=expected_text_track_id)
        actual_text_segments: list[dict[str, Any]] = []
    else:
        actual_text_segments = [row for row in text_track.get("segments") or [] if isinstance(row, dict)]

    video_match = self._video_segments_match_plan(actual_video_segments, expected_video_segments)
    audit["actual_video_rows_match_plan"] = video_match
    audit["actual_video_segment_count"] = len(actual_video_segments)
    audit["expected_video_segment_count"] = len(expected_video_segments)
    if not video_match:
        fail(
            "actual_video_rows_differ_from_projection",
            actual_video_segment_count=len(actual_video_segments),
            expected_video_segment_count=len(expected_video_segments),
        )

    visible_text_rows = self._visible_text_rows(actual_data)
    text_residue_report = self._actual_text_residue_report(
        visible_text_rows=visible_text_rows,
        actual_video_segments=actual_video_segments,
        expected_text_segments=expected_text_segments,
        run_report=run_report,
    )
    audit["actual_text_residue_report"] = text_residue_report
    audit.update(
        {
            key: text_residue_report[key]
            for key in (
                "actual_text_residue_gate_passed",
                "expected_caption_rows_present",
                "actual_has_no_extra_caption_like_text_segments",
                "actual_caption_rows_exact_match_plan",
                "actual_caption_rows_match_plan",
                "actual_text_segment_count",
                "generated_caption_segment_count",
                "preserved_non_subtitle_count",
                "old_subtitle_residue_count",
                "orphan_text_segment_count",
                "text_after_final_video_end_count",
                "floating_caption_count",
            )
        }
    )
    caption_match = bool(text_residue_report.get("actual_caption_rows_exact_match_plan"))
    audit["actual_caption_segment_count"] = int(text_residue_report.get("generated_caption_segment_count") or 0)
    audit["expected_caption_segment_count"] = len(expected_text_segments)
    audit["selected_text_track_segment_count"] = len(actual_text_segments)
    if not caption_match:
        fail(
            "actual_caption_rows_differ_from_material_write_plan",
            actual_caption_segment_count=int(text_residue_report.get("generated_caption_segment_count") or 0),
            actual_text_segment_count=int(text_residue_report.get("actual_text_segment_count") or 0),
            expected_caption_segment_count=len(expected_text_segments),
            expected_caption_rows_present=bool(text_residue_report.get("expected_caption_rows_present")),
            actual_has_no_extra_caption_like_text_segments=bool(text_residue_report.get("actual_has_no_extra_caption_like_text_segments")),
        )
    if not bool(text_residue_report.get("actual_text_residue_gate_passed")):
        fail("actual_text_residue_gate_failed", actual_text_residue_report=text_residue_report)

    speed_report = self._effective_speed_report(actual_video_segments)
    audit["actual_effective_speed_report"] = speed_report
    speed_passed = bool(actual_video_segments) and int(speed_report.get("effective_speed_drift_count") or 0) == 0
    audit["actual_effective_speed_gate_passed"] = speed_passed
    if not speed_passed:
        fail("actual_effective_speed_gate_failed", effective_speed_report=speed_report)

    plan_quality = self._plan_quality_audit(run_report)
    audit.update(plan_quality)
    for reason in plan_quality.get("plan_quality_failure_reasons") or []:
        fail(str(reason))

    actual_timeline = self._actual_final_timeline_from_video_rows(actual_video_segments, run_report.final_timeline)
    actual_alignment_timeline = self._actual_timeline_with_caption_split_containers(
        actual_timeline,
        text_residue_report.get("generated_caption_rows") or [],
    )
    actual_caption_units = self._actual_caption_units_from_text_rows(
        text_residue_report.get("generated_caption_rows") or [],
        actual_timeline=actual_alignment_timeline,
        run_report=run_report,
    )
    actual_caption_alignment = build_caption_alignment_report(
        final_timeline=actual_alignment_timeline,
        captions=actual_caption_units,
        visible_caption_track_count=1 if actual_caption_units else 0,
        caption_lane_count=1 if actual_caption_units else 0,
        enforce_spoken_word_caption_coverage=False,
    )
    audit["actual_caption_alignment_report"] = actual_caption_alignment
    audit["actual_caption_alignment_gate_passed"] = bool(actual_caption_alignment.get("gate_passed"))
    audit["actual_caption_gui_readability_gate_passed"] = bool(actual_caption_alignment.get("caption_gui_track_gate_passed")) and bool(
        actual_caption_alignment.get("subtitle_readability_gate_passed")
    )
    if not bool(actual_caption_alignment.get("gate_passed")):
        fail("actual_caption_alignment_gate_failed", actual_caption_alignment_report=actual_caption_alignment)

    caption_like_rows = list(text_residue_report.get("generated_caption_rows") or []) + list(text_residue_report.get("old_subtitle_residue_segments") or [])
    actual_visible_text_units = self._actual_caption_units_from_text_rows(
        caption_like_rows,
        actual_timeline=actual_alignment_timeline,
        run_report=run_report,
    )
    actual_visible_text_repeat = build_final_caption_visible_repeat_gate(actual_visible_text_units)
    audit["actual_visible_text_repeat_report"] = actual_visible_text_repeat
    audit["actual_visible_text_repeat_gate_passed"] = bool(actual_visible_text_repeat.get("gate_passed"))
    audit["actual_final_caption_visible_repeat_gate_passed"] = bool(actual_visible_text_repeat.get("gate_passed"))
    audit["actual_visible_repeat_candidate_count"] = int(actual_visible_text_repeat.get("visible_repeat_candidate_count") or 0)
    if not bool(actual_visible_text_repeat.get("gate_passed")):
        fail("actual_visible_text_repeat_gate_failed", actual_visible_text_repeat_report=actual_visible_text_repeat)

    audio_coverage_report = self._actual_audio_coverage_report(
        actual_video_segments=actual_video_segments,
        run_report=run_report,
    )
    audit["actual_audio_coverage_report"] = audio_coverage_report
    audit["actual_audio_coverage_gate_passed"] = bool(audio_coverage_report.get("gate_passed"))
    audit["audio_coverage_failure_count"] = int(audio_coverage_report.get("audio_coverage_failure_count") or 0)
    audit["heard_but_uncaptioned_word_count"] = int(audio_coverage_report.get("heard_but_uncaptioned_word_count") or 0)
    audit["dropped_but_reintroduced_word_count"] = int(audio_coverage_report.get("dropped_but_reintroduced_word_count") or 0)
    if not bool(audio_coverage_report.get("gate_passed")):
        fail("actual_audio_coverage_gate_failed", actual_audio_coverage_report=audio_coverage_report)

    canonical_sync_report = self._jianying_canonical_timeline_sync_report(
        actual_video_segments=actual_video_segments,
        generated_caption_rows=text_residue_report.get("generated_caption_rows") or [],
        run_report=run_report,
    )
    audit["jianying_canonical_timeline_sync_report"] = canonical_sync_report
    for key in (
        "final_video_end_us",
        "max_caption_end_us",
        "captions_after_final_video_end_count",
        "post_write_video_target_gap_count_gt_300ms",
        "post_write_total_video_target_gap_us",
        "caption_video_drift_count",
        "max_caption_video_drift_us",
        "split_caption_container_mismatch_count",
        "caption_crosses_video_split_gap_count",
        "caption_words_not_covered_by_actual_video_count",
        "jianying_canonical_timeline_sync_gate_passed",
    ):
        audit[key] = canonical_sync_report.get(key)
    if not bool(canonical_sync_report.get("jianying_canonical_timeline_sync_gate_passed")):
        audit["blocker_codes"] = _unique_strings(
            list(audit.get("blocker_codes") or []) + list(canonical_sync_report.get("blocker_codes") or [])
        )
        fail("jianying_canonical_timeline_sync_failed", jianying_canonical_timeline_sync_report=canonical_sync_report)

    return _finalize_post_write_actual_draft_audit(audit)


def _actual_final_timeline_from_video_rows(
    self,
    actual_video_segments: list[dict[str, Any]],
    planned_segments: list[FinalTimelineSegment],
) -> list[FinalTimelineSegment]:
    timeline: list[FinalTimelineSegment] = []
    for index, row in enumerate(actual_video_segments):
        planned = planned_segments[index] if index < len(planned_segments) else None
        coverage = row.get("_v21_audio_coverage") if isinstance(row.get("_v21_audio_coverage"), dict) else {}
        target_start = self._timerange_start(row.get("target_timerange"))
        target_end = target_start + self._timerange_duration(row.get("target_timerange"))
        source_start, source_end, spoken_start, spoken_end = self._actual_source_interval_for_video_row(row, planned)
        segment_id = str(row.get("id") or f"actual_video_{index + 1:06d}")
        debug_hints = dict(planned.debug_hints) if planned is not None else {}
        if coverage:
            debug_hints.update(
                {
                    "writeback_caption_id": str(coverage.get("caption_id") or ""),
                    "writeback_original_final_segment_id": str(coverage.get("timeline_segment_id") or ""),
                }
            )
        timeline.append(
            FinalTimelineSegment(
                segment_id=segment_id,
                source_material_id=planned.source_material_id if planned is not None else str(row.get("material_id") or row.get("materialId") or ""),
                source_segment_id=planned.source_segment_id if planned is not None else None,
                source_start_us=source_start,
                source_end_us=source_end,
                target_start_us=target_start,
                target_end_us=target_end,
                word_ids=list(coverage.get("word_ids") or (planned.word_ids if planned is not None else [])),
                text=planned.text if planned is not None else "",
                decision_ids=list(planned.decision_ids) if planned is not None else [],
                spoken_source_start_us=spoken_start,
                spoken_source_end_us=spoken_end,
                clip_source_start_us=source_start,
                clip_source_end_us=source_end,
                lead_handle_us=max(0, spoken_start - source_start),
                tail_handle_us=max(0, source_end - spoken_end),
                debug_hints=debug_hints,
            )
        )
    return timeline


def _actual_timeline_with_caption_split_containers(
    self,
    actual_timeline: list[FinalTimelineSegment],
    caption_rows: list[dict[str, Any]],
) -> list[FinalTimelineSegment]:
    timeline = list(actual_timeline)
    existing_ids = {segment.segment_id for segment in timeline}
    for row in caption_rows:
        caption_id = str(row.get("caption_id") or "")
        if not caption_id:
            continue
        start = int(row.get("target_start_us") or 0)
        end = int(row.get("target_end_us") or 0)
        if any(int(segment.target_start_us) <= start and end <= int(segment.target_end_us) for segment in timeline):
            continue
        split_segments = [
            segment
            for segment in actual_timeline
            if str((segment.debug_hints or {}).get("writeback_caption_id") or "") == caption_id
        ]
        if not split_segments:
            split_segments = self._timeline_segments_covering_target_range(actual_timeline, start, end)
        if not split_segments:
            continue
        split_start = min(int(segment.target_start_us) for segment in split_segments)
        split_end = max(int(segment.target_end_us) for segment in split_segments)
        if not (split_start <= start and end <= split_end):
            continue
        word_ids: list[str] = []
        for segment in split_segments:
            for word_id in segment.word_ids:
                if str(word_id) not in word_ids:
                    word_ids.append(str(word_id))
        source_start = min(int(segment.source_start_us) for segment in split_segments)
        source_end = max(int(segment.source_end_us) for segment in split_segments)
        segment_id = f"actual_caption_container_{caption_id}"
        if segment_id in existing_ids:
            continue
        existing_ids.add(segment_id)
        timeline.append(
            FinalTimelineSegment(
                segment_id=segment_id,
                source_material_id=split_segments[0].source_material_id,
                source_segment_id=split_segments[0].source_segment_id,
                source_start_us=source_start,
                source_end_us=source_end,
                target_start_us=start,
                target_end_us=end,
                word_ids=word_ids,
                text=str(row.get("text") or ""),
                decision_ids=[],
                spoken_source_start_us=source_start,
                spoken_source_end_us=source_end,
                clip_source_start_us=source_start,
                clip_source_end_us=source_end,
                lead_handle_us=0,
                tail_handle_us=0,
                debug_hints={"writeback_caption_id": caption_id, "synthetic_split_caption_container": True},
            )
        )
    return timeline


def _actual_caption_units_from_text_rows(
    self,
    rows: list[dict[str, Any]],
    *,
    actual_timeline: list[FinalTimelineSegment],
    run_report: RunReport,
) -> list[CaptionRenderUnit]:
    caption_by_segment_id: dict[str, CaptionRenderUnit] = {}
    caption_by_material_id: dict[str, CaptionRenderUnit] = {}
    for caption, segment in zip(run_report.captions, run_report.material_write_plan.get("segments") or []):
        if not isinstance(segment, dict):
            continue
        segment_id = str(segment.get("id") or "")
        material_id = str(segment.get("material_id") or segment.get("materialId") or "")
        if segment_id:
            caption_by_segment_id[segment_id] = caption
        if material_id:
            caption_by_material_id[material_id] = caption
    units: list[CaptionRenderUnit] = []
    for index, row in enumerate(sorted(rows, key=lambda item: (int(item.get("target_start_us") or 0), int(item.get("target_end_us") or 0), str(item.get("segment_id") or ""))), start=1):
        planned = caption_by_segment_id.get(str(row.get("segment_id") or "")) or caption_by_material_id.get(str(row.get("material_id") or ""))
        container = self._containing_actual_timeline_segment(row, actual_timeline)
        timeline_segment_ids = [container.segment_id] if container is not None else (list(planned.timeline_segment_ids) if planned is not None else [])
        units.append(
            CaptionRenderUnit(
                caption_id=planned.caption_id if planned is not None else f"actual_text_{str(row.get('segment_id') or index)}",
                timeline_segment_ids=timeline_segment_ids,
                word_ids=list(planned.word_ids) if planned is not None else [],
                text=str(row.get("text") or ""),
                target_start_us=int(row.get("target_start_us") or 0),
                target_end_us=int(row.get("target_end_us") or 0),
                source_subtitle_uids=list(planned.source_subtitle_uids) if planned is not None else [],
                style_template_id=planned.style_template_id if planned is not None else "actual_visible_text",
                spoken_source_start_us=planned.spoken_source_start_us if planned is not None else None,
                spoken_source_end_us=planned.spoken_source_end_us if planned is not None else None,
                containing_video_segment_id=container.segment_id if container is not None else None,
            )
        )
    return units


def _containing_actual_timeline_segment(
    self,
    text_row: dict[str, Any],
    actual_timeline: list[FinalTimelineSegment],
) -> FinalTimelineSegment | None:
    start = int(text_row.get("target_start_us") or 0)
    end = int(text_row.get("target_end_us") or 0)
    for segment in actual_timeline:
        if int(segment.target_start_us) <= start and end <= int(segment.target_end_us):
            return segment
    caption_id = str(text_row.get("caption_id") or "")
    if caption_id:
        split_segments = [
            segment
            for segment in actual_timeline
            if str((segment.debug_hints or {}).get("writeback_caption_id") or "") == caption_id
        ]
        if split_segments:
            synthetic = self._synthetic_caption_container_from_segments(
                split_segments,
                caption_id=caption_id,
                text=str(text_row.get("text") or ""),
                target_start_us=start,
                target_end_us=end,
            )
            if synthetic is not None:
                return synthetic
    split_segments = self._timeline_segments_covering_target_range(actual_timeline, start, end)
    if split_segments:
        return self._synthetic_caption_container_from_segments(
            split_segments,
            caption_id=caption_id,
            text=str(text_row.get("text") or ""),
            target_start_us=start,
            target_end_us=end,
        )
    return None


def _timeline_segments_covering_target_range(
    self,
    timeline: list[FinalTimelineSegment],
    start: int,
    end: int,
) -> list[FinalTimelineSegment]:
    if end <= start:
        return []
    overlapping = [
        segment
        for segment in timeline
        if self._ranges_overlap(int(segment.target_start_us), int(segment.target_end_us), start, end)
    ]
    ordered = sorted(overlapping, key=lambda segment: (int(segment.target_start_us), int(segment.target_end_us), str(segment.segment_id)))
    cursor = start
    covering: list[FinalTimelineSegment] = []
    for segment in ordered:
        segment_start = int(segment.target_start_us)
        segment_end = int(segment.target_end_us)
        if segment_end <= cursor:
            continue
        if segment_start > cursor:
            return []
        covering.append(segment)
        cursor = max(cursor, segment_end)
        if cursor >= end:
            return covering
    return []


def _synthetic_caption_container_from_segments(
    self,
    segments: list[FinalTimelineSegment],
    *,
    caption_id: str,
    text: str,
    target_start_us: int,
    target_end_us: int,
) -> FinalTimelineSegment | None:
    if not segments:
        return None
    segment_start = min(int(segment.target_start_us) for segment in segments)
    segment_end = max(int(segment.target_end_us) for segment in segments)
    if not (segment_start <= int(target_start_us) and int(target_end_us) <= segment_end):
        return None
    word_ids: list[str] = []
    for segment in segments:
        for word_id in segment.word_ids:
            if str(word_id) not in word_ids:
                word_ids.append(str(word_id))
    source_start = min(int(segment.source_start_us) for segment in segments)
    source_end = max(int(segment.source_end_us) for segment in segments)
    return FinalTimelineSegment(
        segment_id=f"actual_caption_container_{caption_id or 'unbound'}",
        source_material_id=segments[0].source_material_id,
        source_segment_id=segments[0].source_segment_id,
        source_start_us=source_start,
        source_end_us=source_end,
        target_start_us=int(target_start_us),
        target_end_us=int(target_end_us),
        word_ids=word_ids,
        text=text,
        decision_ids=[],
        spoken_source_start_us=source_start,
        spoken_source_end_us=source_end,
        clip_source_start_us=source_start,
        clip_source_end_us=source_end,
        lead_handle_us=0,
        tail_handle_us=0,
        debug_hints={"writeback_caption_id": caption_id, "synthetic_split_caption_container": True},
    )


def _actual_audio_coverage_report(
    self,
    *,
    actual_video_segments: list[dict[str, Any]],
    run_report: RunReport,
) -> dict[str, Any]:
    if run_report.source_graph is None:
        return {
            "gate_passed": False,
            "actual_audio_coverage_gate_passed": False,
            "audio_coverage_failure_count": 1,
            "heard_but_uncaptioned_word_count": 0,
            "dropped_but_reintroduced_word_count": 0,
            "failure_reasons": ["source_graph_missing"],
            "audio_segment_reports": [],
        }
    words = list(run_report.source_graph.words)
    captioned_word_ids = {str(word_id) for caption in run_report.captions for word_id in caption.word_ids}
    planned_word_ids = {str(word_id) for segment in run_report.final_timeline for word_id in segment.word_ids}
    segment_reports: list[dict[str, Any]] = []
    failure_count = 0
    heard_but_uncaptioned_count = 0
    dropped_but_reintroduced_count = 0
    allowed_gap_count = 0
    for interval in self._actual_source_interval_rows(actual_video_segments, run_report.final_timeline):
        heard_words = [
            word
            for word in words
            if self._ranges_overlap(int(word.source_start_us), int(word.source_end_us), interval["source_start_us"], interval["source_end_us"])
        ]
        missing_words: list[dict[str, Any]] = []
        allowed_words: list[dict[str, Any]] = []
        dropped_words: list[dict[str, Any]] = []
        for word in heard_words:
            word_id = str(word.word_id)
            if word_id in captioned_word_ids:
                continue
            word_row = {
                "word_id": word_id,
                "text": word.text,
                "source_start_us": int(word.source_start_us),
                "source_end_us": int(word.source_end_us),
            }
            overlaps_spoken = self._ranges_overlap(
                int(word.source_start_us),
                int(word.source_end_us),
                interval["spoken_source_start_us"],
                interval["spoken_source_end_us"],
            )
            if not overlaps_spoken:
                allowed_words.append(word_row | {"allowed_reason": "explicit_handle_gap"})
                continue
            missing_words.append(word_row)
            if word_id not in planned_word_ids:
                dropped_words.append(word_row)
        heard_but_uncaptioned_count += len(missing_words)
        dropped_but_reintroduced_count += len(dropped_words)
        allowed_gap_count += len(allowed_words)
        if missing_words or dropped_words:
            failure_count += 1
        segment_reports.append(
            {
                "video_segment_id": interval["video_segment_id"],
                "timeline_segment_id": interval["timeline_segment_id"],
                "caption_id": interval.get("caption_id", ""),
                "source_start_us": interval["source_start_us"],
                "source_end_us": interval["source_end_us"],
                "spoken_source_start_us": interval["spoken_source_start_us"],
                "spoken_source_end_us": interval["spoken_source_end_us"],
                "heard_word_count": len(heard_words),
                "heard_but_uncaptioned_word_count": len(missing_words),
                "dropped_but_reintroduced_word_count": len(dropped_words),
                "allowed_handle_gap_word_count": len(allowed_words),
                "heard_but_uncaptioned_words": missing_words,
                "dropped_but_reintroduced_words": dropped_words,
                "allowed_handle_gap_words": allowed_words,
            }
        )
    gate_passed = failure_count == 0 and heard_but_uncaptioned_count == 0 and dropped_but_reintroduced_count == 0
    return {
        "gate_passed": gate_passed,
        "actual_audio_coverage_gate_passed": gate_passed,
        "audio_coverage_failure_count": failure_count,
        "heard_but_uncaptioned_word_count": heard_but_uncaptioned_count,
        "dropped_but_reintroduced_word_count": dropped_but_reintroduced_count,
        "allowed_handle_gap_word_count": allowed_gap_count,
        "final_video_segment_count": len(actual_video_segments),
        "captioned_word_count": len(captioned_word_ids),
        "audio_segment_reports": segment_reports,
    }


def _jianying_canonical_timeline_sync_report(
    self,
    *,
    actual_video_segments: list[dict[str, Any]],
    generated_caption_rows: list[dict[str, Any]],
    run_report: RunReport,
) -> dict[str, Any]:
    canonical_video_segments: list[dict[str, Any]] = []
    original_video_rows: list[dict[str, Any]] = []
    target_cursor = 0
    previous_target_end = 0
    gap_count = 0
    total_gap_us = 0
    for index, row in enumerate(actual_video_segments, start=1):
        target_start = self._timerange_start(row.get("target_timerange"))
        target_duration = self._timerange_duration(row.get("target_timerange"))
        target_end = target_start + target_duration
        gap_us = target_start - previous_target_end
        if gap_us > 0:
            total_gap_us += gap_us
        if gap_us > 300_000:
            gap_count += 1
        original_video_rows.append(
            {
                "index": index,
                "segment_id": str(row.get("id") or f"actual_video_{index:06d}"),
                "target_start_us": target_start,
                "target_end_us": target_end,
                "duration_us": target_duration,
                "caption_id": str((row.get("_v21_audio_coverage") or {}).get("caption_id") or "")
                if isinstance(row.get("_v21_audio_coverage"), dict)
                else "",
            }
        )
        canonical_row = deepcopy(row)
        canonical_row["target_timerange"] = {"start": target_cursor, "duration": max(0, target_duration)}
        canonical_row["_v21_canonical_save"] = {
            "original_target_start_us": target_start,
            "original_target_end_us": target_end,
            "canonical_target_start_us": target_cursor,
            "canonical_target_end_us": target_cursor + max(0, target_duration),
        }
        canonical_video_segments.append(canonical_row)
        target_cursor += max(0, target_duration)
        previous_target_end = target_end

    final_video_end_us = int(target_cursor)
    caption_rows = sorted(
        generated_caption_rows,
        key=lambda row: (int(row.get("target_start_us") or 0), int(row.get("target_end_us") or 0), str(row.get("caption_id") or "")),
    )
    max_caption_end_us = max((int(row.get("target_end_us") or 0) for row in caption_rows), default=0)
    captions_after_final_video_end = [
        row
        for row in caption_rows
        if final_video_end_us > 0 and int(row.get("target_end_us") or 0) > final_video_end_us
    ]
    canonical_rows_by_caption = self._video_rows_by_caption_id(canonical_video_segments)
    original_rows_by_caption = self._video_rows_by_caption_id(actual_video_segments)
    original_rows_by_timeline_segment = self._video_rows_by_timeline_segment_id(actual_video_segments)
    caption_by_id = {str(caption.caption_id): caption for caption in run_report.captions}

    caption_video_drift_rows: list[dict[str, Any]] = []
    split_caption_mismatch_rows: list[dict[str, Any]] = []
    split_gap_rows: list[dict[str, Any]] = []
    uncovered_word_rows: list[dict[str, Any]] = []
    for row in caption_rows:
        caption_id = str(row.get("caption_id") or "")
        caption_start = int(row.get("target_start_us") or 0)
        caption_end = int(row.get("target_end_us") or 0)
        canonical_group = canonical_rows_by_caption.get(caption_id) or self._video_rows_covering_target_range(
            canonical_video_segments,
            caption_start,
            caption_end,
        )
        if canonical_group:
            group_start = min(self._timerange_start(segment.get("target_timerange")) for segment in canonical_group)
            group_end = max(
                self._timerange_start(segment.get("target_timerange")) + self._timerange_duration(segment.get("target_timerange"))
                for segment in canonical_group
            )
        else:
            group_start = 0
            group_end = 0
        caption_covered_by_video = bool(canonical_group) and group_start <= caption_start and caption_end <= group_end
        drift_us = 0 if caption_covered_by_video else (
            max(abs(caption_start - group_start), abs(caption_end - group_end)) if canonical_group else max(caption_end - caption_start, 0)
        )
        if drift_us:
            caption_video_drift_rows.append(
                {
                    "caption_id": caption_id,
                    "caption_start_us": caption_start,
                    "caption_end_us": caption_end,
                    "canonical_video_start_us": group_start,
                    "canonical_video_end_us": group_end,
                    "drift_us": drift_us,
                }
            )
        if not caption_covered_by_video:
            split_caption_mismatch_rows.append(
                {
                    "caption_id": caption_id,
                    "caption_start_us": caption_start,
                    "caption_end_us": caption_end,
                    "canonical_video_start_us": group_start,
                    "canonical_video_end_us": group_end,
                    "canonical_video_row_count": len(canonical_group),
                }
            )

        planned_caption = caption_by_id.get(caption_id)
        original_group = original_rows_by_caption.get(caption_id) or []
        if not original_group and planned_caption is not None:
            for timeline_id in [planned_caption.containing_video_segment_id, *planned_caption.timeline_segment_ids]:
                timeline_key = str(timeline_id or "")
                if not timeline_key:
                    continue
                original_group = original_rows_by_timeline_segment.get(timeline_key) or []
                if original_group:
                    break
        if not original_group:
            original_group = self._video_rows_overlapping_target_range(
                actual_video_segments,
                caption_start,
                caption_end,
            )
        split_gap = self._caption_split_gap_row(row, original_group)
        if split_gap is not None:
            split_gap_rows.append(split_gap)

        expected_word_ids = {str(word_id) for word_id in (planned_caption.word_ids if planned_caption is not None else [])}
        covered_word_ids = {
            str(word_id)
            for segment in canonical_group
            for word_id in ((segment.get("_v21_audio_coverage") or {}).get("word_ids") or [])
            if isinstance(segment.get("_v21_audio_coverage"), dict)
        }
        missing_word_ids = sorted(expected_word_ids - covered_word_ids)
        if missing_word_ids:
            uncovered_word_rows.append(
                {
                    "caption_id": caption_id,
                    "missing_word_ids": missing_word_ids,
                    "missing_word_count": len(missing_word_ids),
                }
            )

    canonical_timeline = self._actual_final_timeline_from_video_rows(canonical_video_segments, run_report.final_timeline)
    canonical_alignment_timeline = self._actual_timeline_with_caption_split_containers(canonical_timeline, caption_rows)
    canonical_caption_units = self._actual_caption_units_from_text_rows(
        caption_rows,
        actual_timeline=canonical_alignment_timeline,
        run_report=run_report,
    )
    canonical_caption_alignment = build_caption_alignment_report(
        final_timeline=canonical_alignment_timeline,
        captions=canonical_caption_units,
        visible_caption_track_count=1 if canonical_caption_units else 0,
        caption_lane_count=1 if canonical_caption_units else 0,
        enforce_spoken_word_caption_coverage=False,
    )
    caption_words_not_covered_count = sum(int(row["missing_word_count"]) for row in uncovered_word_rows)
    failure_reasons: list[str] = []
    if captions_after_final_video_end:
        failure_reasons.append("captions_after_final_video_end")
    if gap_count:
        failure_reasons.append("post_write_video_target_gaps")
    if caption_video_drift_rows:
        failure_reasons.append("caption_video_drift_after_canonical_save")
    if split_caption_mismatch_rows:
        failure_reasons.append("split_caption_container_mismatch")
    if split_gap_rows:
        failure_reasons.append("caption_crosses_video_split_gap")
    if caption_words_not_covered_count:
        failure_reasons.append("caption_words_not_covered_by_actual_video")
    if not bool(canonical_caption_alignment.get("gate_passed")):
        failure_reasons.append("canonical_caption_alignment_gate_failed")
    gate_passed = not failure_reasons
    return {
        "gate_passed": gate_passed,
        "jianying_canonical_timeline_sync_gate_passed": gate_passed,
        "blocker_codes": [] if gate_passed else ["V21_JIANYING_CANONICAL_TIMELINE_SYNC_FAILED"],
        "failure_reasons": failure_reasons,
        "final_video_end_us": final_video_end_us,
        "max_caption_end_us": max_caption_end_us,
        "captions_after_final_video_end_count": len(captions_after_final_video_end),
        "captions_after_final_video_end": captions_after_final_video_end[:20],
        "post_write_video_target_gap_count_gt_300ms": gap_count,
        "post_write_total_video_target_gap_us": total_gap_us,
        "post_write_video_target_gap_threshold_us": 300_000,
        "caption_video_drift_count": len(caption_video_drift_rows),
        "max_caption_video_drift_us": max((int(row["drift_us"]) for row in caption_video_drift_rows), default=0),
        "caption_video_drift_rows": caption_video_drift_rows[:20],
        "split_caption_container_mismatch_count": len(split_caption_mismatch_rows),
        "split_caption_container_mismatch_rows": split_caption_mismatch_rows[:20],
        "caption_crosses_video_split_gap_count": len(split_gap_rows),
        "caption_crosses_video_split_gap_rows": split_gap_rows[:20],
        "caption_words_not_covered_by_actual_video_count": caption_words_not_covered_count,
        "caption_words_not_covered_by_actual_video_rows": uncovered_word_rows[:20],
        "canonical_caption_alignment_gate_passed": bool(canonical_caption_alignment.get("gate_passed")),
        "canonical_caption_alignment_report": canonical_caption_alignment,
        "canonical_video_row_count": len(canonical_video_segments),
        "canonical_caption_row_count": len(caption_rows),
        "original_video_rows": original_video_rows[:20],
    }


def _video_rows_by_caption_id(self, video_segments: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    rows_by_caption: dict[str, list[dict[str, Any]]] = {}
    for segment in video_segments:
        coverage = segment.get("_v21_audio_coverage") if isinstance(segment.get("_v21_audio_coverage"), dict) else {}
        caption_id = str(coverage.get("caption_id") or "")
        if not caption_id:
            continue
        rows_by_caption.setdefault(caption_id, []).append(segment)
    return rows_by_caption


def _video_rows_by_timeline_segment_id(self, video_segments: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    rows_by_timeline: dict[str, list[dict[str, Any]]] = {}
    for segment in video_segments:
        coverage = segment.get("_v21_audio_coverage") if isinstance(segment.get("_v21_audio_coverage"), dict) else {}
        timeline_segment_id = str(coverage.get("timeline_segment_id") or "")
        if not timeline_segment_id:
            continue
        rows_by_timeline.setdefault(timeline_segment_id, []).append(segment)
    return rows_by_timeline


def _video_rows_covering_target_range(
    self,
    video_segments: list[dict[str, Any]],
    caption_start: int,
    caption_end: int,
) -> list[dict[str, Any]]:
    if caption_end <= caption_start:
        return []
    overlapping = self._video_rows_overlapping_target_range(video_segments, caption_start, caption_end)
    if not overlapping:
        return []
    ordered = sorted(
        overlapping,
        key=lambda segment: (
            self._timerange_start(segment.get("target_timerange")),
            self._timerange_start(segment.get("target_timerange")) + self._timerange_duration(segment.get("target_timerange")),
        ),
    )
    cursor = caption_start
    covering: list[dict[str, Any]] = []
    for segment in ordered:
        segment_start = self._timerange_start(segment.get("target_timerange"))
        segment_end = segment_start + self._timerange_duration(segment.get("target_timerange"))
        if segment_end <= cursor:
            continue
        if segment_start > cursor:
            return []
        covering.append(segment)
        cursor = max(cursor, segment_end)
        if cursor >= caption_end:
            return covering
    return []


def _video_rows_overlapping_target_range(
    self,
    video_segments: list[dict[str, Any]],
    caption_start: int,
    caption_end: int,
) -> list[dict[str, Any]]:
    if caption_end <= caption_start:
        return []
    return [
        segment
        for segment in video_segments
        if self._ranges_overlap(
            self._timerange_start(segment.get("target_timerange")),
            self._timerange_start(segment.get("target_timerange")) + self._timerange_duration(segment.get("target_timerange")),
            caption_start,
            caption_end,
        )
    ]


def _caption_split_gap_row(
    self,
    caption_row: dict[str, Any],
    video_segments: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if len(video_segments) <= 1:
        return None
    ordered = sorted(
        video_segments,
        key=lambda segment: (
            self._timerange_start(segment.get("target_timerange")),
            self._timerange_start(segment.get("target_timerange")) + self._timerange_duration(segment.get("target_timerange")),
        ),
    )
    caption_start = int(caption_row.get("target_start_us") or 0)
    caption_end = int(caption_row.get("target_end_us") or 0)
    previous_end = self._timerange_start(ordered[0].get("target_timerange")) + self._timerange_duration(ordered[0].get("target_timerange"))
    for segment in ordered[1:]:
        current_start = self._timerange_start(segment.get("target_timerange"))
        current_end = current_start + self._timerange_duration(segment.get("target_timerange"))
        if current_start > previous_end and self._ranges_overlap(caption_start, caption_end, previous_end, current_start):
            return {
                "caption_id": str(caption_row.get("caption_id") or ""),
                "caption_start_us": caption_start,
                "caption_end_us": caption_end,
                "gap_start_us": previous_end,
                "gap_end_us": current_start,
                "gap_us": current_start - previous_end,
            }
        previous_end = max(previous_end, current_end)
    return None


def _actual_source_interval_rows(
    self,
    actual_video_segments: list[dict[str, Any]],
    planned_segments: list[FinalTimelineSegment],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(actual_video_segments):
        planned = planned_segments[index] if index < len(planned_segments) else None
        coverage = row.get("_v21_audio_coverage") if isinstance(row.get("_v21_audio_coverage"), dict) else {}
        source_start, source_end, spoken_start, spoken_end = self._actual_source_interval_for_video_row(row, planned)
        rows.append(
            {
                "video_segment_id": str(row.get("id") or f"actual_video_{index + 1:06d}"),
                "timeline_segment_id": str(coverage.get("timeline_segment_id") or (planned.segment_id if planned is not None else "")),
                "caption_id": str(coverage.get("caption_id") or ""),
                "source_start_us": source_start,
                "source_end_us": source_end,
                "spoken_source_start_us": spoken_start,
                "spoken_source_end_us": spoken_end,
            }
        )
    return rows


def _actual_source_interval_for_video_row(
    self,
    row: dict[str, Any],
    planned: FinalTimelineSegment | None,
) -> tuple[int, int, int, int]:
    coverage = row.get("_v21_audio_coverage") if isinstance(row.get("_v21_audio_coverage"), dict) else {}
    if coverage:
        source_start = int(coverage.get("source_start_us") or 0)
        source_end = int(coverage.get("source_end_us") or source_start)
        spoken_start = int(coverage.get("spoken_source_start_us") or source_start)
        spoken_end = int(coverage.get("spoken_source_end_us") or source_end)
        return source_start, source_end, spoken_start, spoken_end
    if planned is None:
        start = self._timerange_start(row.get("source_timerange"))
        end = start + self._timerange_duration(row.get("source_timerange"))
        return start, end, start, end
    spoken_start = int(planned.spoken_source_start_us if planned.spoken_source_start_us is not None else planned.source_start_us)
    spoken_end = int(planned.spoken_source_end_us if planned.spoken_source_end_us is not None else planned.source_end_us)
    clip_start = int(planned.clip_source_start_us if planned.clip_source_start_us is not None else planned.source_start_us)
    clip_end = int(planned.clip_source_end_us if planned.clip_source_end_us is not None else planned.source_end_us)
    projection = row.get("_safe_handle_projection") if isinstance(row.get("_safe_handle_projection"), dict) else {}
    if projection and bool(projection.get("safe_handle_policy_enabled")):
        source_start = clip_start if int(projection.get("lead_handle_applied_us") or 0) > 0 else spoken_start
        source_end = clip_end if int(projection.get("tail_handle_applied_us") or 0) > 0 else spoken_end
        return source_start, source_end, spoken_start, spoken_end
    return int(planned.source_start_us), int(planned.source_end_us), spoken_start, spoken_end


def _ranges_overlap(self, left_start: int, left_end: int, right_start: int, right_end: int) -> bool:
    return int(left_start) < int(right_end) and int(left_end) > int(right_start)


def _segment_timerange_signature(self, row: dict[str, Any], *, include_source: bool = True) -> tuple[int, ...]:
    target = row.get("target_timerange")
    values = [
        self._timerange_start(target),
        self._timerange_duration(target),
    ]
    if include_source:
        source = row.get("source_timerange")
        values.extend([self._timerange_start(source), self._timerange_duration(source)])
    return tuple(values)


def _plan_quality_audit(self, run_report: RunReport) -> dict[str, Any]:
    validator = run_report.validator_report or {}
    quality = validator.get("quality_gate_report") if isinstance(validator.get("quality_gate_report"), dict) else {}
    visual = validator.get("visual_pacing_gate") if isinstance(validator.get("visual_pacing_gate"), dict) else {}
    caption = validator.get("caption_alignment_gate") if isinstance(validator.get("caption_alignment_gate"), dict) else {}
    caption_repeat = validator.get("final_caption_visible_repeat_gate") if isinstance(validator.get("final_caption_visible_repeat_gate"), dict) else {}
    if not caption_repeat and isinstance(quality.get("final_caption_visible_repeat_gate"), dict):
        caption_repeat = quality.get("final_caption_visible_repeat_gate") or {}
    failures: list[str] = []
    quality_passed = bool(quality.get("gate_passed"))
    visual_passed = bool(visual.get("gate_passed")) and bool(visual.get("visual_pacing_executed")) and bool(
        visual.get("visual_merge_safety_gate_passed", True)
    )
    caption_passed = bool(caption.get("gate_passed")) and bool(caption.get("caption_gui_track_gate_passed", True)) and bool(
        caption.get("subtitle_readability_gate_passed", True)
    )
    caption_repeat_passed = bool(caption_repeat.get("gate_passed")) if caption_repeat else False
    if not quality_passed:
        failures.append("prewrite_quality_gate_not_passed")
    if not visual_passed:
        failures.append("prewrite_visual_pacing_gate_not_passed")
    if not caption_passed:
        failures.append("prewrite_caption_gui_readability_or_alignment_gate_not_passed")
    if not caption_repeat_passed:
        failures.append("prewrite_final_caption_visible_repeat_gate_not_passed")
    return {
        "prewrite_quality_gate_passed": quality_passed,
        "actual_visual_pacing_gate_passed": visual_passed,
        "actual_caption_gui_readability_gate_passed": caption_passed,
        "actual_caption_alignment_gate_passed": bool(caption.get("gate_passed")),
        "actual_final_caption_visible_repeat_gate_passed": caption_repeat_passed,
        "plan_quality_failure_reasons": failures,
    }
