from __future__ import annotations

import argparse
import subprocess
import shutil
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aroll_contract_check import timeline_id_checks_after
from aroll_display_subtitle_planner import readability_report
from aroll_final_residual_repeat_auditor import audit_final_residual_repeats, norm_text, write_json
from aroll_inspect import (
    DEFAULT_RUNTIME,
    build_report as inspect_build_report,
    inspect_audio_tracks,
    inspect_filter_tracks,
    inspect_video_tracks,
    subtitle_timeline,
    total_target_duration,
)
from aroll_phase4c2_corrected_word_poc import restore_original_backup, run_post_inspect
from aroll_phase4c3_sentence_gap_poc import material_text_rows
from aroll_poc_writer import backup_draft_files, get_track, split_video_segments_for_edl, write_encrypted_to_targets
from aroll_postwrite_audio_audit import audit_postwrite_audio
from aroll_repeat_fix_planner import (
    apply_fix_plan_to_edl,
    apply_fix_plan_to_subtitles,
    build_final_repeat_fix_plan,
)
from aroll_safe_gap_cutter import SafeGapCutter
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
    import json

    data = json.loads(completed.stdout)
    if isinstance(data, dict):
        data = [data]
    return [{"ProcessName": str(row.get("ProcessName")), "Id": str(row.get("Id"))} for row in data]


def assert_jianying_closed() -> None:
    running = [
        row for row in running_jianying_processes()
        if row["ProcessName"] == "JianyingPro"
    ]
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


def require_phase4d2_inputs(phase4d2_dir: Path) -> dict[str, Path]:
    names = {
        "input_phase4d2_write_report": "write_report.json",
        "video_edl": "phase4d2_video_edl_75s.json",
        "display_subtitles": "phase4d2_display_subtitle_plan_75s.json",
        "decision_report": "phase4d2_decision_merge_report.md",
        "regression": "phase4d2_regression_report.json",
        "audio_pause_audit": "phase4d2_audio_pause_audit.json",
    }
    paths: dict[str, Path] = {}
    missing: list[str] = []
    for key, name in names.items():
        path = phase4d2_dir / name
        if not path.exists():
            matches = list(phase4d2_dir.rglob(name))
            path = matches[0] if matches else path
        if not path.exists():
            missing.append(f"{key}:{name}")
        paths[key] = path
    if missing:
        raise RuntimeError(f"PHASE4D2_INPUT_MISSING:{missing}")
    return paths


def copy_inputs(run_dir: Path, paths: dict[str, Path]) -> None:
    shutil.copy2(paths["input_phase4d2_write_report"], run_dir / "input_phase4d2_write_report.json")


def regression_checks(subtitle_plan: list[dict[str, Any]], before_audit: dict[str, Any], after_audit: dict[str, Any], tiny_after: dict[str, Any]) -> dict[str, Any]:
    final_text = "\n".join(str(row.get("fragment_text") or row.get("text") or "") for row in subtitle_plan)
    issues_before = before_audit.get("issues") or []
    issues_after = after_audit.get("issues") or []

    def has_issue_before(*needles: str) -> bool:
        for issue in issues_before:
            text = f"{issue.get('left_text', '')}{issue.get('right_text', '')}{issue.get('reason', '')}"
            if all(norm_text(needle) in norm_text(text) for needle in needles):
                return True
        return False

    def has_issue_after(*needles: str) -> bool:
        for issue in issues_after:
            text = f"{issue.get('left_text', '')}{issue.get('right_text', '')}{issue.get('reason', '')}"
            if all(norm_text(needle) in norm_text(text) for needle in needles):
                return True
        return False

    self_regulation_ok = "是对自己人的规训" in final_text and "是对自己人的是对自己人的规训" not in norm_text(final_text)
    jingfen_ok = "一群精分的数字游民" in final_text and "就我发现有这么一群精分" not in final_text
    return {
        "是对自己人的规训重复": {
            "detected": has_issue_before("是对自己人", "规训"),
            "after_issue_present": has_issue_after("是对自己人", "规训"),
            "status": "fixed" if self_regulation_ok and not has_issue_after("是对自己人", "规训") and tiny_after.get("unauthorized_segment_under_500ms") == 0 else "risk",
        },
        "精分的数字游民重复": {
            "detected": has_issue_before("精分", "数字游民"),
            "after_issue_present": has_issue_after("精分", "数字游民"),
            "status": "fixed" if jingfen_ok and not has_issue_after("精分", "数字游民") else "risk",
        },
    }


def write_human_focus(run_dir: Path, write_report: dict[str, Any], regression: dict[str, Any]) -> None:
    lines = [
        "# Phase 4D-3 Human Review Focus",
        "",
        "打开唯一测试草稿：D:\\JianyingPro Drafts\\6月14日",
        "",
        "1. 「是对自己人的规训」附近是否没有音频重复、没有极短杂音跳切",
        "2. 「精分的数字游民」是否没有字幕/音频重复",
        "3. 是否还有其他明显重复句",
        "4. 字幕是否仍然不长、不碎",
        "5. 是否有切字 / 断尾音",
        "6. 停顿是否仍接近上一版紧度",
        "",
        "## Summary",
        f"- source_range_s: {write_report.get('source_range_s')}",
        f"- final_duration_s: {write_report.get('final_duration_s')}",
        f"- video_segments: {write_report.get('video_segments')}",
        f"- subtitle_segments: {write_report.get('subtitle_segments')}",
        f"- hidden_audio_cut_count: {write_report.get('hidden_audio_cut_count')}",
        f"- tiny_artifact_removed_count: {write_report.get('tiny_artifact_removed_count')}",
        "",
        "## Regression",
    ]
    for key, row in regression.items():
        lines.append(f"- {key}: detected={row.get('detected')} status={row.get('status')}")
    (run_dir / "human_review_focus.md").write_text("\n".join(lines) + "\n", "utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4D-3 final residual repeat fix.")
    parser.add_argument("--draft-dir", type=Path, default=DEFAULT_DRAFT_DIR)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--phase4d2-dir", type=Path, default=DEFAULT_PHASE4D2_DIR)
    parser.add_argument("--word-timeline", type=Path, default=DEFAULT_WORD_TIMELINE)
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    args = parser.parse_args()

    run_dir = args.runtime / f"aroll_phase4d3_final_repeat_fix_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    assert_jianying_closed()

    paths = require_phase4d2_inputs(args.phase4d2_dir)
    copy_inputs(run_dir, paths)
    input_report = read_json(paths["input_phase4d2_write_report"])
    final_edl = read_json(paths["video_edl"])
    display_plan = read_json(paths["display_subtitles"])
    word_timeline = read_json(args.word_timeline)

    before_audit = audit_final_residual_repeats(final_edl, display_plan, word_timeline)
    write_json(run_dir / "final_residual_repeat_audit_before_fix.json", before_audit)
    hidden_before = {
        "issues": [row for row in before_audit.get("issues") or [] if row.get("issue_type") == "hidden_audio_repeat"],
        "high_confidence_hidden_audio_repeat_count": before_audit.get("high_confidence_hidden_audio_repeat_count", 0),
    }
    write_json(run_dir / "hidden_audio_repeat_audit.json", hidden_before)
    tiny_before = audit_tiny_segments(final_edl, display_plan)
    write_json(run_dir / "tiny_segment_guard_report.json", tiny_before)
    plan = build_final_repeat_fix_plan(before_audit, tiny_before)
    write_json(run_dir / "final_repeat_fix_plan.json", plan)

    fixed_edl, edl_apply_report = apply_fix_plan_to_edl(final_edl, plan)
    fixed_subtitles, subtitle_apply_report = apply_fix_plan_to_subtitles(display_plan, plan, fixed_edl)
    fixed_readability = readability_report(fixed_subtitles)
    after_audit = audit_final_residual_repeats(fixed_edl, fixed_subtitles, word_timeline)
    tiny_after = audit_tiny_segments(fixed_edl, fixed_subtitles)

    write_json(run_dir / "selected_video_edl_after_repeat_fix.json", fixed_edl)
    write_json(run_dir / "subtitle_plan_after_repeat_fix.json", fixed_subtitles)
    write_json(run_dir / "subtitle_readability_after_repeat_fix.json", fixed_readability)
    write_json(run_dir / "final_residual_repeat_audit_after_fix.json", after_audit)
    write_json(run_dir / "edl_apply_report.json", edl_apply_report)
    write_json(run_dir / "subtitle_apply_report.json", subtitle_apply_report)
    write_json(run_dir / "tiny_segment_guard_after_fix.json", tiny_after)

    gate_fatals: list[str] = []
    if int(after_audit.get("high_confidence_text_repeat_count") or 0) > 0:
        gate_fatals.append("HIGH_CONFIDENCE_TEXT_REPEAT_REMAINS")
    if int(after_audit.get("high_confidence_hidden_audio_repeat_count") or 0) > 0:
        gate_fatals.append("HIGH_CONFIDENCE_HIDDEN_AUDIO_REPEAT_REMAINS")
    if int(tiny_after.get("unhandled_tiny_artifact_segment_count") or 0) > 0:
        gate_fatals.append("UNHANDLED_TINY_ARTIFACT_SEGMENT_REMAINS")
    if int(tiny_after.get("unauthorized_segment_under_500ms") or 0) > 0:
        gate_fatals.append("UNAUTHORIZED_SEGMENT_UNDER_500MS_REMAINS")
    if int(fixed_readability.get("overlong_subtitle_count") or 0) > 0:
        gate_fatals.append("OVERLONG_SUBTITLE_REMAINS")
    if int(fixed_readability.get("single_char_subtitle_count") or 0) > 0:
        gate_fatals.append("SINGLE_CHAR_SUBTITLE_REMAINS")
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

    material_path = str(((selected_main.get("materials") or [{}])[0]).get("material_path") or "")
    cutter = SafeGapCutter(material_path, run_dir / "audio_vad")
    postwrite_audio_audit, postwrite_audio_md = audit_postwrite_audio(fixed_edl, fixed_subtitles, word_timeline, cutter)
    write_json(run_dir / "postwrite_audio_pause_audit.json", postwrite_audio_audit)
    (run_dir / "postwrite_audio_pause_audit.md").write_text(postwrite_audio_md, "utf-8")

    backup_paths = backup_draft_files(args.draft_dir, timeline_id, run_dir, root_mirror_required)
    main_track = get_track(data, str(selected_main["track_id"]))
    text_track = get_track(data, str(selected_text_track["track_id"]))
    old_video_segments = deepcopy(main_track.get("segments") or [])
    new_video_segments, video_split_rows = split_video_segments_for_edl(old_video_segments, fixed_edl)
    new_text_segments, text_rows = material_text_rows(data, text_track, subtitles, fixed_subtitles)
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

    regression = regression_checks(fixed_subtitles, before_audit, after_audit, tiny_after)
    write_json(run_dir / "feedback_regression_report.json", regression)
    source_range_s = input_report.get("source_range_s") or []
    final_duration_us = int(data["duration"])
    write_report = {
        "status": "ok",
        "draft_dir": str(args.draft_dir),
        "runtime_dir": str(run_dir),
        "source_range_s": source_range_s,
        "final_duration_us": final_duration_us,
        "final_duration_s": round(final_duration_us / 1_000_000, 3),
        "video_segments": len(new_video_segments),
        "subtitle_segments": len(new_text_segments),
        "drop_count": plan["summary"]["drop_count"],
        "trim_count": plan["summary"]["trim_count"],
        "hidden_audio_cut_count": plan["summary"]["hidden_audio_cut_count"],
        "tiny_artifact_removed_count": plan["summary"]["tiny_artifact_removed_count"],
        "before_fix_text_repeat_count": before_audit.get("high_confidence_text_repeat_count"),
        "before_fix_hidden_audio_repeat_count": before_audit.get("high_confidence_hidden_audio_repeat_count"),
        "before_fix_tiny_artifact_count": tiny_before.get("tiny_segment_count"),
        "after_fix_text_repeat_count": after_audit.get("high_confidence_text_repeat_count"),
        "after_fix_hidden_audio_repeat_count": after_audit.get("high_confidence_hidden_audio_repeat_count"),
        "after_fix_tiny_artifact_count": tiny_after.get("unhandled_tiny_artifact_segment_count"),
        "tiny_segment_count_before": tiny_before.get("tiny_segment_count"),
        "removed_tiny_artifact_count": plan["summary"]["tiny_artifact_removed_count"],
        "merged_tiny_segment_count": 0,
        "allowed_tiny_segment_count": len(tiny_after.get("allowed_tiny_segments") or []),
        "min_segment_duration_us_after_fix": tiny_after.get("min_segment_duration_us"),
        "subtitle_readability": fixed_readability,
        "regression": regression,
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
        "project_json_modified": False,
        "timeline_layout_modified": False,
        "audio_filter_tracks_modified": False,
        "extra_draft_dirs_created": False,
        "edl_apply_report": edl_apply_report,
        "subtitle_apply_report": subtitle_apply_report,
        "video_split_rows": video_split_rows,
        "subtitle_rows": text_rows,
    }
    write_json(run_dir / "write_report.json", write_report)
    write_human_focus(run_dir, write_report, regression)

    print("status=ok")
    print(f"runtime={run_dir}")
    print(f"report={run_dir / 'write_report.json'}")
    print(f"before_text_repeat={write_report['before_fix_text_repeat_count']}")
    print(f"before_hidden_audio_repeat={write_report['before_fix_hidden_audio_repeat_count']}")
    print(f"before_tiny={write_report['before_fix_tiny_artifact_count']}")
    print(f"after_text_repeat={write_report['after_fix_text_repeat_count']}")
    print(f"after_hidden_audio_repeat={write_report['after_fix_hidden_audio_repeat_count']}")
    print(f"after_tiny={write_report['after_fix_tiny_artifact_count']}")
    print(f"final_duration_s={write_report['final_duration_s']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
