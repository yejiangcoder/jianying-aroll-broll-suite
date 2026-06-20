from __future__ import annotations

import json
from typing import Any

from aroll_v21.ir.models import RunReport


def _select_subtitle_track_id(
    data: dict[str, Any],
    text_segments: list[dict[str, Any]],
    template_material_ids: set[str],
    *,
    error_cls,
) -> str:
    if not template_material_ids:
        raise error_cls("V21_WRITEBACK_SUBTITLE_TRACK_NOT_FOUND", "canonical template report has no subtitle candidate material ids")
    counts: dict[str, int] = {}
    for segment in text_segments:
        material_id = str(segment.get("material_id") or segment.get("materialId") or "")
        if material_id not in template_material_ids:
            continue
        track_id = str(segment.get("track_id") or "")
        segment_id = str(segment.get("id") or "")
        if not track_id or not segment_id or not material_id:
            continue
        counts[track_id] = counts.get(track_id, 0) + 1
    if not counts:
        raise error_cls(
            "V21_WRITEBACK_SUBTITLE_TRACK_NOT_FOUND",
            "subtitle candidate materials are not bound to a text track",
            {"candidate_material_ids": sorted(template_material_ids)},
        )
    max_count = max(counts.values())
    winners = sorted(track_id for track_id, count in counts.items() if count == max_count)
    if len(winners) != 1:
        raise error_cls(
            "V21_WRITEBACK_SUBTITLE_TRACK_NOT_UNIQUE",
            "subtitle-bound text segments map to multiple equally likely text tracks",
            {"candidate_track_counts": counts},
        )
    track_id = winners[0]
    track = _track_by_id(data, track_id)
    if track is None or not _is_text_track(track):
        raise error_cls(
            "V21_WRITEBACK_SUBTITLE_TRACK_NOT_FOUND",
            "selected subtitle-bound track_id is not a text/subtitle track",
            {"selected_text_track_id": track_id},
        )
    return track_id


def _template_candidate_material_ids(run_report: RunReport) -> set[str]:
    template_report = (run_report.material_write_plan or {}).get("template_report") or {}
    candidate_ids = {
        str(value)
        for value in template_report.get("candidate_material_ids") or []
        if str(value or "")
    }
    representative = str(template_report.get("representative_material_id") or "")
    canonical = str((run_report.material_write_plan or {}).get("canonical_caption_template_id") or "")
    candidate_ids.update(value for value in (representative, canonical) if value)
    return candidate_ids


def _subtitle_bound_track_ids(text_segments: list[dict[str, Any]], template_material_ids: set[str], *, error_cls) -> set[str]:
    track_ids = {
        str(row.get("track_id") or "")
        for row in text_segments
        if str(row.get("material_id") or row.get("materialId") or "") in template_material_ids and str(row.get("track_id") or "")
    }
    if not track_ids:
        raise error_cls(
            "V21_WRITEBACK_SUBTITLE_TRACK_NOT_FOUND",
            "subtitle candidate materials are not bound to any text track",
            {"candidate_material_ids": sorted(template_material_ids)},
        )
    return track_ids


def _classified_text_segments_by_track(
    text_segments: list[dict[str, Any]],
    subtitle_track_ids: set[str],
    template_material_ids: set[str],
    text_material_by_id: dict[str, dict[str, Any]],
    *,
    error_cls,
) -> dict[str, list[dict[str, Any]]]:
    by_track: dict[str, list[dict[str, Any]]] = {track_id: [] for track_id in subtitle_track_ids}
    for row in text_segments:
        track_id = str(row.get("track_id") or "")
        if track_id not in subtitle_track_ids:
            continue
        classified = _classify_text_segment(row, template_material_ids, text_material_by_id)
        by_track.setdefault(track_id, []).append(classified)
    if not any(
        classified["classification"] == "confirmed_subtitle_bound"
        for rows in by_track.values()
        for classified in rows
    ):
        raise error_cls(
            "V21_WRITEBACK_OLD_SUBTITLE_SEGMENTS_UNBOUND",
            "no old subtitle-bound text segments matched canonical template candidates",
            {"subtitle_track_ids": sorted(subtitle_track_ids), "candidate_material_ids": sorted(template_material_ids)},
        )
    return by_track


def _classify_text_segment(
    segment: dict[str, Any],
    template_material_ids: set[str],
    text_material_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    material_id = str(segment.get("material_id") or segment.get("materialId") or "")
    material = text_material_by_id.get(material_id) or {}
    text = _text_material_text(material)
    if not material_id:
        classification = "unknown_unsafe"
        reason = "text segment has no material_id"
    elif material_id in template_material_ids:
        classification = "confirmed_subtitle_bound"
        reason = "material_id_matches_canonical_subtitle_template"
    elif _is_confirmed_non_subtitle_text(segment, material):
        classification = "confirmed_non_subtitle"
        reason = "segment_or_material_metadata_marks_non_subtitle_text"
    else:
        classification = "unknown_unsafe"
        reason = "text segment is on a subtitle-bound track but lacks subtitle or non-subtitle metadata"
    return {
        "classification": classification,
        "reason": reason,
        "segment": segment,
        "material": material,
        "text": text,
    }


def _is_confirmed_non_subtitle_text(segment: dict[str, Any], material: dict[str, Any]) -> bool:
    non_subtitle_tokens = ("title", "callout", "overlay", "note", "sticker", "label")
    explicit_false_keys = ("is_subtitle", "is_caption", "subtitle", "caption")
    for row in (segment, material):
        for key in explicit_false_keys:
            if row.get(key) is False:
                return True
    metadata_values = [
        segment.get("id"),
        segment.get("track_id"),
        segment.get("type"),
        segment.get("role"),
        segment.get("name"),
        segment.get("category"),
        material.get("id"),
        material.get("type"),
        material.get("role"),
        material.get("name"),
        material.get("category"),
    ]
    for value in metadata_values:
        text = str(value or "").lower()
        if any(_metadata_token_matches(text, token) for token in non_subtitle_tokens):
            return True
    return False


def _metadata_token_matches(text: str, token: str) -> bool:
    normalized = "".join(char if char.isalnum() else "_" for char in text.lower())
    parts = [part for part in normalized.split("_") if part]
    return token in parts


def _text_material_text(material: dict[str, Any]) -> str:
    for key in ("text", "recognize_text"):
        value = material.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for key in ("content", "base_content"):
        value = material.get(key)
        if isinstance(value, str):
            try:
                payload = json.loads(value)
            except json.JSONDecodeError:
                continue
        elif isinstance(value, dict):
            payload = value
        else:
            continue
        if isinstance(payload, dict):
            text = payload.get("text")
            if isinstance(text, str) and text.strip():
                return text
    return ""


def _old_subtitle_segments_by_track(
    text_segments: list[dict[str, Any]],
    subtitle_track_ids: set[str],
    template_material_ids: set[str],
    *,
    error_cls,
) -> dict[str, list[dict[str, Any]]]:
    by_track: dict[str, list[dict[str, Any]]] = {track_id: [] for track_id in subtitle_track_ids}
    for row in text_segments:
        track_id = str(row.get("track_id") or "")
        if track_id not in subtitle_track_ids:
            continue
        material_id = str(row.get("material_id") or row.get("materialId") or "")
        if not material_id:
            raise error_cls(
                "V21_WRITEBACK_OLD_SUBTITLE_SEGMENTS_UNBOUND",
                "subtitle-bound text segment has no material_id",
                {"selected_text_track_id": track_id, "segment_id": str(row.get("id") or "")},
            )
        if material_id in template_material_ids:
            by_track.setdefault(track_id, []).append(row)
    if not any(by_track.values()):
        raise error_cls(
            "V21_WRITEBACK_OLD_SUBTITLE_SEGMENTS_UNBOUND",
            "no old subtitle-bound text segments matched canonical template candidates",
            {"subtitle_track_ids": sorted(subtitle_track_ids), "candidate_material_ids": sorted(template_material_ids)},
        )
    return by_track


def _select_video_track_id_from_templates(used_templates: list[dict[str, Any]], run_report: RunReport, *, error_cls) -> str:
    if not used_templates or len(used_templates) != len(run_report.final_timeline):
        raise error_cls(
            "V21_WRITEBACK_SOURCE_SEGMENT_TEMPLATE_MISSING",
            "final_timeline source templates could not be fully resolved",
            {"final_timeline_segment_count": len(run_report.final_timeline), "resolved_source_segment_template_count": len(used_templates)},
        )
    track_ids = {
        str(template.get("track_id") or "")
        for template in used_templates
    }
    if "" in track_ids:
        raise error_cls(
            "V21_WRITEBACK_MAIN_VIDEO_TRACK_NOT_FOUND",
            "source segment templates do not include track_id",
            {"used_source_segment_ids": sorted(str(template.get("id") or "") for template in used_templates)},
        )
    if len(track_ids) != 1:
        raise error_cls(
            "V21_WRITEBACK_MULTIPLE_SOURCE_VIDEO_TRACKS_UNSUPPORTED",
            "final_timeline uses source segments from multiple video tracks",
            {"used_video_track_ids": sorted(track_ids)},
        )
    return next(iter(track_ids))


def _track_by_id(data: dict[str, Any], track_id: str) -> dict[str, Any] | None:
    for track in data.get("tracks") or []:
        if not isinstance(track, dict):
            continue
        if str(track.get("id") or "") == track_id:
            return track
    return None


def _is_text_track(track: dict[str, Any]) -> bool:
    track_type = str(track.get("type") or track.get("track_type") or "").lower()
    return "text" in track_type or "subtitle" in track_type


def _is_video_track(track: dict[str, Any]) -> bool:
    track_type = str(track.get("type") or track.get("track_type") or "").lower()
    return "video" in track_type


def _track_type_contains(track: dict[str, Any], token: str) -> bool:
    return token in str(track.get("type") or track.get("track_type") or "").lower()
