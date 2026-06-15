from __future__ import annotations

from typing import Any


CLONEABLE_MATERIAL_CATEGORIES = {
    "speeds",
    "effects",
    "canvases",
    "audio_effects",
    "placeholder_infos",
    "realtime_denoises",
    "sound_channel_mappings",
    "material_colors",
    "vocal_separations",
    "material_animations",
    "audio_fades",
    "beats",
    "loudnesses",
    "filters",
    "adjusts",
    "video_effects",
    "sticker_animations",
}


def material_ref_index(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    materials = data.get("materials") or {}
    for category, rows in materials.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            mid = str(row.get("id") or "")
            if not mid:
                continue
            index[mid] = {
                "category": str(category),
                "type": str(row.get("type") or ""),
                "name": str(row.get("name") or row.get("material_name") or ""),
                "path": str(row.get("path") or ""),
                "resource_id": str(row.get("resource_id") or ""),
            }
    return index


def segment_attached_refs(segment: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ("extra_material_refs", "extra_material_refs2"):
        value = segment.get(key)
        if isinstance(value, list):
            refs.extend(str(item) for item in value if item)
    return refs


def inspect_attached_effects(data: dict[str, Any], selected_main_video_track: dict[str, Any] | None) -> dict[str, Any]:
    selected_track_id = str((selected_main_video_track or {}).get("track_id") or "")
    target_track = None
    for track in data.get("tracks") or []:
        if str(track.get("id") or "") == selected_track_id:
            target_track = track
            break
    ref_index = material_ref_index(data)
    rows: list[dict[str, Any]] = []
    unknown_refs: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {}
    ref_count = 0
    if target_track:
        for segment in target_track.get("segments") or []:
            refs = segment_attached_refs(segment)
            for ref in refs:
                ref_count += 1
                meta = ref_index.get(ref)
                if not meta:
                    unknown_refs.append({"segment_id": segment.get("id"), "ref_id": ref})
                    rows.append({"segment_id": segment.get("id"), "ref_id": ref, "category": "unknown", "cloneable": False})
                    continue
                category = str(meta["category"])
                category_counts[category] = category_counts.get(category, 0) + 1
                rows.append(
                    {
                        "segment_id": segment.get("id"),
                        "ref_id": ref,
                        "category": category,
                        "type": meta.get("type"),
                        "name": meta.get("name"),
                        "cloneable": category in CLONEABLE_MATERIAL_CATEGORIES,
                    }
                )
    uncloneable = [row for row in rows if not row.get("cloneable")]
    fatal_reasons = ["UNKNOWN_UNCLONEABLE_ATTACHED_REFS"] if unknown_refs or uncloneable else []
    return {
        "attached_ref_count": ref_count,
        "attached_segment_count": len({str(row.get("segment_id")) for row in rows}),
        "category_counts": category_counts,
        "unknown_uncloneable_ref_count": len(unknown_refs) + len([row for row in uncloneable if row.get("category") != "unknown"]),
        "attached_refs_cloneable": not fatal_reasons,
        "fatal_reasons": fatal_reasons,
        "warnings": ["ATTACHED_REFS_PRESENT_CLONE_REQUIRED"] if ref_count else [],
        "refs": rows[:500],
        "unknown_refs": unknown_refs,
    }


def build_attached_effects_preservation_report(
    old_segments: list[dict[str, Any]],
    new_segments: list[dict[str, Any]],
    video_split_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    def _int_value(value: Any, default: int) -> int:
        return default if value is None else int(value)

    old_by_id = {str(segment.get("id") or ""): segment for segment in old_segments if segment.get("id")}
    split_rows = video_split_rows or []
    checked: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for row in split_rows:
        old_id = str(row.get("old_segment_id") or "")
        old_segment = old_by_id.get(old_id)
        if not old_segment:
            continue
        old_refs = segment_attached_refs(old_segment)
        if not old_refs:
            continue
        new_segment = next(
            (
                segment
                for segment in new_segments
                if _int_value((segment.get("target_timerange") or {}).get("start"), -1)
                == _int_value(row.get("new_target_start_us"), -2)
                and str(segment.get("material_id") or "") == str(row.get("material_id") or "")
            ),
            None,
        )
        new_refs = segment_attached_refs(new_segment or {})
        missing_refs = sorted(set(old_refs) - set(new_refs))
        checked.append(
            {
                "old_segment_id": old_id,
                "new_target_start_us": row.get("new_target_start_us"),
                "old_ref_count": len(old_refs),
                "new_ref_count": len(new_refs),
                "missing_refs": missing_refs,
            }
        )
        if missing_refs:
            failures.append({"old_segment_id": old_id, "missing_refs": missing_refs})
    fatal_reasons = ["ATTACHED_REFS_DROPPED_DURING_CLONE"] if failures else []
    return {
        "checked_segment_count": len(checked),
        "attached_ref_segments_checked": len([row for row in checked if int(row.get("old_ref_count") or 0) > 0]),
        "clone_preservation_passed": not failures,
        "failures": failures,
        "fatal_reasons": fatal_reasons,
        "checked_rows": checked[:500],
    }
