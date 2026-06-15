from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from direct_draft_broll_writer import (
    AI_TRACK_NAME,
    DEFAULT_JY_DRAFTC,
    DEFAULT_RUNTIME,
    PHOTO_DURATION_US,
    assert_all_project_timeline_files_match_folder_ids,
    assert_layout_has_no_duplicate_timeline_ids,
    assert_timeline_content_id,
    decrypt,
    encrypt,
    guid,
    helper_materials,
    image_id_from_filename,
    image_id_sort_key,
    png_size,
    read_json,
    resolve_timeline_id,
    root_mirrors_timeline_id,
    update_key_value,
    write_json,
)


def load_plan(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows = list(csv.DictReader(path.open("r", encoding="utf-8-sig")))
    write_rows: list[dict[str, Any]] = []
    skip_ids: list[str] = []
    for row in rows:
        image_id = str(row.get("image_id") or "").zfill(2)
        action = str(row.get("action") or "").strip()
        if action == "skip":
            skip_ids.append(image_id)
            continue
        if action != "write":
            raise RuntimeError(f"非法 action：image_id={image_id}, action={action}")
        image_path = Path(str(row.get("image_path") or ""))
        if not image_path.exists():
            raise FileNotFoundError(f"图片不存在：image_id={image_id}, path={image_path}")
        start_sec = float(row.get("final_start_sec") or "")
        write_rows.append(
            {
                "image_id": image_id,
                "image_path": image_path,
                "start_us": int(round(start_sec * 1_000_000)),
                "start_sec": start_sec,
                "duration_us": PHOTO_DURATION_US,
                "duration_sec": PHOTO_DURATION_US / 1_000_000,
                "subtitle_index": row.get("final_subtitle_index") or "",
                "subtitle_text": row.get("final_subtitle_text") or "",
                "image_description": row.get("image_description") or "",
            }
        )
    write_rows.sort(key=lambda r: (r["start_us"], image_id_sort_key(r["image_id"])))
    return write_rows, sorted(skip_ids, key=image_id_sort_key)


def remove_existing_ai_broll(data: dict[str, Any]) -> dict[str, set[str]]:
    removed_ids: set[str] = set()
    removed_names: set[str] = set()
    kept_tracks = []
    for track in data.get("tracks", []):
        if track.get("name") == AI_TRACK_NAME:
            for segment in track.get("segments", []):
                material_id = segment.get("material_id")
                if material_id:
                    removed_ids.add(material_id)
            continue
        kept_tracks.append(track)
    data["tracks"] = kept_tracks
    if removed_ids:
        kept_videos = []
        for material in data["materials"].get("videos", []):
            if material.get("id") in removed_ids:
                if material.get("material_name"):
                    removed_names.add(str(material.get("material_name")))
                continue
            kept_videos.append(material)
        data["materials"]["videos"] = kept_videos
    return {"ids": removed_ids, "names": removed_names}


def choose_ai_track_layer(data: dict[str, Any]) -> int:
    filter_layers = [
        int(segment.get("track_render_index") or 0)
        for track in data.get("tracks", [])
        if track.get("type") == "filter"
        for segment in track.get("segments", [])
        if segment.get("track_render_index") is not None
    ]
    text_layers = [
        int(segment.get("track_render_index") or 0)
        for track in data.get("tracks", [])
        if track.get("type") == "text"
        for segment in track.get("segments", [])
        if segment.get("track_render_index") is not None
    ]
    max_filter = max(filter_layers, default=1)
    min_text = min(text_layers, default=max_filter + 1)
    # Do not alter existing subtitle track. If there is no integer gap, share the
    # subtitle layer but insert the AI track before the text track in track order.
    return max_filter + 1 if max_filter + 1 < min_text else min_text


def append_ai_track_from_plan(data: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    for key in [
        "videos",
        "speeds",
        "placeholder_infos",
        "canvases",
        "material_animations",
        "sound_channel_mappings",
        "material_colors",
        "vocal_separations",
    ]:
        data["materials"].setdefault(key, [])

    text_tracks = [track for track in data.get("tracks", []) if track.get("type") == "text"]
    if not text_tracks:
        raise RuntimeError("当前草稿范围没有字幕 text track")
    subtitle_track = max(text_tracks, key=lambda track: len(track.get("segments", [])))
    subtitle_track_index = data.get("tracks", []).index(subtitle_track)
    ai_track_render_index = choose_ai_track_layer(data)
    ai_track = {"id": guid(), "type": "video", "flag": 2, "segments": [], "name": AI_TRACK_NAME}

    for rank, row in enumerate(rows, start=1):
        material_id = guid()
        segment_id = guid()
        refs = {
            "speed": guid(),
            "placeholder": guid(),
            "canvas": guid(),
            "animation": guid(),
            "sound": guid(),
            "color": guid(),
            "vocal": guid(),
        }
        width, height = png_size(row["image_path"])
        data["materials"]["videos"].append(
            {
                "id": material_id,
                "type": "photo",
                "duration": 10_800_000_000,
                "path": str(row["image_path"]).replace("\\", "/"),
                "has_audio": False,
                "width": width,
                "height": height,
                "material_id": hashlib.md5(str(row["image_path"]).encode("utf-8")).hexdigest(),
                "material_name": row["image_path"].name,
                "crop": {},
                "stable": {"time_range": {}},
                "matting": {"path": ""},
                "check_flag": 62978047,
                "video_algorithm": {"path": "", "story_video_modify_video_config": {}},
                "is_unified_beauty_mode": True,
                "is_set_beauty_mode": True,
                "beauty_face_auto_preset": {},
                "video_mask_stroke": {"resource_id": "", "path": "", "type": ""},
                "video_mask_shadow": {"resource_id": "", "path": ""},
            }
        )
        for key, values in helper_materials(refs).items():
            data["materials"][key].extend(values)
        ai_track["segments"].append(
            {
                "id": segment_id,
                "source_timerange": {"duration": PHOTO_DURATION_US},
                "target_timerange": {"start": row["start_us"], "duration": PHOTO_DURATION_US},
                "render_timerange": {},
                "clip": {"scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": 0.0}, "flip": {}},
                "uniform_scale": {},
                "material_id": material_id,
                "extra_material_refs": list(refs.values()),
                "render_index": 12000 + rank,
                "enable_hsl": False,
                "track_render_index": ai_track_render_index,
                "hdr_settings": {"mode": 1},
                "responsive_layout": {},
                "enable_adjust_mask": False,
                "source": "segmentsourcenormal",
            }
        )
        row["draft_material_id"] = material_id
        row["draft_segment_id"] = segment_id

    data["tracks"].insert(subtitle_track_index, ai_track)


def inspect_ai_broll(data: dict[str, Any]) -> dict[str, Any]:
    videos = {material["id"]: material for material in data["materials"].get("videos", [])}
    tracks = [track for track in data.get("tracks", []) if track.get("name") == AI_TRACK_NAME]
    rows = []
    for track in tracks:
        for segment in track.get("segments", []):
            material = videos.get(segment.get("material_id"), {})
            timerange = segment.get("target_timerange") or {}
            rows.append(
                {
                    "image_id": image_id_from_filename(Path(str(material.get("material_name") or ""))),
                    "material_name": material.get("material_name") or "",
                    "start_us": int(timerange.get("start") or 0),
                    "duration_us": int(timerange.get("duration") or 0),
                    "track_id": track.get("id"),
                    "track_name": track.get("name"),
                    "track_render_index": segment.get("track_render_index"),
                }
            )
    return {
        "track_count": len(tracks),
        "track_id": tracks[0].get("id") if tracks else "",
        "track_name": tracks[0].get("name") if tracks else "",
        "segments": sorted(rows, key=lambda row: (row["start_us"], row["image_id"])),
    }


def write_verify_csv(path: Path, plan_rows: list[dict[str, Any]], actual_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {row["image_id"]: row for row in actual_rows}
    failures = []
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        fields = [
            "image_id",
            "expected_start_us",
            "actual_start_us",
            "start_delta_us",
            "expected_duration_us",
            "actual_duration_us",
            "status",
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in sorted(plan_rows, key=lambda r: image_id_sort_key(r["image_id"])):
            actual = by_id.get(row["image_id"])
            status = "ok"
            actual_start = ""
            actual_duration = ""
            delta = ""
            if not actual:
                status = "missing"
            else:
                actual_start = actual["start_us"]
                actual_duration = actual["duration_us"]
                delta = int(actual_start) - int(row["start_us"])
                if delta != 0 or int(actual_duration) != PHOTO_DURATION_US:
                    status = "failed"
            if status != "ok":
                failures.append(row["image_id"])
            writer.writerow(
                {
                    "image_id": row["image_id"],
                    "expected_start_us": row["start_us"],
                    "actual_start_us": actual_start,
                    "start_delta_us": delta,
                    "expected_duration_us": PHOTO_DURATION_US,
                    "actual_duration_us": actual_duration,
                    "status": status,
                }
            )
    return {"failure_ids": failures, "failure_count": len(failures)}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Write final AI B-roll plan into one Jianying timeline.")
    parser.add_argument("--draft-dir", type=Path, required=True)
    parser.add_argument("--timeline-name", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    args = parser.parse_args()

    run_dir = args.runtime / f"final_write_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    timeline_id, timeline_name = resolve_timeline_id(args.draft_dir, args.timeline_name)
    timeline_dir = args.draft_dir / "Timelines" / timeline_id
    encrypted_path = timeline_dir / "draft_content.json"
    timeline_template_path = timeline_dir / "template-2.tmp"
    root_encrypted_path = args.draft_dir / "draft_content.json"
    root_template_path = args.draft_dir / "template-2.tmp"
    plain = run_dir / "draft_content.before.dec.json"
    modified = run_dir / "draft_content.after.dec.json"
    encrypted_out = run_dir / "draft_content.after.encrypted.json"

    plan_rows, skip_ids = load_plan(args.plan)
    if len(plan_rows) != 78:
        raise RuntimeError(f"计划 write 数量不是 78：{len(plan_rows)}")
    if skip_ids != ["01", "02"]:
        raise RuntimeError(f"skip 编号不是 01/02：{skip_ids}")

    assert_layout_has_no_duplicate_timeline_ids(args.draft_dir)
    assert_all_project_timeline_files_match_folder_ids(args.draft_dir, args.jy_draftc, run_dir)
    write_root_mirror = root_mirrors_timeline_id(args.draft_dir, args.jy_draftc, run_dir, timeline_id)

    # Capture timeline01 hash for the final no-touch assertion.
    layout = read_json(args.draft_dir / "timeline_layout.json")
    timeline1_id = ""
    for dock in layout.get("dockItems", []):
        for tid, name in zip(dock.get("timelineIds", []), dock.get("timelineNames", [])):
            if name in {"时间线1", "时间线01"}:
                timeline1_id = tid
                break
        if timeline1_id:
            break
    timeline1_path = args.draft_dir / "Timelines" / timeline1_id / "draft_content.json" if timeline1_id else None
    timeline1_before = sha256(timeline1_path) if timeline1_path and timeline1_path.exists() else ""

    decrypt(args.jy_draftc, encrypted_path, plain)
    data = read_json(plain)
    assert_timeline_content_id(data, timeline_id, encrypted_path)
    removed_ai = remove_existing_ai_broll(data)
    append_ai_track_from_plan(data, plan_rows)
    write_json(modified, data)
    encrypt(args.jy_draftc, modified, encrypted_out)
    encrypted_text = encrypted_out.read_text("utf-8")
    encrypted_path.write_text(encrypted_text, "utf-8")
    timeline_template_path.write_text(encrypted_text, "utf-8")
    if write_root_mirror:
        root_encrypted_path.write_text(encrypted_text, "utf-8")
        root_template_path.write_text(encrypted_text, "utf-8")
    update_key_value(args.draft_dir, plan_rows, removed_ai)
    assert_all_project_timeline_files_match_folder_ids(args.draft_dir, args.jy_draftc, run_dir)

    verify_plain = run_dir / "draft_content.verify.dec.json"
    decrypt(args.jy_draftc, encrypted_path, verify_plain)
    verify_data = read_json(verify_plain)
    ai_info = inspect_ai_broll(verify_data)
    verify_csv = run_dir / "write_verify.csv"
    verify = write_verify_csv(verify_csv, plan_rows, ai_info["segments"])

    timeline1_after = sha256(timeline1_path) if timeline1_path and timeline1_path.exists() else ""
    log_path = run_dir / "final_write_log.json"
    confirmation_path = run_dir / "final_write_confirmation.json"
    summary = {
        "success": verify["failure_count"] == 0 and len(ai_info["segments"]) == 78,
        "draft_dir": str(args.draft_dir),
        "timeline_name": timeline_name,
        "timeline_id": timeline_id,
        "timeline1_id": timeline1_id,
        "timeline1_untouched": bool(timeline1_before and timeline1_before == timeline1_after),
        "root_mirror_written": write_root_mirror,
        "written_count": len(ai_info["segments"]),
        "failed_count": verify["failure_count"],
        "failed_ids": verify["failure_ids"],
        "skip_count": len(skip_ids),
        "skip_ids": skip_ids,
        "ai_track_name": ai_info["track_name"],
        "ai_track_id": ai_info["track_id"],
        "ai_track_segment_count": len(ai_info["segments"]),
        "all_duration_1p3s": all(row["duration_us"] == PHOTO_DURATION_US for row in ai_info["segments"]),
        "all_starts_match_plan": verify["failure_count"] == 0,
        "log_path": str(log_path),
        "confirmation_path": str(confirmation_path),
        "verify_path": str(verify_csv),
    }
    log_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    confirmation_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
