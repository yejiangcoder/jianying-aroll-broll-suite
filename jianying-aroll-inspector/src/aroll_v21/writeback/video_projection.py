from __future__ import annotations

from typing import Any


def configure_writeback_dependencies(dependencies: dict[str, Any]) -> None:
    globals().update(dependencies)


def _gapless_caption_video_projection_plan(self, run_report: RunReport) -> dict[str, Any]:
    final_by_id = {segment.segment_id: segment for segment in run_report.final_timeline}
    words = sorted(
        list(run_report.source_graph.words if run_report.source_graph is not None else []),
        key=lambda word: (int(word.source_start_us), int(word.source_end_us), str(word.word_id)),
    )
    captions_by_final_id: dict[str, list[CaptionRenderUnit]] = {}
    caption_target_ranges: dict[str, dict[str, int]] = {}
    missing_caption_segment_ids: list[str] = []
    for caption in sorted(run_report.captions, key=lambda row: (int(row.target_start_us), int(row.target_end_us), str(row.caption_id))):
        final_ids = self._caption_final_segment_ids(caption)
        if not final_ids:
            missing_caption_segment_ids.append(str(caption.caption_id))
            continue
        target_start = int(caption.target_start_us)
        target_end = int(caption.target_end_us)
        if target_end <= target_start:
            raise WritebackError(
                "V21_WRITEBACK_CAPTION_SOURCE_SPAN_MISSING",
                "caption cannot be projected to video because its target span is empty",
                {"caption_id": caption.caption_id, "target_start_us": target_start, "target_end_us": target_end},
            )
        missing_ids = [final_id for final_id in final_ids if final_id not in final_by_id]
        if missing_ids:
            missing_caption_segment_ids.append(str(caption.caption_id))
            continue
        for final_id in final_ids:
            captions_by_final_id.setdefault(final_id, []).append(caption)
    if missing_caption_segment_ids:
        raise WritebackError(
            "V21_WRITEBACK_CAPTION_SOURCE_SPAN_MISSING",
            "one or more captions do not have a containing final video segment",
            {"caption_ids": missing_caption_segment_ids[:20], "missing_caption_count": len(missing_caption_segment_ids)},
        )
    if not run_report.final_timeline and run_report.captions:
        raise WritebackError(
            "V21_WRITEBACK_CAPTION_SOURCE_SPAN_MISSING",
            "no final timeline video units were available for caption writeback",
            {"final_timeline_segment_count": len(run_report.final_timeline), "caption_count": len(run_report.captions)},
        )

    units: list[FinalTimelineSegment] = []
    target_cursor = 0
    for final_segment in sorted(
        run_report.final_timeline,
        key=lambda row: (int(row.target_start_us), int(row.target_end_us), str(row.segment_id)),
    ):
        segment_captions = sorted(
            captions_by_final_id.get(str(final_segment.segment_id), []),
            key=lambda row: (int(row.target_start_us), int(row.target_end_us), str(row.caption_id)),
        )
        groups = self._final_segment_video_projection_groups(final_segment, segment_captions, words)
        if not groups:
            continue
        segment_original_target_start = int(groups[0]["original_target_start_us"])
        segment_target_delta = int(target_cursor) - segment_original_target_start
        projected_groups: list[dict[str, Any]] = []
        for group_index, group in enumerate(groups, start=1):
            group_source_start = int(group["source_start_us"])
            group_source_end = int(group["source_end_us"])
            group_duration = max(0, group_source_end - group_source_start)
            if group_duration <= 0:
                continue
            group_target_start = target_cursor
            group_target_end = group_target_start + group_duration
            target_cursor = group_target_end
            projected_groups.append(
                {
                    **group,
                    "projected_target_start_us": group_target_start,
                    "projected_target_end_us": group_target_end,
                }
            )
            debug_hints = dict(final_segment.debug_hints)
            debug_hints["safe_handle_policy_enabled"] = False
            if bool(group.get("source_projection_required")):
                debug_hints.update(
                    {
                        "writeback_source_projection": True,
                        "writeback_projection_split_index": group_index,
                        "writeback_projection_split_count": len(groups),
                        "writeback_original_final_segment_id": final_segment.segment_id,
                    }
                )
            units.append(
                FinalTimelineSegment(
                    segment_id=final_segment.segment_id,
                    source_material_id=final_segment.source_material_id,
                    source_segment_id=final_segment.source_segment_id,
                    source_start_us=group_source_start,
                    source_end_us=group_source_end,
                    target_start_us=group_target_start,
                    target_end_us=group_target_end,
                    word_ids=list(group["word_ids"]),
                    text=final_segment.text,
                    decision_ids=list(final_segment.decision_ids),
                    spoken_source_start_us=group_source_start,
                    spoken_source_end_us=group_source_end,
                    clip_source_start_us=group_source_start,
                    clip_source_end_us=group_source_end,
                    lead_handle_us=0,
                    tail_handle_us=0,
                    debug_hints=debug_hints,
                )
            )
        self._apply_caption_ranges_for_projected_segment(
            caption_target_ranges,
            segment_captions,
            projected_groups,
            default_delta_us=segment_target_delta,
        )
    return {
        "video_units": units,
        "caption_target_ranges": caption_target_ranges,
        "caption_repacked_count": len(caption_target_ranges),
        "final_video_end_us": int(target_cursor),
        "video_write_plan_gapless": True,
    }


def _video_projection_units_from_caption_spans(self, run_report: RunReport) -> list[FinalTimelineSegment]:
    return list(self._gapless_caption_video_projection_plan(run_report)["video_units"])


def _apply_gapless_caption_ranges(
    self,
    text_segments: list[dict[str, Any]],
    captions: list[CaptionRenderUnit],
    caption_target_ranges: dict[str, dict[str, int]],
) -> None:
    missing_caption_ids: list[str] = []
    for caption, segment in zip(captions, text_segments):
        caption_range = caption_target_ranges.get(str(caption.caption_id))
        if caption_range is None:
            missing_caption_ids.append(str(caption.caption_id))
            continue
        target_start = int(caption_range["target_start_us"])
        target_end = int(caption_range["target_end_us"])
        if target_end <= target_start:
            raise WritebackError(
                "V21_WRITEBACK_CAPTION_SOURCE_SPAN_MISSING",
                "caption gapless target range is empty",
                {"caption_id": caption.caption_id, "target_start_us": target_start, "target_end_us": target_end},
            )
        segment["target_timerange"] = {"start": target_start, "duration": target_end - target_start}
    if missing_caption_ids or len(text_segments) != len(captions):
        raise WritebackError(
            "V21_WRITEBACK_CAPTION_SOURCE_SPAN_MISSING",
            "caption write segments cannot be matched to gapless projection ranges",
            {
                "missing_caption_ids": missing_caption_ids[:20],
                "missing_caption_count": len(missing_caption_ids),
                "caption_count": len(captions),
                "text_segment_count": len(text_segments),
            },
        )


def _caption_final_segment_ids(self, caption: CaptionRenderUnit) -> list[str]:
    ids: list[str] = []
    for segment_id in caption.timeline_segment_ids:
        segment_id = str(segment_id or "")
        if segment_id and segment_id not in ids:
            ids.append(segment_id)
    containing_id = str(caption.containing_video_segment_id or "")
    if containing_id and containing_id not in ids:
        ids.append(containing_id)
    return ids


def _final_segment_video_projection_groups(
    self,
    final_segment: FinalTimelineSegment,
    segment_captions: list[CaptionRenderUnit],
    words: list[Any],
) -> list[dict[str, Any]]:
    source_start = int(final_segment.source_start_us)
    source_end = int(final_segment.source_end_us)
    target_start = int(final_segment.target_start_us)
    target_end = int(final_segment.target_end_us)
    if source_end <= source_start or target_end <= target_start:
        return []
    if not segment_captions and final_segment.word_ids:
        return []
    captioned_word_ids = {str(word_id) for caption in segment_captions for word_id in caption.word_ids}
    spoken_start = int(final_segment.spoken_source_start_us) if final_segment.spoken_source_start_us is not None else source_start
    spoken_end = int(final_segment.spoken_source_end_us) if final_segment.spoken_source_end_us is not None else source_end
    uncaptioned_speech_words = [
        word
        for word in words
        if str(word.word_id) not in captioned_word_ids
        and self._ranges_overlap(int(word.source_start_us), int(word.source_end_us), source_start, source_end)
        and self._ranges_overlap(int(word.source_start_us), int(word.source_end_us), spoken_start, spoken_end)
    ]
    if not uncaptioned_speech_words:
        return [
            {
                "source_start_us": source_start,
                "source_end_us": source_end,
                "original_target_start_us": target_start,
                "original_target_end_us": target_end,
                "word_ids": list(final_segment.word_ids),
                "caption_ids": [str(caption.caption_id) for caption in segment_captions],
                "source_projection_required": False,
            }
        ]
    kept_words = [
        word
        for word in words
        if str(word.word_id) in captioned_word_ids
        and self._ranges_overlap(int(word.source_start_us), int(word.source_end_us), source_start, source_end)
    ]
    if not kept_words:
        return [
            {
                "source_start_us": source_start,
                "source_end_us": source_end,
                "original_target_start_us": target_start,
                "original_target_end_us": target_end,
                "word_ids": list(final_segment.word_ids),
                "caption_ids": [str(caption.caption_id) for caption in segment_captions],
                "source_projection_required": False,
            }
        ]
    groups: list[list[Any]] = [[kept_words[0]]]
    for previous, current in zip(kept_words, kept_words[1:]):
        gap_start = int(previous.source_end_us)
        gap_end = int(current.source_start_us)
        split_for_uncaptioned_speech = any(
            self._ranges_overlap(int(word.source_start_us), int(word.source_end_us), gap_start, gap_end)
            for word in uncaptioned_speech_words
        )
        if split_for_uncaptioned_speech:
            groups.append([current])
        else:
            groups[-1].append(current)
    projection_groups: list[dict[str, Any]] = []
    for group in groups:
        caption_ids = self._caption_ids_for_word_group(group, segment_captions)
        group_captions = [caption for caption in segment_captions if str(caption.caption_id) in set(caption_ids)]
        projection_groups.append(
            {
                "source_start_us": min(int(word.source_start_us) for word in group),
                "source_end_us": max(int(word.source_end_us) for word in group),
                "original_target_start_us": min((int(caption.target_start_us) for caption in group_captions), default=target_start),
                "original_target_end_us": max((int(caption.target_end_us) for caption in group_captions), default=target_end),
                "word_ids": [str(word.word_id) for word in group],
                "caption_ids": caption_ids,
                "source_projection_required": True,
            }
        )
    return projection_groups


def _caption_ids_for_word_group(self, words: list[Any], captions: list[CaptionRenderUnit]) -> list[str]:
    group_word_ids = {str(word.word_id) for word in words}
    caption_ids: list[str] = []
    for caption in captions:
        if group_word_ids.intersection(str(word_id) for word_id in caption.word_ids):
            caption_ids.append(str(caption.caption_id))
    return caption_ids


def _apply_caption_ranges_for_projected_segment(
    self,
    caption_target_ranges: dict[str, dict[str, int]],
    captions: list[CaptionRenderUnit],
    projected_groups: list[dict[str, Any]],
    *,
    default_delta_us: int,
) -> None:
    source_projected = any(bool(group.get("source_projection_required")) for group in projected_groups)
    groups_by_caption: dict[str, list[dict[str, Any]]] = {}
    for group in projected_groups:
        for caption_id in group.get("caption_ids") or []:
            groups_by_caption.setdefault(str(caption_id), []).append(group)
    for caption in captions:
        caption_id = str(caption.caption_id)
        caption_groups = groups_by_caption.get(caption_id) or []
        if source_projected and len(caption_groups) > 1:
            start = min(int(group["projected_target_start_us"]) for group in caption_groups)
            end = max(int(group["projected_target_end_us"]) for group in caption_groups)
        elif source_projected and len(caption_groups) == 1:
            group = caption_groups[0]
            group_delta = int(group["projected_target_start_us"]) - int(group["original_target_start_us"])
            start = int(caption.target_start_us) + group_delta
            end = int(caption.target_end_us) + group_delta
        else:
            start = int(caption.target_start_us) + int(default_delta_us)
            end = int(caption.target_end_us) + int(default_delta_us)
        if end <= start:
            raise WritebackError(
                "V21_WRITEBACK_CAPTION_SOURCE_SPAN_MISSING",
                "caption projected target range is empty",
                {"caption_id": caption.caption_id, "target_start_us": start, "target_end_us": end},
            )
        self._merge_caption_target_range(caption_target_ranges, caption_id, start, end)


def _merge_caption_target_range(
    self,
    caption_target_ranges: dict[str, dict[str, int]],
    caption_id: str,
    target_start_us: int,
    target_end_us: int,
) -> None:
    existing = caption_target_ranges.get(caption_id)
    if existing is None:
        caption_target_ranges[caption_id] = {
            "target_start_us": int(target_start_us),
            "target_end_us": int(target_end_us),
        }
        return
    caption_target_ranges[caption_id] = {
        "target_start_us": min(int(existing["target_start_us"]), int(target_start_us)),
        "target_end_us": max(int(existing["target_end_us"]), int(target_end_us)),
    }


def _caption_spoken_source_span(
    self,
    caption: CaptionRenderUnit,
    word_by_id: dict[str, Any],
) -> tuple[int | None, int | None]:
    explicit_start = int(caption.spoken_source_start_us) if caption.spoken_source_start_us is not None else None
    explicit_end = int(caption.spoken_source_end_us) if caption.spoken_source_end_us is not None else None
    words = [word_by_id[str(word_id)] for word_id in caption.word_ids if str(word_id) in word_by_id]
    if words:
        word_start = min(int(word.source_start_us) for word in words)
        word_end = max(int(word.source_end_us) for word in words)
        if explicit_start is not None and explicit_end is not None and not (explicit_start <= word_start and word_end <= explicit_end):
            return explicit_start, explicit_end
        return word_start, word_end
    if explicit_start is not None and explicit_end is not None:
        return explicit_start, explicit_end
    return None, None


def _caption_video_source_groups(
    self,
    caption: CaptionRenderUnit,
    words: list[Any],
    *,
    source_start: int,
    source_end: int,
) -> list[dict[str, Any]]:
    caption_word_ids = {str(word_id) for word_id in caption.word_ids}
    kept_words = sorted(
        [
            word
            for word in words
            if str(word.word_id) in caption_word_ids
            and self._ranges_overlap(int(word.source_start_us), int(word.source_end_us), int(source_start), int(source_end))
        ],
        key=lambda word: (int(word.source_start_us), int(word.source_end_us), str(word.word_id)),
    )
    if not kept_words:
        return [{"source_start_us": int(source_start), "source_end_us": int(source_end), "word_ids": list(caption.word_ids)}]
    groups: list[list[Any]] = [[kept_words[0]]]
    for previous, current in zip(kept_words, kept_words[1:]):
        gap_start = int(previous.source_end_us)
        gap_end = int(current.source_start_us)
        split_for_dropped_speech = any(
            str(word.word_id) not in caption_word_ids
            and self._ranges_overlap(int(word.source_start_us), int(word.source_end_us), gap_start, gap_end)
            for word in words
        )
        if split_for_dropped_speech:
            groups.append([current])
        else:
            groups[-1].append(current)
    return [
        {
            "source_start_us": min(int(word.source_start_us) for word in group),
            "source_end_us": max(int(word.source_end_us) for word in group),
            "word_ids": [str(word.word_id) for word in group],
        }
        for group in groups
    ]


def _video_segment_from_template(self, template: dict[str, Any], final_segment, index: int, draft_data: dict[str, Any]) -> dict[str, Any]:
    speed = self._segment_speed(template, draft_data)
    row = project_video_segment_from_template(template, final_segment, index, speed)
    row["_v21_audio_coverage"] = {
        "timeline_segment_id": str(final_segment.segment_id),
        "caption_id": str((final_segment.debug_hints or {}).get("writeback_caption_id") or ""),
        "source_start_us": int(final_segment.source_start_us),
        "source_end_us": int(final_segment.source_end_us),
        "spoken_source_start_us": int(
            final_segment.spoken_source_start_us if final_segment.spoken_source_start_us is not None else final_segment.source_start_us
        ),
        "spoken_source_end_us": int(
            final_segment.spoken_source_end_us if final_segment.spoken_source_end_us is not None else final_segment.source_end_us
        ),
        "word_ids": list(final_segment.word_ids),
    }
    return row


def _effective_speed_report(self, video_segments: list[dict[str, Any]]) -> dict[str, Any]:
    speeds: list[float] = []
    drift_count = 0
    for row in video_segments:
        speed = self._effective_speed_from_row(row)
        if speed is None:
            continue
        speeds.append(speed)
        if not self._effective_speed_supported_or_baseline(speed):
            drift_count += 1
    report = {
        "effective_speed_min": min(speeds, default=None),
        "effective_speed_max": max(speeds, default=None),
        "effective_speed_drift_count": drift_count,
    }
    report.update(safe_handle_report_from_projected_segments(video_segments))
    return report


def _effective_speed_from_row(self, row: dict[str, Any]) -> float | None:
    source_timerange = row.get("source_timerange")
    target_timerange = row.get("target_timerange")
    source_duration = self._timerange_duration(source_timerange)
    target_duration = self._timerange_duration(target_timerange)
    if source_duration <= 0 or target_duration <= 0:
        return None
    return round(source_duration / target_duration, 6)


def _effective_speed_supported_or_baseline(self, speed: float) -> bool:
    return any(abs(speed - candidate) <= EFFECTIVE_SPEED_TOLERANCE for candidate in (1.0, 1.2))
