from __future__ import annotations

import argparse
import json
import shutil
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from aroll_speed_mapping import (
    display_to_material_delta,
    ensure_clip_time_fields,
    source_timeline_to_material_time,
)
from aroll_contract_check import timeline_id_checks_after
from aroll_inspect import (
    DEFAULT_RUNTIME,
    build_report,
    inspect_audio_tracks,
    inspect_filter_tracks,
    inspect_video_tracks,
    segment_duration,
    segment_end,
    segment_start,
    subtitle_timeline,
    timerange_duration,
    timerange_start,
    total_target_duration,
)
from jy_bridge import (
    DEFAULT_JY_DRAFTC,
    assert_all_project_timeline_files_match_folder_ids,
    assert_layout_has_no_duplicate_timeline_ids,
    assert_timeline_content_id,
    decrypt,
    encrypt,
    guid,
    read_json,
    resolve_timeline_id,
    root_mirrors_timeline_id,
    write_json,
)


TOOL_ROOT = Path(__file__).resolve().parents[1]
LEAD_GUARD_US = 200_000
TAIL_GUARD_US = 300_000
SHORT_PAUSE_US = 40_000
MID_PAUSE_US = 500_000


def copy_if_exists(src: Path, dst: Path, backup_paths: list[str]) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        backup_paths.append(str(dst))


def backup_draft_files(
    draft_dir: Path,
    timeline_id: str,
    run_dir: Path,
    root_mirror_required: bool,
) -> list[str]:
    backup_paths: list[str] = []
    timeline_dir = draft_dir / "Timelines" / timeline_id
    backup_root = run_dir / "backup"
    copy_if_exists(timeline_dir / "draft_content.json", backup_root / "timeline" / "draft_content.json", backup_paths)
    copy_if_exists(timeline_dir / "template-2.tmp", backup_root / "timeline" / "template-2.tmp", backup_paths)
    if root_mirror_required:
        copy_if_exists(draft_dir / "draft_content.json", backup_root / "root" / "draft_content.json", backup_paths)
        copy_if_exists(draft_dir / "template-2.tmp", backup_root / "root" / "template-2.tmp", backup_paths)
    return backup_paths


def uid_number(uid: str) -> int:
    try:
        return int(str(uid).split("_")[-1])
    except Exception:
        return 0


def find_subtitle_by_uid(subtitles: list[dict[str, Any]], uid: str) -> dict[str, Any]:
    if not subtitles:
        raise RuntimeError("SUBTITLE_TIMELINE_EMPTY")
    wanted = uid_number(uid)
    if wanted <= 0:
        return subtitles[0]
    index = min(max(wanted, 1), len(subtitles)) - 1
    return subtitles[index]


def span_from_subtitles(
    clip_id: str,
    subtitles: list[dict[str, Any]],
    start_uid: str,
    end_uid: str,
    target_start_us: int,
    pause_after_us: int,
    main_total_duration_us: int,
) -> dict[str, Any]:
    start_row = find_subtitle_by_uid(subtitles, start_uid)
    end_row = find_subtitle_by_uid(subtitles, end_uid)
    if int(start_row["subtitle_index"]) > int(end_row["subtitle_index"]):
        start_row, end_row = end_row, start_row
    subtitle_start_us = int(start_row["start_us"])
    subtitle_end_us = int(end_row["end_us"])
    cut_start_us = max(0, subtitle_start_us - LEAD_GUARD_US)
    cut_end_us = min(main_total_duration_us, subtitle_end_us + TAIL_GUARD_US)
    target_duration_us = max(0, cut_end_us - cut_start_us)
    if target_duration_us <= 0:
        raise RuntimeError(f"EDL_SPAN_HAS_NON_POSITIVE_DURATION:{clip_id}")
    return {
        "clip_id": clip_id,
        "subtitle_start_uid": start_row["subtitle_uid"],
        "subtitle_end_uid": end_row["subtitle_uid"],
        "subtitle_start_us": subtitle_start_us,
        "subtitle_end_us": subtitle_end_us,
        "lead_guard_us": LEAD_GUARD_US,
        "tail_guard_us": TAIL_GUARD_US,
        "cut_start_us": cut_start_us,
        "cut_end_us": cut_end_us,
        "target_start_us": target_start_us,
        "target_duration_us": target_duration_us,
        "pause_after_us": pause_after_us,
        "boundary_mode": "subtitle_span_with_guard",
        "subtitle_texts": [
            row["subtitle_text"]
            for row in subtitles
            if int(start_row["subtitle_index"]) <= int(row["subtitle_index"]) <= int(end_row["subtitle_index"])
        ],
    }


def build_manual_poc_edl(subtitles: list[dict[str, Any]], main_total_duration_us: int) -> list[dict[str, Any]]:
    if len(subtitles) < 3:
        raise RuntimeError("SUBTITLE_COUNT_TOO_SMALL_FOR_3_SPAN_POC")
    middle_start = max(1, min(len(subtitles) - 2, (len(subtitles) // 2)))
    specs = [
        ("poc_001", "sub_000001", "sub_000003", SHORT_PAUSE_US),
        ("poc_002", f"sub_{middle_start:06d}", f"sub_{middle_start + 2:06d}", MID_PAUSE_US),
        ("poc_003", "sub_000113", "sub_000115", SHORT_PAUSE_US),
    ]
    spans: list[dict[str, Any]] = []
    target_start_us = 0
    for clip_id, start_uid, end_uid, pause_after_us in specs:
        span = span_from_subtitles(
            clip_id=clip_id,
            subtitles=subtitles,
            start_uid=start_uid,
            end_uid=end_uid,
            target_start_us=target_start_us,
            pause_after_us=pause_after_us,
            main_total_duration_us=main_total_duration_us,
        )
        spans.append(span)
        target_start_us = span["target_start_us"] + span["target_duration_us"] + pause_after_us
    return spans


def split_video_segments_for_edl(
    old_segments: list[dict[str, Any]],
    edl: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rewritten: list[dict[str, Any]] = []
    split_rows: list[dict[str, Any]] = []
    for span in edl:
        cut_start = int(span.get("source_timeline_start_us") or span.get("cut_start_us") or span.get("source_start_us") or 0)
        cut_end = int(span.get("source_timeline_end_us") or span.get("cut_end_us") or span.get("source_end_us") or cut_start)
        for old_index, old_segment in enumerate(old_segments):
            old_target_start = segment_start(old_segment)
            old_target_end = segment_end(old_segment)
            overlap_start = max(cut_start, old_target_start)
            overlap_end = min(cut_end, old_target_end)
            if overlap_end <= overlap_start:
                continue
            display_duration = overlap_end - overlap_start
            old_source_start = timerange_start(old_segment.get("source_timerange") or {})
            old_source_duration = timerange_duration(old_segment.get("source_timerange") or {})
            old_target_duration = timerange_duration(old_segment.get("target_timerange") or {})
            speed = float(span.get("speed") or (old_source_duration / old_target_duration if old_target_duration > 0 else 1.0))
            new_source_start = source_timeline_to_material_time(overlap_start, old_target_start, old_source_start, speed)
            new_source_duration = display_to_material_delta(display_duration, speed)
            new_target_start = int(span["target_start_us"]) + (overlap_start - cut_start)

            new_segment = deepcopy(old_segment)
            new_segment["id"] = guid()
            source_timerange = deepcopy(new_segment.get("source_timerange") or {})
            source_timerange["start"] = new_source_start
            source_timerange["duration"] = new_source_duration
            new_segment["source_timerange"] = source_timerange
            target_timerange = deepcopy(new_segment.get("target_timerange") or {})
            target_timerange["start"] = new_target_start
            target_timerange["duration"] = display_duration
            new_segment["target_timerange"] = target_timerange
            rewritten.append(new_segment)
            clip_fields = ensure_clip_time_fields(
                {
                    "clip_id": span["clip_id"],
                    "source_material_id": old_segment.get("material_id"),
                    "source_segment_id": old_segment.get("id"),
                    "source_timeline_start_us": overlap_start,
                    "source_timeline_end_us": overlap_end,
                    "material_start_us": new_source_start,
                    "material_end_us": new_source_start + new_source_duration,
                    "target_start_us": new_target_start,
                    "target_duration_us": display_duration,
                },
                speed,
            )
            split_rows.append(
                {
                    "clip_id": span["clip_id"],
                    "old_segment_index": old_index,
                    "old_segment_id": old_segment.get("id"),
                    "material_id": old_segment.get("material_id"),
                    "speed": speed,
                    "source_timeline_start_us": overlap_start,
                    "source_timeline_end_us": overlap_end,
                    "material_start_us": new_source_start,
                    "material_end_us": new_source_start + new_source_duration,
                    "new_source_start_us": new_source_start,
                    "new_source_duration_us": new_source_duration,
                    "new_target_start_us": new_target_start,
                    "new_duration_us": display_duration,
                    "clip_time_fields": clip_fields,
                }
            )
    rewritten.sort(key=segment_start)
    return rewritten, split_rows


def rewrite_text_segments_for_edl(
    old_text_segments: list[dict[str, Any]],
    subtitles: list[dict[str, Any]],
    edl: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    segment_by_id = {
        str(segment.get("id") or ""): segment
        for segment in old_text_segments
        if segment.get("id")
    }
    rewritten: list[dict[str, Any]] = []
    kept_rows: list[dict[str, Any]] = []
    used_segment_ids: set[str] = set()
    for span in edl:
        start_index = uid_number(span["subtitle_start_uid"])
        end_index = uid_number(span["subtitle_end_uid"])
        for row in subtitles:
            row_index = int(row["subtitle_index"])
            if row_index < start_index or row_index > end_index:
                continue
            source_segment = segment_by_id.get(str(row["text_segment_id"]))
            if not source_segment:
                continue
            new_segment = deepcopy(source_segment)
            old_start = int(row["start_us"])
            new_start = int(span["target_start_us"]) + (old_start - int(span["cut_start_us"]))
            target_timerange = deepcopy(new_segment.get("target_timerange") or {})
            target_timerange["start"] = max(0, new_start)
            new_segment["target_timerange"] = target_timerange
            rewritten.append(new_segment)
            used_segment_ids.add(str(row["text_segment_id"]))
            kept_rows.append(
                {
                    "clip_id": span["clip_id"],
                    "subtitle_uid": row["subtitle_uid"],
                    "text_segment_id": row["text_segment_id"],
                    "old_start_us": old_start,
                    "new_start_us": target_timerange["start"],
                    "duration_us": row["duration_us"],
                    "subtitle_text": row["subtitle_text"],
                }
            )
    rewritten.sort(key=segment_start)
    return rewritten, kept_rows


def get_track(data: dict[str, Any], track_id: str) -> dict[str, Any] | None:
    for track in data.get("tracks") or []:
        if str(track.get("id") or "") == track_id:
            return track
    return None


def write_encrypted_to_targets(encrypted_text_path: Path, targets: list[Path]) -> dict[str, bool]:
    encrypted_text = encrypted_text_path.read_text("utf-8")
    result: dict[str, bool] = {}
    for target in targets:
        target.write_text(encrypted_text, "utf-8")
        result[str(target)] = True
    return result


def run_poc(args: argparse.Namespace) -> tuple[Path, Path]:
    run_dir = args.runtime / f"aroll_poc_write_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    timeline_id, timeline_name = resolve_timeline_id(args.draft_dir, args.timeline_name)
    timeline_dir = args.draft_dir / "Timelines" / timeline_id
    encrypted_path = timeline_dir / "draft_content.json"
    plain_before = run_dir / "draft_content.before.dec.json"
    plain_modified = run_dir / "draft_content.modified.dec.json"
    encrypted_out = run_dir / "draft_content.modified.enc.json"
    verify_after = run_dir / "verify_after_write.dec.json"

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
        fatal_reasons.append("AUDIO_TRACK_PRESENT_UNSUPPORTED_FOR_POC")
    if has_complex_audio:
        fatal_reasons.extend(f"AUDIO:{reason}" for reason in audio_fatals)
    if has_global_filter or has_complex_filter or filter_tracks:
        fatal_reasons.append("FILTER_TRACK_PRESENT_UNSUPPORTED_FOR_POC")
        fatal_reasons.extend(f"FILTER:{reason}" for reason in filter_fatals)
    if not main_speed_safe:
        fatal_reasons.append("MAIN_VIDEO_SPEED_UNSAFE")
    fatal_reasons = sorted(set(fatal_reasons))
    if fatal_reasons:
        report_path = run_dir / "aroll_poc_write_report.json"
        write_json(
            report_path,
            {
                "draft_dir": str(args.draft_dir),
                "timeline_id": timeline_id,
                "timeline_name": timeline_name,
                "fatal_reasons": fatal_reasons,
                "warnings": sorted(set(warnings)),
            },
        )
        raise RuntimeError(f"POC_PREFLIGHT_BLOCKED:{fatal_reasons}; report={report_path}")

    backup_paths = backup_draft_files(args.draft_dir, timeline_id, run_dir, root_mirror_required)

    edl = build_manual_poc_edl(subtitles, main_total_duration_us)
    manual_edl_path = run_dir / "manual_poc_edl.json"
    write_json(manual_edl_path, edl)

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
        raise RuntimeError("POC_REWRITE_PRODUCED_NO_VIDEO_SEGMENTS")
    if not new_text_segments:
        raise RuntimeError("POC_REWRITE_PRODUCED_NO_TEXT_SEGMENTS")

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

    decrypt(args.jy_draftc, encrypted_path, verify_after)
    verify_data = read_json(verify_after)
    timeline_checks, check_fatals = timeline_id_checks_after(
        draft_dir=args.draft_dir,
        jy_draftc=args.jy_draftc,
        run_dir=run_dir,
        plain_path=verify_after,
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
        "manual_poc_edl_path": str(manual_edl_path),
        "wrote_timeline_draft_content": str(timeline_dir / "draft_content.json") in target_writes,
        "wrote_timeline_template_2_tmp": str(timeline_dir / "template-2.tmp") in target_writes,
        "wrote_root_draft_content": str(args.draft_dir / "draft_content.json") in target_writes,
        "wrote_root_template_2_tmp": str(args.draft_dir / "template-2.tmp") in target_writes,
        "video_track_before": before_video,
        "video_track_after": after_video,
        "text_track_before": before_text,
        "text_track_after": after_text,
        "total_duration_before_us": int(data.get("duration") or 0) if False else before_video["total_duration_us"],
        "total_duration_after_us": after_video["total_duration_us"],
        "video_split_rows": video_split_rows,
        "kept_subtitle_rows": kept_subtitle_rows,
        "timeline_id_checks_after": timeline_checks,
        "root_mirror_required": root_mirror_required,
        "root_mirror_matches_after": root_mirror_after if root_mirror_required else None,
        "timeline_layout_modified": False,
        "fatal_reasons": sorted(set(check_fatals)),
        "warnings": sorted(set(warnings)),
    }
    report_path = run_dir / "aroll_poc_write_report.json"
    write_json(report_path, report)
    return run_dir, report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a 3-span A-Roll rewrite PoC into a sacrificial Jianying draft.")
    parser.add_argument("--draft-dir", type=Path, required=True)
    parser.add_argument("--timeline-name", default="")
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    args = parser.parse_args()

    run_dir, report_path = run_poc(args)
    report = read_json(report_path)
    print("status=ok" if not report.get("fatal_reasons") else "status=blocked")
    print(f"runtime={run_dir}")
    print(f"report={report_path}")
    print(f"manual_poc_edl={report.get('manual_poc_edl_path')}")
    print(f"video_segments={report['video_track_before']['segment_count']}->{report['video_track_after']['segment_count']}")
    print(f"text_segments={report['text_track_before']['segment_count']}->{report['text_track_after']['segment_count']}")
    if report.get("fatal_reasons"):
        print("fatal_reasons=" + ",".join(report["fatal_reasons"]))
    if report.get("warnings"):
        print("warnings=" + ",".join(report["warnings"]))
    return 0 if not report.get("fatal_reasons") else 2


if __name__ == "__main__":
    raise SystemExit(main())
