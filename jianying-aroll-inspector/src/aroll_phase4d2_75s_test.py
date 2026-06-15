from __future__ import annotations

import argparse
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aroll_cleanup_runtime import fmt_size, run_cleanup
from aroll_contract_check import timeline_id_checks_after
from aroll_decision_merger import decision_maps, merge_decisions
from aroll_display_subtitle_planner import (
    build_display_subtitle_plan,
    kept_words_for_row,
    write_json,
)
from aroll_inspect import (
    DEFAULT_RUNTIME,
    build_report as inspect_build_report,
    inspect_audio_tracks,
    inspect_filter_tracks,
    inspect_video_tracks,
    subtitle_timeline,
    total_target_duration,
)
from aroll_intra_segment_breath_cutter import (
    apply_breath_cuts_to_edl,
    build_breath_cut_plan,
    rebase_subtitle_plan,
)
from aroll_pause_tightening_pass import apply_tightening_to_edl, build_pause_tightening_candidates
from aroll_phase4c2_corrected_word_poc import post_merge_repeat_check, restore_original_backup, run_post_inspect
from aroll_phase4c3_sentence_gap_poc import material_text_rows
from aroll_phase4d_long_segment_test import (
    filter_breath_plan_for_min_pieces,
    range_subtitle_indices,
    regression_report,
    write_decision_merge_report,
)
from aroll_poc_writer import backup_draft_files, get_track, split_video_segments_for_edl, write_encrypted_to_targets
from aroll_postwrite_audio_audit import audit_postwrite_audio
from aroll_safe_gap_cutter import SafeGapCutter
from aroll_sentence_gap_compressor import build_group_level_edl, build_sentence_gap_report
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
)


DEFAULT_DRAFT_DIR = Path(r"D:\JianyingPro Drafts\6月14日")
DEFAULT_BACKUP_DIR = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_roughcut_write_20260614_111435\backup")
DEFAULT_V5_DIR = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_corrective_v5_20260614_163617")
DEFAULT_REPEAT_CLUSTERS = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4_diagnostics_20260614_171206\repeat_clusters.json")
DEFAULT_WORD_TIMELINE = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4_diagnostics_20260614_171206\word_timeline.json")
SOURCE_START_US = 0
SOURCE_END_US = 75_000_000
MIN_VIDEO_PIECE_US = 240_000


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


def selected_rows_for_range(
    subtitles: list[dict[str, Any]],
    drops: dict[int, dict[str, Any]],
    micros: dict[int, dict[str, Any]],
    source_start_us: int,
    source_end_us: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in subtitles:
        idx = int(row["subtitle_index"])
        start = int(row["start_us"])
        end = int(row["end_us"])
        if start < source_start_us or end > source_end_us:
            continue
        if idx in drops:
            continue
        text = str(row.get("subtitle_text") or "")
        reason = "normal"
        if idx in micros:
            text = str(micros[idx].get("kept_text") or text)
            reason = "micro_cleanup"
        rows.append(
            {
                "subtitle_uid": row["subtitle_uid"],
                "subtitle_index": idx,
                "source_text": row.get("subtitle_text") or "",
                "text": text,
                "source_start_us": start,
                "source_end_us": end,
                "reason": reason,
                "text_segment_id": row.get("text_segment_id"),
                "text_material_id": row.get("text_material_id"),
            }
        )
    return rows


def build_video_speech_units(selected_rows: list[dict[str, Any]], word_timeline: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    units: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for idx, row in enumerate(selected_rows, start=1):
        words = kept_words_for_row(row, word_timeline)
        if not words:
            diagnostics.append({"subtitle_index": row.get("subtitle_index"), "status": "no_words", "row": row})
            continue
        source_start = min(int(word["start_us"]) for word in words)
        source_end = max(int(word["end_us"]) for word in words)
        unit = {
            "fragment_id": f"vunit_{idx:04d}",
            "text": row["text"],
            "source_subtitle_indices": [int(row["subtitle_index"])],
            "source_subtitle_uids": [row["subtitle_uid"]],
            "speech_start_us": source_start,
            "speech_end_us": source_end,
            "word_count": len(words),
            "adjustment": None,
            "row_reason": row.get("reason"),
            "word_ids": [word.get("word_id") for word in words],
        }
        units.append(unit)
        diagnostics.append(
            {
                "subtitle_index": row.get("subtitle_index"),
                "source_text": row.get("source_text"),
                "kept_text": row.get("text"),
                "row_reason": row.get("reason"),
                "word_ids": unit["word_ids"],
                "speech_start_us": source_start,
                "speech_end_us": source_end,
            }
        )
    units.sort(key=lambda row: int(row["speech_start_us"]))
    return units, diagnostics


def source_range_report(
    subtitles: list[dict[str, Any]],
    selected_rows: list[dict[str, Any]],
    drops: dict[int, dict[str, Any]],
    micros: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    selected_indices = range_subtitle_indices(subtitles, SOURCE_START_US, SOURCE_END_US)
    actual_start = min(int(row["source_start_us"]) for row in selected_rows)
    actual_end = max(int(row["source_end_us"]) for row in selected_rows)
    return {
        "requested_source_range_s": [0.0, 75.0],
        "actual_source_range_s": [round(actual_start / 1_000_000, 3), round(actual_end / 1_000_000, 3)],
        "source_duration_s": round((actual_end - actual_start) / 1_000_000, 3),
        "actual_source_start_us": actual_start,
        "actual_source_end_us": actual_end,
        "subtitle_indices_in_requested_range": selected_indices,
        "kept_subtitle_indices": [int(row["subtitle_index"]) for row in selected_rows],
        "dropped_in_range": [idx for idx in selected_indices if idx in drops],
        "micro_cleanup_in_range": [idx for idx in selected_indices if idx in micros],
    }


def write_human_focus(run_dir: Path, report: dict[str, Any], regression: dict[str, Any], readability: dict[str, Any]) -> None:
    lines = [
        "# Phase 4D-2 Human Review Focus",
        "",
        "打开唯一测试草稿：D:\\JianyingPro Drafts\\6月14日",
        "",
        "1. 75 秒段是否没有重复句回归",
        "2. 字幕是否不再顶成长条",
        "3. 是否还有过长字幕",
        "4. 是否有单字/碎字幕",
        "5. 是否切字 / 断尾音",
        "6. 停顿是否接近 4C-5 的紧度",
        "7. 「你嘲笑嘉豪」「人家年少时候」「你跪在地上叫大佬」「肆意的踩踏」是否自然",
        "",
        "## Summary",
        f"- source_range_s: {report.get('source_range_s')}",
        f"- final_duration_s: {report.get('final_duration_s')}",
        f"- removed_duration_s: {report.get('removed_duration_s')}",
        f"- video_segments: {report.get('video_segments')}",
        f"- subtitle_segments: {report.get('subtitle_segments')}",
        "",
        "## Subtitle readability",
        f"- max_chars: {readability.get('max_chars')}",
        f"- avg_chars: {readability.get('avg_chars')}",
        f"- max_duration_s: {readability.get('max_duration_s')}",
        f"- overlong_subtitle_count: {readability.get('overlong_subtitle_count')}",
        f"- single_char_subtitle_count: {readability.get('single_char_subtitle_count')}",
        "",
        "## Regression",
    ]
    for key, row in (regression.get("checks") or {}).items():
        lines.append(f"- {key}: {row.get('status')}")
    (run_dir / "human_review_focus.md").write_text("\n".join(lines) + "\n", "utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4D-2 repaired 75s A-Roll test.")
    parser.add_argument("--draft-dir", type=Path, default=DEFAULT_DRAFT_DIR)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--v5-dir", type=Path, default=DEFAULT_V5_DIR)
    parser.add_argument("--repeat-clusters", type=Path, default=DEFAULT_REPEAT_CLUSTERS)
    parser.add_argument("--word-timeline", type=Path, default=DEFAULT_WORD_TIMELINE)
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--target-keep-pause-us", type=int, default=20_000)
    args = parser.parse_args()

    run_dir = args.runtime / f"aroll_phase4d2_75s_test_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    cleanup_plan, cleanup_report = run_cleanup(run_dir)

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

    merged, merge_report, merge_summary = merge_decisions(subtitles, args.v5_dir, args.repeat_clusters)
    write_json(run_dir / "merged_aroll_decisions.json", merged)
    drops, micros = decision_maps(merged)
    selected_rows = selected_rows_for_range(subtitles, drops, micros, SOURCE_START_US, SOURCE_END_US)
    if not selected_rows:
        raise RuntimeError("NO_SELECTED_ROWS_FOR_PHASE4D2")
    sr_report = source_range_report(subtitles, selected_rows, drops, micros)
    write_json(run_dir / "source_range_report.json", sr_report)
    write_decision_merge_report(run_dir / "phase4d2_decision_merge_report.md", merge_report, selected_rows)
    write_json(
        run_dir / "semantic_guard_report.json",
        {
            "semantic_guard_blocks_total": len(merged.get("semantic_guard_blocks") or []),
            "semantic_guard_blocks_in_range": [
                row for row in (merged.get("semantic_guard_blocks") or [])
                if int(row.get("subtitle_index") or 0) in sr_report["subtitle_indices_in_requested_range"]
            ],
        },
    )

    repeat_check = post_merge_repeat_check([
        {
            "fragment_text": row["text"],
            "source_start_us": row["source_start_us"],
            "source_end_us": row["source_end_us"],
        }
        for row in selected_rows
    ])
    if not repeat_check["pass"]:
        raise RuntimeError(f"POST_DECISION_REPEAT_CHECK_FAILED:{repeat_check['residuals']}")

    word_timeline = read_json(args.word_timeline)
    video_units, video_unit_diag = build_video_speech_units(selected_rows, word_timeline)
    write_json(run_dir / "phase4d2_video_speech_units.json", video_units)
    write_json(run_dir / "phase4d2_video_speech_unit_diagnostics.json", video_unit_diag)

    material_path = str(((selected_main.get("materials") or [{}])[0]).get("material_path") or "")
    cutter = SafeGapCutter(material_path, run_dir / "audio_vad")
    gap_report, gap_review = build_sentence_gap_report(video_units, cutter.silences)
    write_json(run_dir / "phase4d2_gap_cut_report.json", gap_report)
    (run_dir / "phase4d2_gap_cut_report.md").write_text(gap_review, "utf-8")
    sentence_edl, sentence_subtitles = build_group_level_edl(video_units)

    audio_audit, audio_md = audit_postwrite_audio(sentence_edl, sentence_subtitles, word_timeline, cutter)
    write_json(run_dir / "phase4d2_audio_pause_audit.json", audio_audit)
    (run_dir / "phase4d2_audio_pause_audit.md").write_text(audio_md, "utf-8")
    raw_breath_plan = build_breath_cut_plan(audio_audit)
    write_json(run_dir / "intra_segment_breath_cut_plan.raw.json", raw_breath_plan)
    breath_plan = filter_breath_plan_for_min_pieces(raw_breath_plan, sentence_edl, MIN_VIDEO_PIECE_US)
    write_json(run_dir / "intra_segment_breath_cut_plan.json", breath_plan)
    breath_edl = apply_breath_cuts_to_edl(sentence_edl, breath_plan)
    breath_subtitles = rebase_subtitle_plan(sentence_subtitles, breath_edl)

    post_breath_audit, post_breath_md = audit_postwrite_audio(breath_edl, breath_subtitles, word_timeline, cutter)
    write_json(run_dir / "post_breath_audio_pause_audit.json", post_breath_audit)
    (run_dir / "post_breath_audio_pause_audit.md").write_text(post_breath_md, "utf-8")
    tightening_report = build_pause_tightening_candidates(post_breath_audit, breath_plan, args.target_keep_pause_us)
    final_edl, apply_report = apply_tightening_to_edl(breath_edl, tightening_report)
    tightening_report["apply_report"] = apply_report
    tightening_report["actual_cut_count"] = apply_report["applied_count"]
    tightening_report["estimated_removed_pause_us"] = apply_report["actual_removed_us"]
    tightening_report["estimated_removed_pause_s"] = round(apply_report["actual_removed_us"] / 1_000_000, 3)
    write_json(run_dir / "pause_tightening_candidates.json", tightening_report)
    write_json(run_dir / "phase4d2_video_edl_75s.json", final_edl)

    display_plan, readability = build_display_subtitle_plan(selected_rows, word_timeline, final_edl)
    write_json(run_dir / "phase4d2_display_subtitle_plan_75s.json", display_plan)
    write_json(run_dir / "phase4d2_subtitle_readability_report.json", readability)
    if int(readability.get("overlong_subtitle_count") or 0) > 0 or int(readability.get("single_char_subtitle_count") or 0) > 0:
        raise RuntimeError(f"DISPLAY_SUBTITLE_READABILITY_BLOCKED:{readability}")

    regression = regression_report(subtitles, display_plan, SOURCE_START_US, SOURCE_END_US)
    write_json(run_dir / "phase4d2_regression_report.json", regression)
    failed = [key for key, row in (regression.get("checks") or {}).items() if row.get("status") == "failed"]
    if failed:
        raise RuntimeError(f"REGRESSION_BLOCKED:{failed}")

    backup_paths = backup_draft_files(args.draft_dir, timeline_id, run_dir, root_mirror_required)
    main_track = get_track(data, str(selected_main["track_id"]))
    text_track = get_track(data, str(selected_text_track["track_id"]))
    old_video_segments = deepcopy(main_track.get("segments") or [])
    new_video_segments, video_split_rows = split_video_segments_for_edl(old_video_segments, final_edl)
    new_text_segments, text_rows = material_text_rows(data, text_track, subtitles, display_plan)
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

    source_duration_us = int(sr_report["actual_source_end_us"]) - int(sr_report["actual_source_start_us"])
    final_duration_us = int(data["duration"])
    write_report = {
        "draft_dir": str(args.draft_dir),
        "runtime_dir": str(run_dir),
        "cleanup": {
            "deleted": cleanup_report["deleted"],
            "released_size": cleanup_report["released_size"],
            "released_size_human": fmt_size(int(cleanup_report["released_size"])),
            "preserved_runtime_dirs": cleanup_report["preserved_runtime_dirs"],
        },
        "restored_paths": restored,
        "backup_paths": backup_paths,
        "source_range_s": sr_report["actual_source_range_s"],
        "source_duration_s": round(source_duration_us / 1_000_000, 3),
        "final_duration_us": final_duration_us,
        "final_duration_s": round(final_duration_us / 1_000_000, 3),
        "removed_duration_s": round((source_duration_us - final_duration_us) / 1_000_000, 3),
        "video_segments": len(new_video_segments),
        "subtitle_segments": len(new_text_segments),
        "drop_decision_count": len(sr_report["dropped_in_range"]),
        "micro_cleanup_count": len(sr_report["micro_cleanup_in_range"]),
        "sentence_gap_cut_count": gap_report.get("sentence_gap_cut_count"),
        "postwrite_pause_cut_count": breath_plan.get("breath_cut_count"),
        "tightening_cut_count": tightening_report.get("actual_cut_count"),
        "sentence_gap_removed_s": gap_report.get("total_sentence_gap_removed_s"),
        "postwrite_pause_removed_s": breath_plan.get("estimated_removed_pause_s"),
        "tightening_removed_s": tightening_report.get("estimated_removed_pause_s"),
        "total_pause_removed_s": round(
            float(gap_report.get("total_sentence_gap_removed_s") or 0)
            + float(breath_plan.get("estimated_removed_pause_s") or 0)
            + float(tightening_report.get("estimated_removed_pause_s") or 0),
            3,
        ),
        "readability": readability,
        "target_writes": {str(path): str(path) in target_writes for path in targets},
        "timeline_id_checks_after": timeline_checks,
        "root_mirror_required": root_mirror_required,
        "root_mirror_matches_after": root_mirrors_timeline_id(args.draft_dir, args.jy_draftc, run_dir, timeline_id),
        "merge_summary": merge_summary,
        "repeat_regression_summary": {key: row.get("status") for key, row in regression["checks"].items()},
        "risk_report": {
            "used_display_subtitle_plan_to_drive_video_edl": False,
            "split_video_edl_and_display_subtitle_plan": True,
            "medium_high_risk_cut_executed": any(row.get("risk") in {"medium", "high"} for row in apply_report.get("applied") or []),
            "deepseek_called": False,
        },
        "fatal_reasons": sorted(set(check_fatals)),
        "warnings": sorted(set(video_warnings + (post_inspect.get("warnings") or []))),
        "project_json_modified": False,
        "timeline_layout_modified": False,
        "audio_filter_tracks_modified": False,
        "deepseek_called": False,
        "extra_draft_dirs_created": False,
        "video_split_rows": video_split_rows,
        "subtitle_rows": text_rows,
    }
    write_json(run_dir / "write_report.json", write_report)
    write_human_focus(run_dir, write_report, regression, readability)

    print("status=ok")
    print(f"runtime={run_dir}")
    print(f"report={run_dir / 'write_report.json'}")
    print(f"source_range_s={write_report['source_range_s']}")
    print(f"final_duration_s={write_report['final_duration_s']}")
    print(f"removed_duration_s={write_report['removed_duration_s']}")
    print(f"video_segments={write_report['video_segments']}")
    print(f"subtitle_segments={write_report['subtitle_segments']}")
    print(f"released_size={write_report['cleanup']['released_size_human']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
