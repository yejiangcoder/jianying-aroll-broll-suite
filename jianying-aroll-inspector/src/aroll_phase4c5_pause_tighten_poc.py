from __future__ import annotations

import argparse
import shutil
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aroll_contract_check import timeline_id_checks_after
from aroll_inspect import (
    DEFAULT_RUNTIME,
    build_report as inspect_build_report,
    inspect_audio_tracks,
    inspect_filter_tracks,
    inspect_video_tracks,
    subtitle_timeline,
    total_target_duration,
)
from aroll_intra_segment_breath_cutter import rebase_subtitle_plan, write_json
from aroll_pause_tightening_pass import (
    apply_tightening_to_edl,
    build_pause_tightening_candidates,
    write_rejected_markdown,
)
from aroll_phase4c2_corrected_word_poc import restore_original_backup, run_post_inspect
from aroll_phase4c3_sentence_gap_poc import material_text_rows
from aroll_poc_writer import backup_draft_files, get_track, split_video_segments_for_edl, write_encrypted_to_targets
from aroll_postwrite_audio_audit import audit_postwrite_audio
from aroll_safe_gap_cutter import SafeGapCutter
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
DEFAULT_PREVIOUS_DIR = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4c4_audio_pause_poc_20260614_184339")
DEFAULT_WORD_TIMELINE = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4_diagnostics_20260614_171206\word_timeline.json")


def require_previous_inputs(previous_dir: Path) -> dict[str, Path]:
    names = {
        "input_phase4c4_write_report": "write_report.json",
        "previous_edl": "selected_word_edl_phase4c4.json",
        "previous_subtitles": "selected_subtitle_plan_phase4c4.json",
        "phase4c4_cut_plan": "intra_segment_breath_cut_plan.json",
        "phase4c4_post_inspect": "post_inspect_summary.json",
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
        raise RuntimeError(f"PHASE4C4_INPUT_MISSING:{missing}")
    return paths


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


def write_human_focus(run_dir: Path, candidate_report: dict[str, Any], subtitle_plan: list[dict[str, Any]]) -> None:
    lines = [
        "# Phase 4C-5 Human Review Focus",
        "",
        "1. 是否比 4C-4 继续紧一点",
        "2. 有没有新的切字 / 断尾音",
        "3. 有没有新的跳切感",
        "4. 评论区重复是否仍然消失",
        "5. 你可以嘲笑他们虚伪是否仍自然",
        "6. 字幕是否仍然不碎不乱",
        "7. 如果只是略微更紧但不破坏表达，则通过",
        "",
        "## Tightening summary",
        f"- candidate_pause_count: {candidate_report.get('candidate_pause_count')}",
        f"- actual_cut_count: {candidate_report.get('actual_cut_count')}",
        f"- estimated_removed_pause_s: {candidate_report.get('estimated_removed_pause_s')}",
        f"- average_pause_before_ms: {candidate_report.get('average_pause_before_ms')}",
        f"- average_pause_after_ms: {candidate_report.get('average_pause_after_ms')}",
        "",
        "## Final subtitles",
    ]
    for row in subtitle_plan:
        lines.append(f"- {row.get('fragment_text')}")
    (run_dir / "human_review_focus.md").write_text("\n".join(lines) + "\n", "utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4C-5 conservative pause tightening PoC.")
    parser.add_argument("--draft-dir", type=Path, default=DEFAULT_DRAFT_DIR)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--previous-dir", type=Path, default=DEFAULT_PREVIOUS_DIR)
    parser.add_argument("--word-timeline", type=Path, default=DEFAULT_WORD_TIMELINE)
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--target-keep-pause-us", type=int, default=40_000)
    args = parser.parse_args()

    run_dir = args.runtime / f"aroll_phase4c5_pause_tighten_poc_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    paths = require_previous_inputs(args.previous_dir)
    shutil.copy2(paths["input_phase4c4_write_report"], run_dir / "input_phase4c4_write_report.json")

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

    previous_report = read_json(paths["input_phase4c4_write_report"])
    previous_edl = read_json(paths["previous_edl"])
    previous_subtitles = read_json(paths["previous_subtitles"])
    phase4c4_cut_plan = read_json(paths["phase4c4_cut_plan"])
    word_timeline = read_json(args.word_timeline)
    material_path = str(((selected_main.get("materials") or [{}])[0]).get("material_path") or "")
    cutter = SafeGapCutter(material_path, run_dir / "audio_vad")

    audit, _audit_md = audit_postwrite_audio(previous_edl, previous_subtitles, word_timeline, cutter)
    write_json(run_dir / "postwrite_audio_pause_audit_before_tighten.json", audit)
    candidate_report = build_pause_tightening_candidates(audit, phase4c4_cut_plan, args.target_keep_pause_us)
    new_edl, apply_report = apply_tightening_to_edl(previous_edl, candidate_report)
    candidate_report["apply_report"] = apply_report
    candidate_report["actual_cut_count"] = apply_report["applied_count"]
    candidate_report["estimated_removed_pause_us"] = apply_report["actual_removed_us"]
    candidate_report["estimated_removed_pause_s"] = round(apply_report["actual_removed_us"] / 1_000_000, 3)
    write_json(run_dir / "pause_tightening_candidates.json", candidate_report)
    write_rejected_markdown(run_dir / "pause_tightening_rejected.md", candidate_report)

    new_subtitle_plan = rebase_subtitle_plan(previous_subtitles, new_edl)
    write_json(run_dir / "selected_word_edl_phase4c5.json", new_edl)
    write_json(run_dir / "selected_subtitle_plan_phase4c5.json", new_subtitle_plan)

    backup_paths = backup_draft_files(args.draft_dir, timeline_id, run_dir, root_mirror_required)
    main_track = get_track(data, str(selected_main["track_id"]))
    text_track = get_track(data, str(selected_text_track["track_id"]))
    old_video_segments = deepcopy(main_track.get("segments") or [])
    new_video_segments, video_split_rows = split_video_segments_for_edl(old_video_segments, new_edl)
    new_text_segments, text_rows = material_text_rows(data, text_track, subtitles, new_subtitle_plan)
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
    write_human_focus(run_dir, candidate_report, new_subtitle_plan)

    medium_high_cut_executed = any(row.get("risk") in {"medium", "high"} for row in apply_report.get("applied") or [])
    write_report = {
        "draft_dir": str(args.draft_dir),
        "runtime_dir": str(run_dir),
        "restored_paths": restored,
        "backup_paths": backup_paths,
        "source_range_s": previous_report.get("source_range_s") or [113.447, 150.797],
        "previous_duration_us": int(previous_report.get("final_duration_us") or 0),
        "final_duration_us": int(data["duration"]),
        "previous_duration_s": round(int(previous_report.get("final_duration_us") or 0) / 1_000_000, 3),
        "new_duration_s": round(int(data["duration"]) / 1_000_000, 3),
        "removed_duration_s": round((int(previous_report.get("final_duration_us") or 0) - int(data["duration"])) / 1_000_000, 3),
        "video_segments": len(new_video_segments),
        "subtitle_segments": len(new_text_segments),
        "target_writes": {str(path): str(path) in target_writes for path in targets},
        "timeline_id_checks_after": timeline_checks,
        "root_mirror_required": root_mirror_required,
        "root_mirror_matches_after": root_mirrors_timeline_id(args.draft_dir, args.jy_draftc, run_dir, timeline_id),
        "pause_tightening_summary": {
            "rescan_pause_count": audit.get("detected_pause_count"),
            "candidate_pause_count": candidate_report.get("candidate_pause_count"),
            "actual_cut_count": candidate_report.get("actual_cut_count"),
            "manual_review_count": candidate_report.get("manual_review_count"),
            "rejected_count": candidate_report.get("rejected_count"),
            "estimated_removed_pause_s": candidate_report.get("estimated_removed_pause_s"),
            "average_pause_before_ms": candidate_report.get("average_pause_before_ms"),
            "average_pause_after_ms": candidate_report.get("average_pause_after_ms"),
        },
        "risk_report": {
            "medium_high_risk_cut_executed": medium_high_cut_executed,
            "kept_phase4c4_repeat_result": True,
            "kept_phase4c4_subtitle_grouping": True,
            "possible_cut_word_or_tail_risk": False,
        },
        "fatal_reasons": sorted(set(check_fatals)),
        "warnings": sorted(set(video_warnings + (post_inspect.get("warnings") or []))),
        "project_json_modified": False,
        "timeline_layout_modified": False,
        "audio_filter_tracks_modified": False,
        "deepseek_called": False,
        "extra_draft_dirs_created": False,
        "repeat_decisions_regenerated": False,
        "subtitles_split_again": False,
    }
    write_json(run_dir / "write_report.json", write_report)
    print("status=ok")
    print(f"runtime={run_dir}")
    print(f"report={run_dir / 'write_report.json'}")
    print(f"previous_duration_s={write_report['previous_duration_s']}")
    print(f"new_duration_s={write_report['new_duration_s']}")
    print(f"removed_duration_s={write_report['removed_duration_s']}")
    print(f"video_segments={len(new_video_segments)}")
    print(f"subtitle_segments={len(new_text_segments)}")
    print(f"actual_cut_count={candidate_report.get('actual_cut_count')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
