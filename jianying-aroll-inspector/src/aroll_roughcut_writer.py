from __future__ import annotations

import argparse
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from aroll_contract_check import timeline_id_checks_after
from aroll_inspect import (
    DEFAULT_RUNTIME,
    inspect_audio_tracks,
    inspect_filter_tracks,
    inspect_video_tracks,
    segment_start,
    subtitle_timeline,
    total_target_duration,
)
from aroll_poc_writer import (
    backup_draft_files,
    get_track,
    rewrite_text_segments_for_edl,
    split_video_segments_for_edl,
    write_encrypted_to_targets,
)
from jy_bridge import (
    DEFAULT_JY_DRAFTC,
    assert_all_project_timeline_files_match_folder_ids,
    assert_layout_has_no_duplicate_timeline_ids,
    assert_timeline_content_id,
    decrypt,
    encrypt,
    read_json,
    resolve_timeline_id,
    root_mirrors_timeline_id,
    write_json,
)


LEAD_GUARD_US = 200_000
TAIL_GUARD_US = 300_000
MERGE_GAP_US = 350_000
NORMAL_PAUSE_AFTER_US = 60_000
PARAGRAPH_PAUSE_AFTER_US = 180_000
DRAMATIC_PAUSE_AFTER_US = 350_000
PARAGRAPH_GAP_US = 700_000
DRAMATIC_GAP_US = 1_500_000
MAX_CLIP_DURATION_US = 12_000_000


def pause_for_gap(gap_us: int) -> int:
    if gap_us < PARAGRAPH_GAP_US:
        return NORMAL_PAUSE_AFTER_US
    if gap_us <= DRAMATIC_GAP_US:
        return PARAGRAPH_PAUSE_AFTER_US
    return DRAMATIC_PAUSE_AFTER_US


def subtitle_region(row: dict[str, Any], main_total_duration_us: int) -> dict[str, Any]:
    start_us = int(row["start_us"])
    end_us = int(row["end_us"])
    return {
        "subtitle_start_uid": row["subtitle_uid"],
        "subtitle_end_uid": row["subtitle_uid"],
        "subtitle_start_us": start_us,
        "subtitle_end_us": end_us,
        "cut_start_us": max(0, start_us - LEAD_GUARD_US),
        "cut_end_us": min(main_total_duration_us, end_us + TAIL_GUARD_US),
        "source_subtitle_count": 1,
        "subtitle_texts": [row["subtitle_text"]],
    }


def merge_regions(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for region in regions:
        if not merged:
            merged.append(deepcopy(region))
            continue
        current = merged[-1]
        if int(region["cut_start_us"]) <= int(current["cut_end_us"]) + MERGE_GAP_US:
            current["subtitle_end_uid"] = region["subtitle_end_uid"]
            current["subtitle_end_us"] = region["subtitle_end_us"]
            current["cut_end_us"] = max(int(current["cut_end_us"]), int(region["cut_end_us"]))
            current["source_subtitle_count"] = int(current["source_subtitle_count"]) + int(region["source_subtitle_count"])
            current["subtitle_texts"].extend(region.get("subtitle_texts") or [])
        else:
            merged.append(deepcopy(region))
    return merged


def build_roughcut_edl(subtitles: list[dict[str, Any]], main_total_duration_us: int) -> list[dict[str, Any]]:
    speech_rows = [
        row for row in sorted(subtitles, key=lambda item: int(item["start_us"]))
        if str(row.get("subtitle_text") or "").strip()
    ]
    if not speech_rows:
        raise RuntimeError("SUBTITLE_TIMELINE_HAS_NO_SPEECH_ROWS")
    regions = [subtitle_region(row, main_total_duration_us) for row in speech_rows]
    merged = merge_regions(regions)

    edl: list[dict[str, Any]] = []
    target_start_us = 0
    for index, region in enumerate(merged, start=1):
        next_region = merged[index] if index < len(merged) else None
        gap_to_next = int(next_region["cut_start_us"]) - int(region["cut_end_us"]) if next_region else 0
        pause_after_us = pause_for_gap(gap_to_next) if next_region else 0
        target_duration_us = int(region["cut_end_us"]) - int(region["cut_start_us"])
        if target_duration_us <= 0:
            continue
        edl.append(
            {
                "clip_id": f"rough_{index:03d}",
                "subtitle_start_uid": region["subtitle_start_uid"],
                "subtitle_end_uid": region["subtitle_end_uid"],
                "subtitle_start_us": int(region["subtitle_start_us"]),
                "subtitle_end_us": int(region["subtitle_end_us"]),
                "cut_start_us": int(region["cut_start_us"]),
                "cut_end_us": int(region["cut_end_us"]),
                "target_start_us": target_start_us,
                "target_duration_us": target_duration_us,
                "pause_after_us": pause_after_us,
                "source_subtitle_count": int(region["source_subtitle_count"]),
                "boundary_mode": "subtitle_regions_merged_with_guard",
                "subtitle_texts": region.get("subtitle_texts") or [],
            }
        )
        target_start_us += target_duration_us + pause_after_us
    if not edl:
        raise RuntimeError("ROUGH_CUT_EDL_EMPTY")
    return edl


def summarize_edl(edl: list[dict[str, Any]], subtitle_count: int, source_duration_us: int) -> dict[str, Any]:
    durations = [int(row["target_duration_us"]) for row in edl]
    output_duration_us = max(int(row["target_start_us"]) + int(row["target_duration_us"]) for row in edl)
    return {
        "clip_count": len(edl),
        "covered_subtitle_count": sum(int(row["source_subtitle_count"]) for row in edl),
        "source_subtitle_count": subtitle_count,
        "source_duration_us": source_duration_us,
        "output_duration_us": output_duration_us,
        "longest_clip_duration_us": max(durations) if durations else 0,
        "shortest_clip_duration_us": min(durations) if durations else 0,
        "max_clip_duration_us": MAX_CLIP_DURATION_US,
        "clips_over_max_duration": [
            row["clip_id"] for row in edl if int(row["target_duration_us"]) > MAX_CLIP_DURATION_US
        ],
    }


def run_roughcut(args: argparse.Namespace) -> tuple[Path, Path]:
    run_dir = args.runtime / f"aroll_roughcut_write_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    timeline_id, timeline_name = resolve_timeline_id(args.draft_dir, args.timeline_name)
    timeline_dir = args.draft_dir / "Timelines" / timeline_id
    encrypted_path = timeline_dir / "draft_content.json"
    plain_before = run_dir / "draft_content.before.dec.json"
    plain_modified = run_dir / "draft_content.modified.dec.json"
    encrypted_out = run_dir / "draft_content.modified.enc.json"
    plain_after = run_dir / "draft_content.after.dec.json"
    subtitle_before_path = run_dir / "subtitle_timeline.before.json"
    edl_path = run_dir / "roughcut_edl.json"
    report_path = run_dir / "aroll_roughcut_write_report.json"

    decrypt(args.jy_draftc, encrypted_path, plain_before)
    data = read_json(plain_before)
    assert_timeline_content_id(data, timeline_id, encrypted_path)
    assert_layout_has_no_duplicate_timeline_ids(args.draft_dir)
    assert_all_project_timeline_files_match_folder_ids(args.draft_dir, args.jy_draftc, run_dir)

    root_mirror_required = False
    if (args.draft_dir / "draft_content.json").exists():
        root_mirror_required = root_mirrors_timeline_id(args.draft_dir, args.jy_draftc, run_dir, timeline_id)

    video_candidates, selected_main, video_fatals, video_warnings, main_speed_safe = inspect_video_tracks(data)
    subtitles, text_tracks, selected_text_track = subtitle_timeline(data)
    write_json(subtitle_before_path, subtitles)
    audio_tracks, has_independent_audio, has_complex_audio, audio_fatals = inspect_audio_tracks(data)
    main_total_duration_us = int((selected_main or {}).get("total_target_duration_us") or 0)
    filter_tracks, has_global_filter, has_complex_filter, filter_fatals = inspect_filter_tracks(data, main_total_duration_us)

    fatal_reasons: list[str] = []
    warnings: list[str] = []
    fatal_reasons.extend(video_fatals)
    warnings.extend(video_warnings)
    if not selected_main:
        fatal_reasons.append("MAIN_VIDEO_TRACK_NOT_FOUND")
    if not selected_text_track:
        fatal_reasons.append("TEXT_TRACK_NOT_FOUND")
    if len([row for row in text_tracks if row.get("selected_as_subtitle_track")]) != 1:
        fatal_reasons.append("TEXT_TRACK_NOT_UNIQUE")
    if has_independent_audio or audio_tracks:
        fatal_reasons.append("AUDIO_TRACK_PRESENT_UNSUPPORTED_FOR_ROUGHCUT")
    if has_complex_audio:
        fatal_reasons.extend(f"AUDIO:{reason}" for reason in audio_fatals)
    if has_global_filter or has_complex_filter or filter_tracks:
        fatal_reasons.append("FILTER_TRACK_PRESENT_UNSUPPORTED_FOR_ROUGHCUT")
        fatal_reasons.extend(f"FILTER:{reason}" for reason in filter_fatals)
    if not main_speed_safe:
        fatal_reasons.append("MAIN_VIDEO_SPEED_UNSAFE")
    if len(subtitles) == 0:
        fatal_reasons.append("SUBTITLE_TIMELINE_EMPTY")
    if fatal_reasons:
        report = {
            "draft_dir": str(args.draft_dir),
            "timeline_id": timeline_id,
            "timeline_name": timeline_name,
            "runtime_dir": str(run_dir),
            "fatal_reasons": sorted(set(fatal_reasons)),
            "warnings": sorted(set(warnings)),
        }
        write_json(report_path, report)
        raise RuntimeError(f"ROUGHCUT_PREFLIGHT_BLOCKED:{report['fatal_reasons']}; report={report_path}")

    backup_paths = backup_draft_files(args.draft_dir, timeline_id, run_dir, root_mirror_required)
    edl = build_roughcut_edl(subtitles, main_total_duration_us)
    write_json(edl_path, edl)

    main_track = get_track(data, str(selected_main["track_id"]))
    text_track = get_track(data, str(selected_text_track["track_id"]))
    if main_track is None:
        raise RuntimeError("SELECTED_MAIN_TRACK_NOT_FOUND_IN_DATA")
    if text_track is None:
        raise RuntimeError("SELECTED_TEXT_TRACK_NOT_FOUND_IN_DATA")

    old_video_segments = deepcopy(main_track.get("segments") or [])
    old_text_segments = deepcopy(text_track.get("segments") or [])
    new_video_segments, video_split_rows = split_video_segments_for_edl(old_video_segments, edl)
    new_text_segments, kept_subtitle_rows = rewrite_text_segments_for_edl(old_text_segments, subtitles, edl)
    if not new_video_segments:
        raise RuntimeError("ROUGHCUT_REWRITE_PRODUCED_NO_VIDEO_SEGMENTS")
    if not new_text_segments:
        raise RuntimeError("ROUGHCUT_REWRITE_PRODUCED_NO_TEXT_SEGMENTS")

    before_video = {
        "track_index": selected_main["track_index"],
        "track_id": selected_main["track_id"],
        "segment_count": len(old_video_segments),
        "total_duration_us": total_target_duration(old_video_segments),
    }
    before_text = {
        "track_index": selected_text_track["track_index"],
        "track_id": selected_text_track["track_id"],
        "segment_count": len(old_text_segments),
    }

    main_track["segments"] = new_video_segments
    text_track["segments"] = new_text_segments
    new_total_duration_us = total_target_duration(new_video_segments)
    data["duration"] = new_total_duration_us

    write_json(plain_modified, data)
    encrypt(args.jy_draftc, plain_modified, encrypted_out)

    targets = [
        timeline_dir / "draft_content.json",
        timeline_dir / "template-2.tmp",
    ]
    if root_mirror_required:
        targets.extend([args.draft_dir / "draft_content.json", args.draft_dir / "template-2.tmp"])
    target_writes = write_encrypted_to_targets(encrypted_out, targets)

    decrypt(args.jy_draftc, encrypted_path, plain_after)
    verify_data = read_json(plain_after)
    timeline_checks, check_fatals = timeline_id_checks_after(
        draft_dir=args.draft_dir,
        jy_draftc=args.jy_draftc,
        run_dir=run_dir,
        plain_path=plain_after,
        encrypted_path=encrypted_path,
        timeline_id=timeline_id,
    )
    root_mirror_after = False
    if root_mirror_required:
        root_mirror_after = root_mirrors_timeline_id(args.draft_dir, args.jy_draftc, run_dir, timeline_id)

    verify_video_track = get_track(verify_data, str(selected_main["track_id"])) or {}
    verify_text_track = get_track(verify_data, str(selected_text_track["track_id"])) or {}
    after_video = {
        "track_index": selected_main["track_index"],
        "track_id": selected_main["track_id"],
        "segment_count": len(verify_video_track.get("segments") or []),
        "total_duration_us": total_target_duration(verify_video_track.get("segments") or []),
    }
    after_text = {
        "track_index": selected_text_track["track_index"],
        "track_id": selected_text_track["track_id"],
        "segment_count": len(verify_text_track.get("segments") or []),
    }

    report = {
        "draft_dir": str(args.draft_dir),
        "timeline_id": timeline_id,
        "timeline_name": timeline_name,
        "runtime_dir": str(run_dir),
        "backup_paths": backup_paths,
        "subtitle_timeline_before_path": str(subtitle_before_path),
        "roughcut_edl_path": str(edl_path),
        "draft_content_before_dec_path": str(plain_before),
        "draft_content_after_dec_path": str(plain_after),
        "wrote_timeline_draft_content": str(timeline_dir / "draft_content.json") in target_writes,
        "wrote_timeline_template_2_tmp": str(timeline_dir / "template-2.tmp") in target_writes,
        "wrote_root_draft_content": str(args.draft_dir / "draft_content.json") in target_writes,
        "wrote_root_template_2_tmp": str(args.draft_dir / "template-2.tmp") in target_writes,
        "video_track_before": before_video,
        "video_track_after": after_video,
        "text_track_before": before_text,
        "text_track_after": after_text,
        "edl_summary": summarize_edl(edl, len(subtitles), before_video["total_duration_us"]),
        "video_split_count": len(video_split_rows),
        "video_split_rows": video_split_rows,
        "kept_subtitle_count": len(kept_subtitle_rows),
        "timeline_id_checks_after": timeline_checks,
        "root_mirror_required": root_mirror_required,
        "root_mirror_matches_after": root_mirror_after if root_mirror_required else None,
        "timeline_layout_modified": False,
        "fatal_reasons": sorted(set(check_fatals)),
        "warnings": sorted(set(warnings)),
    }
    write_json(report_path, report)
    return run_dir, report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a rule-based rough-cut A-Roll PoC into a sacrificial Jianying draft.")
    parser.add_argument("--draft-dir", type=Path, required=True)
    parser.add_argument("--timeline-name", default="")
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    args = parser.parse_args()

    run_dir, report_path = run_roughcut(args)
    report = read_json(report_path)
    summary = report.get("edl_summary") or {}
    print("status=ok" if not report.get("fatal_reasons") else "status=blocked")
    print(f"runtime={run_dir}")
    print(f"report={report_path}")
    print(f"roughcut_edl={report.get('roughcut_edl_path')}")
    print(f"roughcut_clips={summary.get('clip_count')}")
    print(f"covered_subtitles={summary.get('covered_subtitle_count')}")
    print(f"video_segments={report['video_track_before']['segment_count']}->{report['video_track_after']['segment_count']}")
    print(f"text_segments={report['text_track_before']['segment_count']}->{report['text_track_after']['segment_count']}")
    print(f"duration_us={report['video_track_before']['total_duration_us']}->{report['video_track_after']['total_duration_us']}")
    if report.get("fatal_reasons"):
        print("fatal_reasons=" + ",".join(report["fatal_reasons"]))
    if report.get("warnings"):
        print("warnings=" + ",".join(report["warnings"]))
    return 0 if not report.get("fatal_reasons") else 2


if __name__ == "__main__":
    raise SystemExit(main())
