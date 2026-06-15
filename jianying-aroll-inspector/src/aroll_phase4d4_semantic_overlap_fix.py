from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aroll_contract_check import timeline_id_checks_after
from aroll_display_subtitle_planner import readability_report
from aroll_final_residual_repeat_auditor import audit_final_residual_repeats, write_json
from aroll_inspect import (
    DEFAULT_RUNTIME,
    build_report as inspect_build_report,
    inspect_audio_tracks,
    inspect_filter_tracks,
    inspect_video_tracks,
    subtitle_timeline,
    total_target_duration,
)
from aroll_llm_semantic_overlap_arbiter import no_call_report
from aroll_phase4c2_corrected_word_poc import restore_original_backup, run_post_inspect
from aroll_phase4c3_sentence_gap_poc import material_text_rows
from aroll_poc_writer import backup_draft_files, get_track, split_video_segments_for_edl, write_encrypted_to_targets
from aroll_semantic_overlap_trimmer import apply_semantic_overlap_trim, semantic_overlap_regression
from aroll_subtitle_interval_guard import apply_subtitle_interval_guard
from aroll_tiny_segment_guard import audit_tiny_segments
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
DEFAULT_PHASE4D3_DIR = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4d3_final_repeat_fix_20260614_222445")
DEFAULT_PHASE4D2_DIR = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4d2_75s_test_20260614_220351")
DEFAULT_WORD_TIMELINE = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4_diagnostics_20260614_171206\word_timeline.json")


def running_jianying_processes() -> list[dict[str, str]]:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-Process | Where-Object {$_.ProcessName -like 'JianyingPro*' -or $_.ProcessName -like 'CapCut*' -or $_.ProcessName -like '*剪映*'} | Select-Object ProcessName,Id | ConvertTo-Json -Compress",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    data = json.loads(completed.stdout)
    if isinstance(data, dict):
        data = [data]
    return [{"ProcessName": str(row.get("ProcessName")), "Id": str(row.get("Id"))} for row in data]


def assert_jianying_closed() -> None:
    running = [row for row in running_jianying_processes() if row["ProcessName"] == "JianyingPro"]
    if running:
        raise RuntimeError(f"JIANying_PROCESS_RUNNING_REFUSE_DRAFT_WRITE:{running}")


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


def require_inputs(phase4d3_dir: Path, phase4d2_dir: Path) -> dict[str, Path]:
    names = {
        "input_phase4d3_write_report": phase4d3_dir / "write_report.json",
        "phase4d3_edl": phase4d3_dir / "selected_video_edl_after_repeat_fix.json",
        "phase4d3_subtitles": phase4d3_dir / "subtitle_plan_after_repeat_fix.json",
        "phase4d3_readability": phase4d3_dir / "subtitle_readability_after_repeat_fix.json",
        "phase4d3_before_audit": phase4d3_dir / "final_residual_repeat_audit_before_fix.json",
        "phase4d3_after_audit": phase4d3_dir / "final_residual_repeat_audit_after_fix.json",
        "phase4d3_fix_plan": phase4d3_dir / "final_repeat_fix_plan.json",
        "phase4d2_edl": phase4d2_dir / "phase4d2_video_edl_75s.json",
        "phase4d2_subtitles": phase4d2_dir / "phase4d2_display_subtitle_plan_75s.json",
    }
    missing = [f"{key}:{path}" for key, path in names.items() if not path.exists()]
    if missing:
        raise RuntimeError(f"PHASE4D4_INPUT_MISSING:{missing}")
    return names


def copy_inputs(run_dir: Path, paths: dict[str, Path]) -> None:
    shutil.copy2(paths["input_phase4d3_write_report"], run_dir / "input_phase4d3_write_report.json")


def write_human_focus(run_dir: Path, report: dict[str, Any], regression: dict[str, Any]) -> None:
    lines = [
        "# Phase 4D-4 Human Review Focus",
        "",
        "打开唯一测试草稿：D:\\JianyingPro Drafts\\6月14日",
        "",
        "1. 「精分的数字游民」是否只删重复 phrase，没有丢掉前面的语义",
        "2. 「是对自己人的规训」是否仍然无重复、无极短跳切",
        "3. 后面那处字幕是否不再飞上去",
        "4. 是否还有字幕重叠/上一轨显示异常",
        "5. 是否有切字 / 断尾音",
        "6. 整体停顿是否仍接近上一版紧度",
        "",
        "## Summary",
        f"- final_duration_s: {report.get('final_duration_s')}",
        f"- video_segments: {report.get('video_segments')}",
        f"- subtitle_segments: {report.get('subtitle_segments')}",
        f"- semantic_overlap_issue_count: {report.get('semantic_overlap_issue_count')}",
        f"- partial_trim_count: {report.get('partial_trim_count')}",
        f"- subtitle_interval_overlap_count: {report.get('subtitle_interval_overlap_count')}",
        "",
        "## Semantic regression",
        f"- detected: {regression.get('detected')}",
        f"- old_action_would_be: {regression.get('old_action_would_be')}",
        f"- new_action: {regression.get('new_action')}",
        f"- preserved_unique_text: {regression.get('preserved_unique_text')}",
        f"- dropped_duplicate_text: {regression.get('dropped_duplicate_text')}",
        f"- risk: {regression.get('risk')}",
    ]
    (run_dir / "human_review_focus.md").write_text("\n".join(lines) + "\n", "utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4D-4 semantic overlap and subtitle interval guard.")
    parser.add_argument("--draft-dir", type=Path, default=DEFAULT_DRAFT_DIR)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--phase4d3-dir", type=Path, default=DEFAULT_PHASE4D3_DIR)
    parser.add_argument("--phase4d2-dir", type=Path, default=DEFAULT_PHASE4D2_DIR)
    parser.add_argument("--word-timeline", type=Path, default=DEFAULT_WORD_TIMELINE)
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    args = parser.parse_args()

    run_dir = args.runtime / f"aroll_phase4d4_semantic_overlap_fix_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    assert_jianying_closed()

    paths = require_inputs(args.phase4d3_dir, args.phase4d2_dir)
    copy_inputs(run_dir, paths)
    input_report = read_json(paths["input_phase4d3_write_report"])
    phase4d3_edl = read_json(paths["phase4d3_edl"])
    phase4d3_subtitles = read_json(paths["phase4d3_subtitles"])
    phase4d3_fix_plan = read_json(paths["phase4d3_fix_plan"])
    phase4d3_before_audit = read_json(paths["phase4d3_before_audit"])
    phase4d2_edl = read_json(paths["phase4d2_edl"])
    phase4d2_subtitles = read_json(paths["phase4d2_subtitles"])
    word_timeline = read_json(args.word_timeline)

    sem_edl, sem_subtitles, semantic_report = apply_semantic_overlap_trim(
        phase4d3_edl,
        phase4d3_subtitles,
        phase4d3_fix_plan,
        phase4d3_before_audit,
        phase4d2_edl,
        phase4d2_subtitles,
        word_timeline,
    )
    write_json(run_dir / "semantic_overlap_trim_report.json", semantic_report)
    llm_report = no_call_report()
    write_json(run_dir / "llm_semantic_overlap_arbiter_report.json", llm_report)
    regression = semantic_overlap_regression(semantic_report, sem_subtitles)
    write_json(run_dir / "semantic_overlap_regression_report.json", regression)

    guarded_subtitles, interval_report = apply_subtitle_interval_guard(sem_subtitles)
    write_json(run_dir / "subtitle_interval_guard_report.json", interval_report)
    readability = readability_report(guarded_subtitles)
    readability["subtitle_interval_overlap_count"] = interval_report["overlap_count_after"]
    write_json(run_dir / "subtitle_readability_after_4d4.json", readability)
    after_audit = audit_final_residual_repeats(sem_edl, guarded_subtitles, word_timeline)
    write_json(run_dir / "final_residual_repeat_audit_after_4d4.json", after_audit)
    write_json(run_dir / "selected_video_edl_after_4d4.json", sem_edl)
    write_json(run_dir / "subtitle_plan_after_4d4.json", guarded_subtitles)

    tiny_after = audit_tiny_segments(sem_edl, guarded_subtitles)
    write_json(run_dir / "tiny_segment_guard_after_4d4.json", tiny_after)

    gate_fatals: list[str] = []
    if int(after_audit.get("high_confidence_text_repeat_count") or 0) > 0:
        gate_fatals.append("HIGH_CONFIDENCE_TEXT_REPEAT_REMAINS")
    if int(after_audit.get("high_confidence_hidden_audio_repeat_count") or 0) > 0:
        gate_fatals.append("HIGH_CONFIDENCE_HIDDEN_AUDIO_REPEAT_REMAINS")
    if int(tiny_after.get("unhandled_tiny_artifact_segment_count") or 0) > 0:
        gate_fatals.append("UNHANDLED_TINY_ARTIFACT_SEGMENT_REMAINS")
    if int(tiny_after.get("unauthorized_segment_under_500ms") or 0) > 0:
        gate_fatals.append("UNAUTHORIZED_SEGMENT_UNDER_500MS_REMAINS")
    if int(readability.get("overlong_subtitle_count") or 0) > 0:
        gate_fatals.append("OVERLONG_SUBTITLE_REMAINS")
    if int(readability.get("single_char_subtitle_count") or 0) > 0:
        gate_fatals.append("SINGLE_CHAR_SUBTITLE_REMAINS")
    if int(interval_report.get("overlap_count_after") or 0) > 0:
        gate_fatals.append("SUBTITLE_INTERVAL_OVERLAP_REMAINS")
    if int(interval_report.get("manual_review_overlap_count") or 0) > 0:
        gate_fatals.append("SUBTITLE_INTERVAL_MANUAL_REVIEW_REQUIRED")
    if int(semantic_report.get("manual_review_count") or 0) > 0:
        gate_fatals.append("SEMANTIC_OVERLAP_MANUAL_REVIEW_REQUIRED")
    if gate_fatals:
        write_json(run_dir / "write_report.json", {"status": "blocked", "fatal_reasons": gate_fatals})
        raise RuntimeError(f"FINAL_GATE_BLOCKED:{gate_fatals}")

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
    preflight_fatal: list[str] = []
    preflight_fatal.extend(video_fatals)
    if not selected_main:
        preflight_fatal.append("MAIN_VIDEO_TRACK_NOT_FOUND")
    if not selected_text_track:
        preflight_fatal.append("TEXT_TRACK_NOT_FOUND")
    if audio_tracks or has_independent_audio or has_complex_audio:
        preflight_fatal.append("AUDIO_TRACK_PRESENT_UNSUPPORTED")
        preflight_fatal.extend(audio_fatals)
    if filter_tracks or has_global_filter or has_complex_filter:
        preflight_fatal.append("FILTER_TRACK_PRESENT_UNSUPPORTED")
        preflight_fatal.extend(filter_fatals)
    if not main_speed_safe:
        preflight_fatal.append("MAIN_VIDEO_SPEED_UNSAFE")
    if preflight_fatal:
        raise RuntimeError(f"PREFLIGHT_BLOCKED:{sorted(set(preflight_fatal))}")

    backup_paths = backup_draft_files(args.draft_dir, timeline_id, run_dir, root_mirror_required)
    main_track = get_track(data, str(selected_main["track_id"]))
    text_track = get_track(data, str(selected_text_track["track_id"]))
    old_video_segments = deepcopy(main_track.get("segments") or [])
    new_video_segments, video_split_rows = split_video_segments_for_edl(old_video_segments, sem_edl)
    new_text_segments, text_rows = material_text_rows(data, text_track, subtitles, guarded_subtitles)
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

    final_duration_us = int(data["duration"])
    report = {
        "status": "ok",
        "draft_dir": str(args.draft_dir),
        "runtime_dir": str(run_dir),
        "source_range_s": input_report.get("source_range_s") or [2.367, 73.9],
        "final_duration_us": final_duration_us,
        "final_duration_s": round(final_duration_us / 1_000_000, 3),
        "video_segments": len(new_video_segments),
        "subtitle_segments": len(new_text_segments),
        "semantic_overlap_issue_count": semantic_report["semantic_overlap_issue_count"],
        "full_drop_prevented_count": semantic_report["full_drop_prevented_count"],
        "partial_trim_count": semantic_report["partial_trim_count"],
        "manual_review_count": semantic_report["manual_review_count"],
        "llm_arbitration_count": llm_report["call_count"],
        "subtitle_interval_overlap_count": interval_report["overlap_count_after"],
        "interval_guard": interval_report,
        "subtitle_readability": readability,
        "final_repeat_audit": after_audit,
        "target_writes": target_writes,
        "root_mirror_required": root_mirror_required,
        "root_mirror_matches_after": root_mirrors_timeline_id(args.draft_dir, args.jy_draftc, run_dir, timeline_id),
        "timeline_id_checks_after": timeline_checks,
        "fatal_reasons": sorted(set(check_fatals)),
        "warnings": sorted(set(video_warnings + (post_inspect.get("warnings") or []))),
        "restored_paths": restored,
        "backup_paths": backup_paths,
        "hardcoded_feedback_sentences_as_logic": False,
        "deepseek_called": False,
        "deepseek_call_count": 0,
        "api_key_leaked": False,
        "project_json_modified": False,
        "timeline_layout_modified": False,
        "audio_filter_tracks_modified": False,
        "extra_draft_dirs_created": False,
        "semantic_overlap_regression": regression,
        "video_split_rows": video_split_rows,
        "subtitle_rows": text_rows,
    }
    write_json(run_dir / "write_report.json", report)
    write_human_focus(run_dir, report, regression)

    print("status=ok")
    print(f"runtime={run_dir}")
    print(f"report={run_dir / 'write_report.json'}")
    print(f"semantic_overlap_issue_count={report['semantic_overlap_issue_count']}")
    print(f"partial_trim_count={report['partial_trim_count']}")
    print(f"subtitle_interval_overlap_count={report['subtitle_interval_overlap_count']}")
    print(f"final_duration_s={report['final_duration_s']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
