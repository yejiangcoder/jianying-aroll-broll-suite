from __future__ import annotations

from typing import Any, Callable

from aroll_v21.ir.models import RunReport


TimerangeFunc = Callable[[Any], int]


def _video_segments_match_plan(
    actual: list[dict[str, Any]],
    expected: list[dict[str, Any]],
    *,
    segment_timerange_signature: Callable[..., tuple[int, ...]],
) -> bool:
    if len(actual) != len(expected) or not expected:
        return False
    for actual_row, expected_row in zip(actual, expected):
        if str(actual_row.get("id") or "") != str(expected_row.get("id") or ""):
            return False
        if segment_timerange_signature(actual_row) != segment_timerange_signature(expected_row):
            return False
    return True


def _expected_caption_segments_present(
    actual: list[dict[str, Any]],
    expected: list[dict[str, Any]],
    *,
    segment_timerange_signature: Callable[..., tuple[int, ...]],
) -> bool:
    if not expected:
        return False
    actual_by_id = {str(row.get("id") or ""): row for row in actual if str(row.get("id") or "")}
    for expected_row in expected:
        expected_id = str(expected_row.get("id") or "")
        actual_row = actual_by_id.get(expected_id)
        if actual_row is None:
            return False
        if segment_timerange_signature(actual_row, include_source=False) != segment_timerange_signature(
            expected_row,
            include_source=False,
        ):
            return False
        if str(actual_row.get("material_id") or actual_row.get("materialId") or "") != str(
            expected_row.get("material_id") or expected_row.get("materialId") or ""
        ):
            return False
    return True


def _visible_text_rows(
    data: dict[str, Any],
    *,
    is_text_track: Callable[[dict[str, Any]], bool],
    text_segment_text: Callable[[dict[str, Any], dict[str, Any]], str],
    timerange_start: TimerangeFunc,
    timerange_duration: TimerangeFunc,
) -> list[dict[str, Any]]:
    materials = data.get("materials") if isinstance(data.get("materials"), dict) else {}
    text_material_by_id = {
        str(row.get("id") or ""): row
        for row in materials.get("texts") or []
        if isinstance(row, dict) and str(row.get("id") or "")
    }
    rows: list[dict[str, Any]] = []
    for track in data.get("tracks") or []:
        if not isinstance(track, dict) or not is_text_track(track) or not _is_visible_timeline_row(track):
            continue
        track_id = str(track.get("id") or "")
        track_type = str(track.get("type") or track.get("track_type") or "")
        for segment in track.get("segments") or []:
            if not isinstance(segment, dict) or not _is_visible_timeline_row(segment):
                continue
            material_id = str(segment.get("material_id") or segment.get("materialId") or "")
            material = text_material_by_id.get(material_id) or {}
            text = text_segment_text(segment, material)
            if not text.strip():
                continue
            target_start = timerange_start(segment.get("target_timerange"))
            duration = timerange_duration(segment.get("target_timerange"))
            segment_for_classification = dict(segment)
            segment_for_classification.setdefault("track_id", track_id)
            segment_for_classification.setdefault("track_type", track_type)
            rows.append(
                {
                    "track_id": track_id,
                    "track_type": track_type,
                    "segment_id": str(segment.get("id") or ""),
                    "material_id": material_id,
                    "segment": segment_for_classification,
                    "material": material,
                    "text": text,
                    "target_start_us": target_start,
                    "target_end_us": target_start + duration,
                    "duration_us": duration,
                }
            )
    return rows


def _is_visible_timeline_row(row: dict[str, Any]) -> bool:
    for key in ("visible", "is_visible", "enable", "enabled"):
        if row.get(key) is False:
            return False
    for key in ("hidden", "disabled", "is_hidden"):
        if row.get(key) is True:
            return False
    return True


def _text_segment_text(
    segment: dict[str, Any],
    material: dict[str, Any],
    *,
    text_material_text: Callable[[dict[str, Any]], str],
) -> str:
    for key in ("text", "recognize_text"):
        value = segment.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return text_material_text(material)


def _classified_actual_text_rows(
    rows: list[dict[str, Any]],
    *,
    expected_segment_ids: set[str],
    expected_material_ids: set[str],
    template_material_ids: set[str],
    is_confirmed_non_subtitle_text: Callable[[dict[str, Any], dict[str, Any]], bool],
) -> list[dict[str, Any]]:
    classified_rows: list[dict[str, Any]] = []
    for row in rows:
        segment = row["segment"]
        material = row["material"]
        segment_id = str(row.get("segment_id") or "")
        material_id = str(row.get("material_id") or "")
        if segment_id in expected_segment_ids or material_id in expected_material_ids:
            classification = "generated_caption"
            reason = "segment_or_material_id_matches_v21_caption_plan"
            generated_caption_id = True
        elif is_confirmed_non_subtitle_text(segment, material):
            classification = "confirmed_non_subtitle"
            reason = "segment_or_material_metadata_marks_non_subtitle_text"
            generated_caption_id = False
        elif material_id in template_material_ids:
            classification = "old_subtitle_residue"
            reason = "material_id_matches_old_subtitle_template"
            generated_caption_id = False
        else:
            classification = "old_subtitle_residue"
            reason = "visible_caption_like_text_without_confirmed_non_subtitle_metadata"
            generated_caption_id = False
        classified = dict(row)
        classified.update(
            {
                "classification": classification,
                "classification_reason": reason,
                "generated_caption_id": generated_caption_id,
            }
        )
        classified_rows.append(classified)
    return classified_rows


def _actual_text_residue_report(
    *,
    visible_text_rows: list[dict[str, Any]],
    actual_video_segments: list[dict[str, Any]],
    expected_text_segments: list[dict[str, Any]],
    run_report: RunReport,
    classified_actual_text_rows: Callable[..., list[dict[str, Any]]],
    template_candidate_material_ids: Callable[[RunReport], set[str]],
    expected_caption_segments_present: Callable[[list[dict[str, Any]], list[dict[str, Any]]], bool],
    has_containing_video_segment: Callable[[dict[str, Any], list[dict[str, Any]]], bool],
    timerange_start: TimerangeFunc,
    timerange_duration: TimerangeFunc,
) -> dict[str, Any]:
    expected_segment_ids = {str(row.get("id") or "") for row in expected_text_segments if str(row.get("id") or "")}
    expected_material_ids = {
        str(row.get("material_id") or row.get("materialId") or "")
        for row in expected_text_segments
        if str(row.get("material_id") or row.get("materialId") or "")
    }
    expected_material_ids.update(
        str(row.get("id") or "")
        for row in run_report.material_write_plan.get("materials") or []
        if isinstance(row, dict) and str(row.get("id") or "")
    )
    classified_rows = classified_actual_text_rows(
        visible_text_rows,
        expected_segment_ids=expected_segment_ids,
        expected_material_ids=expected_material_ids,
        template_material_ids=template_candidate_material_ids(run_report),
    )
    caption_by_segment_id: dict[str, str] = {}
    caption_by_material_id: dict[str, str] = {}
    for caption, segment in zip(run_report.captions, expected_text_segments):
        segment_id = str(segment.get("id") or "")
        material_id = str(segment.get("material_id") or segment.get("materialId") or "")
        if segment_id:
            caption_by_segment_id[segment_id] = caption.caption_id
        if material_id:
            caption_by_material_id[material_id] = caption.caption_id
    for row in classified_rows:
        if row["classification"] == "generated_caption":
            row["caption_id"] = caption_by_segment_id.get(str(row.get("segment_id") or "")) or caption_by_material_id.get(str(row.get("material_id") or "")) or ""
    generated_rows = [row for row in classified_rows if row["classification"] == "generated_caption"]
    residue_rows = [row for row in classified_rows if row["classification"] == "old_subtitle_residue"]
    preserved_rows = [row for row in classified_rows if row["classification"] == "confirmed_non_subtitle"]
    caption_like_rows = [*generated_rows, *residue_rows]
    final_video_end = max(
        (
            timerange_start(row.get("target_timerange")) + timerange_duration(row.get("target_timerange"))
            for row in actual_video_segments
        ),
        default=0,
    )
    orphan_rows = [
        row
        for row in caption_like_rows
        if not has_containing_video_segment(row, actual_video_segments)
    ]
    text_after_rows = [
        row
        for row in caption_like_rows
        if final_video_end > 0 and int(row.get("target_end_us") or 0) > final_video_end
    ]
    floating_rows = list(orphan_rows)
    expected_present = expected_caption_segments_present([row["segment"] for row in visible_text_rows], expected_text_segments)
    no_extra_caption_like = not residue_rows and not orphan_rows and not text_after_rows and not floating_rows
    exact_match = expected_present and no_extra_caption_like and len(generated_rows) == len(expected_text_segments)
    gate_passed = exact_match
    return {
        "gate_passed": gate_passed,
        "actual_text_residue_gate_passed": gate_passed,
        "expected_caption_rows_present": expected_present,
        "actual_has_no_extra_caption_like_text_segments": no_extra_caption_like,
        "actual_caption_rows_exact_match_plan": exact_match,
        "actual_caption_rows_match_plan": exact_match,
        "actual_text_segment_count": len(visible_text_rows),
        "generated_caption_segment_count": len(generated_rows),
        "preserved_non_subtitle_count": len(preserved_rows),
        "old_subtitle_residue_count": len(residue_rows),
        "orphan_text_segment_count": len(orphan_rows),
        "text_after_final_video_end_count": len(text_after_rows),
        "floating_caption_count": len(floating_rows),
        "final_video_end_us": final_video_end,
        "generated_caption_rows": generated_rows,
        "old_subtitle_residue_segments": residue_rows,
        "orphan_text_segments": orphan_rows,
        "text_after_final_video_end_segments": text_after_rows,
        "floating_caption_segments": floating_rows,
        "preserved_non_subtitle_segments": preserved_rows,
    }
