from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _materials(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = (data.get("materials") or {}).get(key) or []
    return [row for row in rows if isinstance(row, dict)]


def _tracks(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in (data.get("tracks") or []) if isinstance(row, dict)]


def _track_segments(track: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in (track.get("segments") or []) if isinstance(row, dict)]


def _text_id(value: Any) -> str:
    return str(value or "")


def _processed_markers(data: dict[str, Any]) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for material in _materials(data, "texts"):
        mid = _text_id(material.get("id"))
        if mid.startswith("aroll_text_"):
            markers.append({"kind": "text_material", "id": mid})
    for track in _tracks(data):
        for segment in _track_segments(track):
            sid = _text_id(segment.get("id"))
            mid = _text_id(segment.get("material_id"))
            if sid.startswith("aroll_text_segment_") or mid.startswith("aroll_text_"):
                markers.append(
                    {
                        "kind": "text_segment",
                        "track_id": track.get("id"),
                        "segment_id": sid,
                        "material_id": mid,
                    }
                )
    return markers


def _selected_main(inspect_report: dict[str, Any]) -> dict[str, Any]:
    return dict(inspect_report.get("selected_main_video_track") or {})


def _selected_subtitle_track(inspect_report: dict[str, Any]) -> dict[str, Any]:
    for row in inspect_report.get("text_tracks") or []:
        if row.get("selected_as_subtitle_track"):
            return dict(row)
    rows = list(inspect_report.get("text_tracks") or [])
    return dict(rows[0]) if rows else {}


def _main_material_ids(selected_main: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for material in selected_main.get("materials") or []:
        mid = _text_id(material.get("material_id") or material.get("id"))
        if mid:
            ids.append(mid)
    return sorted(set(ids))


def _fingerprint(parts: dict[str, Any]) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_source_draft_fingerprint(
    inspect_report: dict[str, Any],
    data: dict[str, Any],
) -> dict[str, Any]:
    selected_main = _selected_main(inspect_report)
    selected_text = _selected_subtitle_track(inspect_report)
    timeline_id = _text_id(inspect_report.get("timeline_id") or data.get("id"))
    duration_us = int(selected_main.get("total_target_duration_us") or inspect_report.get("duration_us") or data.get("duration") or 0)
    subtitle_count = int(selected_text.get("segment_count") or inspect_report.get("subtitle_segment_count") or 0)
    parts = {
        "timeline_id": timeline_id,
        "current_source_duration_us": duration_us,
        "current_source_subtitle_count": subtitle_count,
        "main_video_material_ids": _main_material_ids(selected_main),
        "subtitle_track_id": _text_id(selected_text.get("track_id") or selected_text.get("id")),
    }
    parts["draft_fingerprint"] = _fingerprint(parts)
    return parts


def audit_source_draft_integrity(
    inspect_report: dict[str, Any],
    data: dict[str, Any],
    *,
    clean_baseline: dict[str, Any] | None = None,
    clean_source_duration_us: int | None = None,
    clean_source_subtitle_count: int | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    fingerprint = build_source_draft_fingerprint(inspect_report, data)
    markers = _processed_markers(data)
    clean = clean_baseline or {}
    if clean:
        clean_source_duration_us = int(clean.get("clean_source_duration_us") or clean.get("current_source_duration_us") or clean_source_duration_us or 0)
        clean_source_subtitle_count = int(clean.get("clean_source_subtitle_count") or clean.get("current_source_subtitle_count") or clean_source_subtitle_count or 0)
    clean_source_duration_us = int(clean_source_duration_us or 0)
    clean_source_subtitle_count = int(clean_source_subtitle_count or 0)
    current_source_duration_us = int(fingerprint.get("current_source_duration_us") or 0)
    current_source_subtitle_count = int(fingerprint.get("current_source_subtitle_count") or 0)
    source_duration_ratio = (
        current_source_duration_us / clean_source_duration_us
        if clean_source_duration_us > 0
        else 1.0
    )
    subtitle_count_ratio = (
        current_source_subtitle_count / clean_source_subtitle_count
        if clean_source_subtitle_count > 0
        else 1.0
    )
    fatal_reasons: list[str] = []
    if clean and clean.get("draft_fingerprint") and clean.get("draft_fingerprint") != fingerprint.get("draft_fingerprint"):
        fatal_reasons.append("SOURCE_DRAFT_FINGERPRINT_MISMATCH")
    if clean_source_duration_us > 0 and source_duration_ratio < 0.90:
        fatal_reasons.append("SOURCE_DURATION_BELOW_CLEAN_BASELINE")
    if clean_source_subtitle_count > 0 and subtitle_count_ratio < 0.90:
        fatal_reasons.append("SUBTITLE_COUNT_BELOW_CLEAN_BASELINE")
    if markers:
        fatal_reasons.append("PROCESSED_AROLL_OUTPUT_MARKERS_FOUND")
    detected_processed = bool(markers)
    report = {
        "source_draft_integrity_gate_passed": not fatal_reasons,
        "detected_as_processed_aroll_output": detected_processed,
        "clean_baseline_available": bool(clean),
        "clean_source_duration_s": round(clean_source_duration_us / 1_000_000, 3) if clean_source_duration_us else None,
        "current_source_duration_s": round(current_source_duration_us / 1_000_000, 3),
        "clean_source_subtitle_count": clean_source_subtitle_count or None,
        "current_source_subtitle_count": current_source_subtitle_count,
        "source_duration_ratio": round(source_duration_ratio, 4),
        "subtitle_count_ratio": round(subtitle_count_ratio, 4),
        "timeline_id": fingerprint.get("timeline_id"),
        "main_video_material_ids": fingerprint.get("main_video_material_ids"),
        "subtitle_track_id": fingerprint.get("subtitle_track_id"),
        "draft_fingerprint": fingerprint.get("draft_fingerprint"),
        "processed_markers": markers[:100],
        "fatal_reasons": sorted(set(fatal_reasons)),
    }
    if output_path:
        write_json(output_path, report)
    return report
