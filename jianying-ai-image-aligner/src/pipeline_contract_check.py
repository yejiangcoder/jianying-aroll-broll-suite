from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path
from typing import Any

from direct_draft_broll_writer import (
    AI_TRACK_NAME,
    DEFAULT_JY_DRAFTC,
    DEFAULT_RUNTIME,
    MIN_MATCH_CONFIDENCE,
    PHOTO_DURATION_US,
    active_timeline_id,
    broll_static_list_ids,
    broll_table_ai_ids,
    decrypt,
    image_id_from_filename,
    image_id_sort_key,
    map_items,
    normalized_image_files,
    parse_broll_items,
    read_json,
    subtitle_rows,
)


def normalized_image_ids(image_dir: Path) -> list[str]:
    return list(normalized_image_files(image_dir).keys())


def inspect_written_ai(data: dict[str, Any], image_dir: Path) -> dict[str, Any]:
    image_root = str(image_dir).replace("\\", "/")
    videos = {m["id"]: m for m in data["materials"].get("videos", [])}
    ai_tracks = []
    ai_segments = []
    ai_segment_rows = []
    filter_layers = []
    text_layers = []
    text_track_summaries = []
    for index, track in enumerate(data.get("tracks", [])):
        layers = sorted(
            set(
                seg.get("track_render_index")
                for seg in track.get("segments", [])
                if seg.get("track_render_index") is not None
            )
        )
        if track.get("type") == "filter":
            filter_layers.extend(layers)
        if track.get("type") == "text":
            text_layers.extend(layers)
            text_track_summaries.append(
                {
                    "track_index": index,
                    "name": track.get("name"),
                    "count": len(track.get("segments", [])),
                    "track_render_layers": layers,
                }
            )
        rows = []
        for segment in track.get("segments", []):
            material = videos.get(segment.get("material_id"))
            if not material:
                continue
            name = material.get("material_name") or ""
            path = str(material.get("path") or "").replace("\\", "/")
            if track.get("name") == AI_TRACK_NAME or image_root in path:
                rows.append((segment, material))
                timerange = segment.get("target_timerange") or {}
                ai_segment_rows.append(
                    {
                        "image_id": image_id_from_filename(Path(name)),
                        "material_name": name,
                        "path": material.get("path"),
                        "track_index": index,
                        "track_name": track.get("name"),
                        "track_type": track.get("type"),
                        "track_render_index": segment.get("track_render_index"),
                        "start_us": int(timerange.get("start") or 0),
                        "duration_us": int(timerange.get("duration") or 0),
                    }
                )
        if rows:
            ai_tracks.append(
                {
                    "track_index": index,
                    "name": track.get("name"),
                    "type": track.get("type"),
                    "flag": track.get("flag"),
                    "count": len(rows),
                    "track_render_layers": sorted(
                        set(seg.get("track_render_index") for seg, _ in rows)
                    ),
                }
            )
            ai_segments.extend(rows)

    missing_paths = []
    durations = sorted(set(seg["target_timerange"]["duration"] for seg, _ in ai_segments))
    ordered = sorted(ai_segments, key=lambda row: row[0]["target_timerange"]["start"])
    overlaps = []
    for (left_seg, left_mat), (right_seg, right_mat) in zip(ordered, ordered[1:]):
        left_end = left_seg["target_timerange"]["start"] + left_seg["target_timerange"]["duration"]
        if left_end > right_seg["target_timerange"]["start"]:
            overlaps.append((left_mat.get("material_name"), right_mat.get("material_name")))
    for _, material in ai_segments:
        if not Path(str(material.get("path") or "").replace("/", "\\")).exists():
            missing_paths.append(material.get("material_name") or material.get("path"))

    main_text_track = max(text_track_summaries, key=lambda row: row["count"], default=None)
    return {
        "ai_track_count": len(ai_tracks),
        "ai_tracks": ai_tracks,
        "ai_segment_count": len(ai_segments),
        "ai_segment_rows": sorted(ai_segment_rows, key=lambda row: (row["start_us"], row["image_id"])),
        "durations_us": durations,
        "missing_paths": missing_paths,
        "overlaps": overlaps,
        "filter_layers": sorted(set(filter_layers)),
        "text_layers": sorted(set(text_layers)),
        "text_tracks": text_track_summaries,
        "main_text_track": main_text_track,
    }


def write_exec_preview(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "image_id",
        "image_path",
        "start_sec",
        "duration_sec",
        "subtitle_index",
        "subtitle_text",
        "target_text",
        "match_method",
        "confidence",
        "nudged_us",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: image_id_sort_key(r["image_id"])):
            writer.writerow({field: row.get(field, "") for field in fields})


def main() -> int:
    parser = argparse.ArgumentParser(description="Check B-roll design, AI images, and direct draft alignment contract.")
    parser.add_argument("--draft-dir", type=Path, required=True)
    parser.add_argument("--broll", type=Path, required=True)
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    args = parser.parse_args()

    out_dir = args.runtime / f"pipeline_check_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    timeline_id = active_timeline_id(args.draft_dir)
    encrypted = args.draft_dir / "Timelines" / timeline_id / "draft_content.json"
    plain = out_dir / "draft_content.dec.json"
    decrypt(args.jy_draftc, encrypted, plain)
    data = read_json(plain)

    items = parse_broll_items(args.broll, args.image_dir)
    image_ids = normalized_image_ids(args.image_dir)
    subtitles = subtitle_rows(data)
    mapped = map_items(items, subtitles)
    written = inspect_written_ai(data, args.image_dir)
    written_by_id = {
        row["image_id"]: row
        for row in written["ai_segment_rows"]
        if re.fullmatch(r"\d{2}", str(row.get("image_id") or ""))
    }
    precision_rows = []
    for row in mapped:
        actual = written_by_id.get(row["image_id"])
        if not actual:
            precision_rows.append(
                {
                    "image_id": row["image_id"],
                    "status": "missing",
                    "expected_start_us": row["start_us"],
                    "actual_start_us": None,
                    "delta_us": None,
                    "expected_duration_us": PHOTO_DURATION_US,
                    "actual_duration_us": None,
                    "track_render_index": None,
                }
            )
            continue
        delta = int(actual["start_us"]) - int(row["start_us"])
        precision_rows.append(
            {
                "image_id": row["image_id"],
                "status": "ok" if delta == 0 and int(actual["duration_us"]) == PHOTO_DURATION_US else "failed",
                "expected_start_us": row["start_us"],
                "actual_start_us": actual["start_us"],
                "delta_us": delta,
                "expected_duration_us": PHOTO_DURATION_US,
                "actual_duration_us": actual["duration_us"],
                "track_render_index": actual["track_render_index"],
            }
        )
    precision_errors = [row for row in precision_rows if row["status"] != "ok"]
    max_abs_start_delta_us = max((abs(int(row["delta_us"] or 0)) for row in precision_rows), default=0)

    table_ids = broll_table_ai_ids(args.broll)
    static_list_ids = broll_static_list_ids(args.broll)
    parsed_ids = [item["image_id"] for item in items]

    report: dict[str, Any] = {
        "draft_dir": str(args.draft_dir),
        "timeline_id": timeline_id,
        "broll": str(args.broll),
        "image_dir": str(args.image_dir),
        "broll_table_ai_rows": len(table_ids),
        "broll_table_ai_ids": table_ids,
        "broll_static_list_ids": static_list_ids,
        "broll_parsed_ai_items": len(items),
        "broll_parsed_ids": parsed_ids,
        "normalized_ai_image_count": len(image_ids),
        "normalized_ai_image_ids": image_ids,
        "table_ids_missing_images": sorted(set(table_ids) - set(image_ids), key=image_id_sort_key),
        "image_ids_missing_table": sorted(set(image_ids) - set(table_ids), key=image_id_sort_key),
        "static_list_ids_missing_images": sorted(set(static_list_ids) - set(image_ids), key=image_id_sort_key),
        "image_ids_missing_static_list": sorted(set(image_ids) - set(static_list_ids), key=image_id_sort_key),
        "subtitle_count": len(subtitles),
        "mapped_count": len(mapped),
        "low_confidence_ids": [
            row["image_id"] for row in mapped if float(row.get("confidence", 0)) < MIN_MATCH_CONFIDENCE
        ],
        "fallback_rows": [row["image_id"] for row in mapped if "fallback" in row.get("match_method", "")],
        "nudged_rows": [row["image_id"] for row in mapped if int(row.get("nudged_us", 0)) != 0],
        "written_ai": written,
        "precision_check": {
            "status": "ok" if not precision_errors else "failed",
            "max_abs_start_delta_us": max_abs_start_delta_us,
            "rows": precision_rows,
        },
        "duration_expected_us": PHOTO_DURATION_US,
    }
    hard_errors = []
    if not image_ids:
        hard_errors.append("IMAGE_COUNT=0")
    if len(items) != len(image_ids):
        hard_errors.append(f"BROLL_PARSED_COUNT={len(items)} IMAGE_COUNT={len(image_ids)}")
    if table_ids and table_ids != image_ids:
        hard_errors.append("BROLL_TABLE_IDS_NOT_EQUAL_IMAGES")
    if static_list_ids != image_ids:
        hard_errors.append("BROLL_STATIC_LIST_IDS_NOT_EQUAL_IMAGES")
    if parsed_ids != image_ids:
        hard_errors.append("BROLL_PARSED_IDS_NOT_EQUAL_IMAGES")
    if len(mapped) != len(items):
        hard_errors.append(f"MAPPED_COUNT={len(mapped)}")
    if report["low_confidence_ids"]:
        hard_errors.append(
            "LOW_CONFIDENCE_IDS="
            + ",".join(report["low_confidence_ids"])
        )
    if written["ai_segment_count"] not in {0, len(items)}:
        hard_errors.append(f"WRITTEN_AI_COUNT={written['ai_segment_count']}")
    if written["ai_segment_count"]:
        if written["ai_track_count"] != 1:
            hard_errors.append(f"AI_TRACK_COUNT={written['ai_track_count']}")
        if written["durations_us"] != [PHOTO_DURATION_US]:
            hard_errors.append(f"AI_DURATIONS={written['durations_us']}")
        if written["missing_paths"]:
            hard_errors.append("MISSING_PATHS")
        if written["overlaps"]:
            hard_errors.append("OVERLAPS")
        ai_layers = written["ai_tracks"][0]["track_render_layers"] if written["ai_tracks"] else []
        main_text_track = written.get("main_text_track") or {}
        main_text_layers = main_text_track.get("track_render_layers") or []
        if written["filter_layers"] and ai_layers and max(written["filter_layers"]) >= min(ai_layers):
            hard_errors.append("AI_NOT_ABOVE_FILTER")
        if written["text_layers"] and ai_layers and max(ai_layers) >= min(written["text_layers"]):
            hard_errors.append("AI_NOT_BELOW_TEXT")
        if ai_layers and main_text_layers and min(ai_layers) != min(main_text_layers) - 1:
            hard_errors.append("AI_NOT_IMMEDIATE_SUBTITLE_SECOND_ROW")
        if written["ai_tracks"] and main_text_track:
            if written["ai_tracks"][0]["track_index"] != main_text_track["track_index"] - 1:
                hard_errors.append("AI_TRACK_NOT_IMMEDIATELY_BEFORE_SUBTITLE_TRACK")
        if precision_errors:
            hard_errors.append("PRECISION_CHECK_FAILED")

    report["hard_errors"] = hard_errors
    report["status"] = "ok" if not hard_errors else "failed"
    report_path = out_dir / "pipeline_contract_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    write_exec_preview(out_dir / "broll_exec_plan_preview.csv", mapped)

    print(f"status={report['status']}")
    print(f"report={report_path}")
    print(f"broll_items={len(items)} images={len(image_ids)} subtitles={len(subtitles)} mapped={len(mapped)}")
    print(f"written_ai={written['ai_segment_count']} ai_tracks={written['ai_track_count']}")
    if hard_errors:
        print("hard_errors=" + ",".join(hard_errors))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
