from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aroll_inspect import build_report as inspect_build_report
from aroll_subtitle_style_integrity_gate import is_safe_subtitle_style
from jy_bridge import read_json


def _copy_if_exists(src: Path, dst: Path, copied: list[str]) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(str(dst))


def restore_original_backup(draft_dir: Path, timeline_id: str, backup_dir: Path) -> list[str]:
    backup_dir = Path(backup_dir)
    timeline_dir = Path(draft_dir) / "Timelines" / timeline_id
    restored: list[str] = []
    _copy_if_exists(backup_dir / "timeline" / "draft_content.json", timeline_dir / "draft_content.json", restored)
    _copy_if_exists(backup_dir / "timeline" / "template-2.tmp", timeline_dir / "template-2.tmp", restored)
    _copy_if_exists(backup_dir / "root" / "draft_content.json", Path(draft_dir) / "draft_content.json", restored)
    _copy_if_exists(backup_dir / "root" / "template-2.tmp", Path(draft_dir) / "template-2.tmp", restored)
    if len(restored) < 2:
        raise RuntimeError(f"RESTORE_BACKUP_INCOMPLETE:{backup_dir}:{restored}")
    return restored


def run_post_inspect(draft_dir: Path, run_dir: Path, jy_draftc: Path) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    args = SimpleNamespace(
        draft_dir=Path(draft_dir),
        timeline_name="",
        main_video_track_index=-1,
        main_material_path="",
        jy_draftc=Path(jy_draftc),
        runtime=run_dir / "post_inspect_runtime",
        max_allowed_speed=1.25,
    )
    _inspect_dir, report_path, _subtitle_path = inspect_build_report(args)
    report = read_json(report_path)
    selected_main = report.get("selected_main_video_track") or {}
    selected_text = next((row for row in report.get("text_tracks") or [] if row.get("selected_as_subtitle_track")), {})
    return {
        "inspect_report_path": str(report_path),
        "timeline_id": report.get("timeline_id"),
        "duration_us": int(selected_main.get("total_target_duration_us") or 0),
        "subtitle_segment_count": int(selected_text.get("segment_count") or 0),
        "fatal_reasons": report.get("fatal_reasons") or [],
        "warnings": report.get("warnings") or [],
        "raw_report": report,
    }


def _replace_json_payload_text(value: Any, text: str) -> Any:
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return value
        if isinstance(payload, dict):
            payload["text"] = text
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return value
    if isinstance(value, dict):
        payload = deepcopy(value)
        payload["text"] = text
        return payload
    return value


def set_json_text_payload(obj: Any, text: str) -> None:
    """Update a text material root without rewriting nested style content."""
    if not isinstance(obj, dict):
        return
    for key in ("text", "recognize_text"):
        if isinstance(obj.get(key), str):
            obj[key] = text
    for key in ("content", "base_content"):
        if key in obj:
            obj[key] = _replace_json_payload_text(obj.get(key), text)


def clone_text_material(material: dict[str, Any], new_id: str, text: str) -> dict[str, Any]:
    cloned = deepcopy(material)
    cloned["id"] = new_id
    set_json_text_payload(cloned, text)
    return cloned


def material_text_rows(
    data: dict[str, Any],
    text_track: dict[str, Any],
    source_subtitles: list[dict[str, Any]],
    display_plan: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    material_by_id: dict[str, dict[str, Any]] = {}
    source_by_uid: dict[str, dict[str, Any]] = {}
    source_by_material_id: dict[str, dict[str, Any]] = {}
    safe_sources: list[dict[str, Any]] = []
    for row in source_subtitles:
        material = row.get("material") or {}
        material_id = str(row.get("text_material_id") or material.get("id") or "")
        if material_id:
            material_by_id[material_id] = material
            source_by_material_id[material_id] = row
        subtitle_uid = str(row.get("subtitle_uid") or "")
        if subtitle_uid:
            source_by_uid[subtitle_uid] = row
        if is_safe_subtitle_style(material, row.get("segment") or {}):
            safe_sources.append(row)
    fallback_source = safe_sources[0] if safe_sources else (source_subtitles[0] if source_subtitles else {})
    fallback_material = fallback_source.get("material") or next(iter(material_by_id.values()), {})
    fallback_segment = fallback_source.get("segment") or {}
    materials = data.setdefault("materials", {})
    text_materials = materials.setdefault("texts", [])
    old_ids = {str(row.get("id") or "") for row in text_materials}
    new_segments: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(display_plan, start=1):
        text = str(item.get("fragment_text") or item.get("text") or "")
        source_ids = [str(sid) for sid in (item.get("source_subtitle_uids") or [])]
        selected_source = fallback_source
        for source_id in source_ids:
            candidate = source_by_uid.get(source_id) or {}
            if candidate and is_safe_subtitle_style(candidate.get("material") or {}, candidate.get("segment") or {}):
                selected_source = candidate
                break
        source_material_id = str(selected_source.get("text_material_id") or (selected_source.get("material") or {}).get("id") or "")
        material = material_by_id.get(source_material_id) or fallback_material
        new_material_id = f"aroll_text_{index:06d}"
        while new_material_id in old_ids:
            new_material_id = f"aroll_text_{index:06d}_{len(old_ids)}"
        old_ids.add(new_material_id)
        text_materials.append(clone_text_material(material, new_material_id, text))
        source_segment = (source_by_material_id.get(source_material_id) or {}).get("segment") or fallback_segment
        segment = deepcopy(source_segment)
        segment["id"] = f"aroll_text_segment_{index:06d}"
        segment["material_id"] = new_material_id
        segment["target_timerange"] = {
            "start": int(item.get("target_start_us") or 0),
            "duration": int(item.get("target_duration_us") or 0),
        }
        new_segments.append(segment)
        rows.append(
            {
                "fragment_id": item.get("fragment_id"),
                "text_material_id": new_material_id,
                "text_segment_id": segment["id"],
                "text": text,
                "target_start_us": segment["target_timerange"]["start"],
                "target_duration_us": segment["target_timerange"]["duration"],
            }
        )
    return new_segments, rows


def _norm(text: str) -> str:
    return "".join(ch for ch in str(text or "") if ch.strip())


def post_merge_repeat_check(rows: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    for idx, (left, right) in enumerate(zip(rows, rows[1:]), start=1):
        left_text = str(left.get("fragment_text") or left.get("text") or "")
        right_text = str(right.get("fragment_text") or right.get("text") or "")
        left_n = _norm(left_text)
        right_n = _norm(right_text)
        if not left_n or not right_n:
            continue
        if left_n == right_n:
            issues.append({"issue_id": f"pmr_{idx:03d}", "issue_type": "exact_adjacent_repeat", "left_text": left_text, "right_text": right_text})
        elif len(left_n) >= 4 and right_n.startswith(left_n):
            issues.append({"issue_id": f"pmr_{idx:03d}", "issue_type": "left_contained_in_right", "left_text": left_text, "right_text": right_text})
    return {"issue_count": len(issues), "issues": issues}
