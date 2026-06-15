from __future__ import annotations

import argparse
import json
import shutil
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aroll_contract_check import timeline_id_checks_after
from aroll_hidden_audio_repeat_diagnostics import diagnose_hidden_repeat
from aroll_inspect import (
    DEFAULT_RUNTIME,
    build_report as inspect_build_report,
    inspect_audio_tracks,
    inspect_filter_tracks,
    inspect_video_tracks,
    subtitle_timeline,
    total_target_duration,
)
from aroll_phase4c2_corrected_word_poc import (
    clone_text_material,
    restore_original_backup,
    run_post_inspect,
)
from aroll_poc_writer import backup_draft_files, get_track, split_video_segments_for_edl, write_encrypted_to_targets
from aroll_safe_gap_cutter import SafeGapCutter
from aroll_sentence_gap_compressor import (
    build_group_bounds,
    build_group_level_edl,
    build_sentence_gap_report,
    write_json,
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
)


DEFAULT_DRAFT_DIR = Path(r"D:\JianyingPro Drafts\6月14日")
DEFAULT_BACKUP_DIR = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_roughcut_write_20260614_111435\backup")
DEFAULT_PREVIOUS_DIR = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4c2_corrected_word_poc_20260614_180716")
DEFAULT_WORD_TIMELINE = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4_diagnostics_20260614_171206\word_timeline.json")


def run_inspect_summary(draft_dir: Path, run_dir: Path, jy_draftc: Path) -> dict[str, Any]:
    args = SimpleNamespace(
        draft_dir=draft_dir,
        timeline_name="",
        main_video_track_index=-1,
        main_material_path="",
        jy_draftc=jy_draftc,
        runtime=run_dir / "inspect_runtime",
    )
    inspect_dir, report_path, subtitle_path = inspect_build_report(args)
    report = read_json(report_path)
    selected_main = report.get("selected_main_video_track") or {}
    selected_text = next((row for row in report.get("text_tracks") or [] if row.get("selected_as_subtitle_track")), {})
    return {
        "inspect_output_dir": str(inspect_dir),
        "inspect_report_path": str(report_path),
        "subtitle_timeline_path": str(subtitle_path),
        "timeline_id": report.get("timeline_id"),
        "timeline_id_checks": report.get("timeline_id_checks"),
        "root_mirror": report.get("root_mirror"),
        "video_segment_count": selected_main.get("segment_count"),
        "subtitle_segment_count": selected_text.get("segment_count"),
        "duration_us": selected_main.get("total_target_duration_us"),
        "fatal_reasons": report.get("fatal_reasons") or [],
        "warnings": report.get("warnings") or [],
    }


def require_previous_inputs(previous_dir: Path) -> dict[str, Path]:
    names = {
        "input_previous_write_report": "write_report.json",
        "previous_edl": "selected_word_edl_corrected.json",
        "previous_subtitles": "selected_subtitle_plan_corrected.json",
        "grouped_subtitle_plan": "grouped_subtitle_plan.json",
        "merged_decisions": "merged_aroll_decisions.json",
        "safe_gap_plan": "safe_gap_cut_plan.json",
    }
    paths: dict[str, Path] = {}
    missing: list[str] = []
    for key, name in names.items():
        path = previous_dir / name
        if not path.exists():
            matches = list(previous_dir.rglob(name))
            path = matches[0] if matches else path
        if not path.exists():
            missing.append(f"{key}:{name}")
        paths[key] = path
    if missing:
        raise RuntimeError(f"PHASE4C2_INPUT_MISSING:{missing}")
    return paths


def copy_previous_inputs(run_dir: Path, paths: dict[str, Path]) -> None:
    shutil.copy2(paths["input_previous_write_report"], run_dir / "input_previous_write_report.json")


def material_text_rows(
    data: dict[str, Any],
    text_track: dict[str, Any],
    original_subtitles: list[dict[str, Any]],
    subtitle_plan: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    materials = (data.get("materials") or {}).setdefault("texts", [])
    material_by_id = {str(item.get("id") or ""): item for item in materials}
    sub_by_uid = {str(row["subtitle_uid"]): row for row in original_subtitles}
    new_segments: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for group in subtitle_plan:
        source_uids = [str(uid) for uid in (group.get("source_subtitle_uids") or [])]
        if not source_uids:
            continue
        source_row = sub_by_uid.get(source_uids[0])
        if not source_row:
            continue
        source_segment = source_row.get("segment") or {}
        source_material = material_by_id.get(str(source_row.get("text_material_id") or ""))
        if not source_segment or not source_material:
            continue
        new_segment = deepcopy(source_segment)
        new_segment["id"] = guid()
        target_timerange = deepcopy(new_segment.get("target_timerange") or {})
        target_timerange["start"] = int(group["target_start_us"])
        target_timerange["duration"] = int(group["target_duration_us"])
        new_segment["target_timerange"] = target_timerange
        cloned_material = clone_text_material(source_material, str(group["fragment_text"]))
        materials.append(cloned_material)
        new_segment["material_id"] = cloned_material["id"]
        new_segments.append(new_segment)
        rows.append(
            {
                "fragment_id": group.get("fragment_id"),
                "text": group.get("fragment_text"),
                "target_start_us": group.get("target_start_us"),
                "target_duration_us": group.get("target_duration_us"),
                "source_start_us": group.get("source_start_us"),
                "source_end_us": group.get("source_end_us"),
            }
        )
    new_segments.sort(key=lambda row: int((row.get("target_timerange") or {}).get("start") or 0))
    return new_segments, rows


def write_human_focus(
    run_dir: Path,
    sentence_report: dict[str, Any],
    hidden_report: dict[str, Any],
    subtitle_plan: list[dict[str, Any]],
) -> None:
    lines = [
        "# Phase 4C-3 Human Review Focus",
        "",
        "1. 句子和句子之间的大停顿是否至少少了三分之二",
        "2. 有没有新的切字 / 断尾音",
        "3. 「评论区 评论区」音频重复是否还在",
        "4. 字幕是否仍然正常，不碎不乱",
        "5. 「你可以嘲笑他们虚伪」是否仍自然",
        "6. 是否有跳切感",
        "",
        "## Sentence gap summary",
        f"- candidate_count: {sentence_report.get('sentence_gap_candidate_count')}",
        f"- cut_count: {sentence_report.get('sentence_gap_cut_count')}",
        f"- removed_s: {sentence_report.get('total_sentence_gap_removed_s')}",
        "",
        "## Hidden repeat summary",
        f"- word_timeline_occurrences: {hidden_report.get('word_timeline_occurrences')}",
        f"- recommended_action: {hidden_report.get('recommended_action')}",
        f"- confidence: {hidden_report.get('confidence')}",
        "",
        "## Final subtitles",
    ]
    for row in subtitle_plan:
        lines.append(f"- {row.get('fragment_text')}")
    (run_dir / "human_review_focus.md").write_text("\n".join(lines) + "\n", "utf-8")


def write_sentence_review(run_dir: Path, review_text: str) -> None:
    (run_dir / "sentence_gap_compression_review.md").write_text(review_text, "utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4C-3 sentence gap compression and hidden repeat PoC.")
    parser.add_argument("--draft-dir", type=Path, default=DEFAULT_DRAFT_DIR)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--previous-dir", type=Path, default=DEFAULT_PREVIOUS_DIR)
    parser.add_argument("--word-timeline", type=Path, default=DEFAULT_WORD_TIMELINE)
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    args = parser.parse_args()

    run_dir = args.runtime / f"aroll_phase4c3_sentence_gap_poc_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    paths = require_previous_inputs(args.previous_dir)
    copy_previous_inputs(run_dir, paths)

    timeline_id, _timeline_name = resolve_timeline_id(args.draft_dir, "")
    restored = restore_original_backup(args.draft_dir, timeline_id, args.backup_dir)
    restore_inspect = run_post_inspect(args.draft_dir, run_dir / "restore_check", args.jy_draftc)
    if int(restore_inspect.get("duration_us") or 0) < 300_000_000:
        raise RuntimeError(f"RESTORE_DURATION_UNSAFE:{restore_inspect}")
    if int(restore_inspect.get("subtitle_segment_count") or 0) != 115:
        raise RuntimeError(f"RESTORE_SUBTITLE_COUNT_UNSAFE:{restore_inspect}")

    timeline_dir = args.draft_dir / "Timelines" / timeline_id
    encrypted_path = timeline_dir / "draft_content.json"
    plain_before = run_dir / "draft_content.before.dec.json"
    plain_modified = run_dir / "draft_content.modified.dec.json"
    encrypted_out = run_dir / "draft_content.modified.enc.json"
    plain_after = run_dir / "draft_content.after.dec.json"

    decrypt(args.jy_draftc, encrypted_path, plain_before)
    data = read_json(plain_before)
    assert_timeline_content_id(data, timeline_id, encrypted_path)
    assert_layout_has_no_duplicate_timeline_ids(args.draft_dir)
    assert_all_project_timeline_files_match_folder_ids(args.draft_dir, args.jy_draftc, run_dir)
    root_mirror_required = root_mirrors_timeline_id(args.draft_dir, args.jy_draftc, run_dir, timeline_id)

    video_candidates, selected_main, video_fatals, video_warnings, main_speed_safe = inspect_video_tracks(data)
    subtitles, text_tracks, selected_text_track = subtitle_timeline(data)
    main_total = int((selected_main or {}).get("total_target_duration_us") or 0)
    audio_tracks, has_independent_audio, has_complex_audio, audio_fatals = inspect_audio_tracks(data)
    filter_tracks, has_global_filter, has_complex_filter, filter_fatals = inspect_filter_tracks(data, main_total)
    fatal = []
    fatal.extend(video_fatals)
    if not selected_main:
        fatal.append("MAIN_VIDEO_TRACK_NOT_FOUND")
    if not selected_text_track:
        fatal.append("TEXT_TRACK_NOT_FOUND")
    if audio_tracks or has_independent_audio or has_complex_audio:
        fatal.append("AUDIO_TRACK_PRESENT_UNSUPPORTED")
        fatal.extend(audio_fatals)
    if filter_tracks or has_global_filter or has_complex_filter:
        fatal.append("FILTER_TRACK_PRESENT_UNSUPPORTED")
        fatal.extend(filter_fatals)
    if not main_speed_safe:
        fatal.append("MAIN_VIDEO_SPEED_UNSAFE")
    if fatal:
        raise RuntimeError(f"PREFLIGHT_BLOCKED:{sorted(set(fatal))}")

    previous_report = read_json(paths["input_previous_write_report"])
    previous_duration_us = int(previous_report.get("final_duration_us") or 0)
    grouped = read_json(paths["grouped_subtitle_plan"])
    word_timeline = read_json(args.word_timeline)
    material_path = str(((selected_main.get("materials") or [{}])[0]).get("material_path") or "")
    cutter = SafeGapCutter(material_path, run_dir / "audio_vad")

    hidden_report, hidden_context = diagnose_hidden_repeat(grouped, word_timeline, cutter)
    (run_dir / "hidden_audio_repeat_context.md").write_text(hidden_context, "utf-8")
    write_json(run_dir / "hidden_audio_repeat_diagnostics.json", hidden_report)

    group_bounds = build_group_bounds(grouped, word_timeline, hidden_report)
    sentence_report, sentence_review = build_sentence_gap_report(group_bounds, cutter.silences)
    write_json(run_dir / "sentence_gap_compression_report.json", sentence_report)
    write_sentence_review(run_dir, sentence_review)

    clips, subtitle_plan = build_group_level_edl(group_bounds)
    write_json(run_dir / "selected_word_edl_phase4c3.json", clips)
    write_json(run_dir / "selected_subtitle_plan_phase4c3.json", subtitle_plan)

    backup_paths = backup_draft_files(args.draft_dir, timeline_id, run_dir, root_mirror_required)
    main_track = get_track(data, str(selected_main["track_id"]))
    text_track = get_track(data, str(selected_text_track["track_id"]))
    old_video_segments = deepcopy(main_track.get("segments") or [])
    old_text_segments = deepcopy(text_track.get("segments") or [])
    new_video_segments, video_split_rows = split_video_segments_for_edl(old_video_segments, clips)
    new_text_segments, text_rows = material_text_rows(data, text_track, subtitles, subtitle_plan)

    main_track["segments"] = new_video_segments
    text_track["segments"] = new_text_segments
    data["duration"] = total_target_duration(new_video_segments)
    write_json(plain_modified, data)
    encrypt(args.jy_draftc, plain_modified, encrypted_out)
    targets = [timeline_dir / "draft_content.json", timeline_dir / "template-2.tmp"]
    if root_mirror_required:
        targets.extend([args.draft_dir / "draft_content.json", args.draft_dir / "template-2.tmp"])
    target_writes = write_encrypted_to_targets(encrypted_out, targets)
    decrypt(args.jy_draftc, encrypted_path, plain_after)

    timeline_checks, check_fatals = timeline_id_checks_after(args.draft_dir, args.jy_draftc, run_dir, plain_after, encrypted_path, timeline_id)
    post_inspect = run_inspect_summary(args.draft_dir, run_dir, args.jy_draftc)
    write_json(run_dir / "post_inspect_summary.json", post_inspect)
    write_human_focus(run_dir, sentence_report, hidden_report, subtitle_plan)

    write_report = {
        "draft_dir": str(args.draft_dir),
        "runtime_dir": str(run_dir),
        "restored_paths": restored,
        "backup_paths": backup_paths,
        "source_range_s": previous_report.get("source_range_s") or [113.447, 150.797],
        "previous_duration_us": previous_duration_us,
        "final_duration_us": data["duration"],
        "previous_duration_s": round(previous_duration_us / 1_000_000, 3),
        "new_duration_s": round(int(data["duration"]) / 1_000_000, 3),
        "video_segments": len(new_video_segments),
        "subtitle_segments": len(new_text_segments),
        "video_split_rows": video_split_rows,
        "subtitle_rows": text_rows,
        "target_writes": {str(path): str(path) in target_writes for path in targets},
        "timeline_id_checks_after": timeline_checks,
        "root_mirror_required": root_mirror_required,
        "root_mirror_matches_after": root_mirrors_timeline_id(args.draft_dir, args.jy_draftc, run_dir, timeline_id),
        "sentence_gap_summary": {
            key: sentence_report.get(key)
            for key in [
                "sentence_gap_candidate_count",
                "sentence_gap_cut_count",
                "total_sentence_gap_removed_s",
                "average_gap_before_ms",
                "average_gap_after_ms",
            ]
        },
        "hidden_audio_repeat_summary": {
            "word_timeline_occurrences": hidden_report.get("word_timeline_occurrences"),
            "asr_collapsed_audio_repeat": hidden_report.get("asr_collapsed_audio_repeat"),
            "speech_islands_count": len(hidden_report.get("speech_islands") or []),
            "hidden_repeat_candidates_count": len(hidden_report.get("hidden_repeat_candidates") or []),
            "recommended_action": hidden_report.get("recommended_action"),
            "confidence": hidden_report.get("confidence"),
            "actual_audio_island_removed": hidden_report.get("recommended_action") == "remove_first_audio_island",
        },
        "fatal_reasons": sorted(set(check_fatals)),
        "warnings": sorted(set(video_warnings + (post_inspect.get("warnings") or []))),
        "project_json_modified": False,
        "timeline_layout_modified": False,
        "audio_filter_tracks_modified": False,
        "deepseek_called": False,
        "extra_draft_dirs_created": False,
    }
    write_json(run_dir / "write_report.json", write_report)
    print("status=ok")
    print(f"runtime={run_dir}")
    print(f"report={run_dir / 'write_report.json'}")
    print(f"previous_duration_s={write_report['previous_duration_s']}")
    print(f"new_duration_s={write_report['new_duration_s']}")
    print(f"video_segments={len(new_video_segments)}")
    print(f"subtitle_segments={len(new_text_segments)}")
    print(f"sentence_gap_removed_s={write_report['sentence_gap_summary']['total_sentence_gap_removed_s']}")
    print(f"hidden_repeat_action={write_report['hidden_audio_repeat_summary']['recommended_action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
