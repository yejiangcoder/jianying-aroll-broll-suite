from __future__ import annotations

import argparse
import statistics
import shutil
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aroll_contract_check import timeline_id_checks_after
from aroll_decision_merger import decision_maps, merge_decisions
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
from aroll_intra_segment_breath_cutter import (
    apply_breath_cuts_to_edl,
    build_breath_cut_plan,
    rebase_subtitle_plan,
)
from aroll_pause_tightening_pass import (
    apply_tightening_to_edl,
    build_pause_tightening_candidates,
    write_rejected_markdown,
)
from aroll_phase4c2_corrected_word_poc import (
    post_merge_repeat_check,
    restore_original_backup,
    run_post_inspect,
)
from aroll_phase4c3_sentence_gap_poc import material_text_rows
from aroll_poc_writer import backup_draft_files, get_track, split_video_segments_for_edl, write_encrypted_to_targets
from aroll_postwrite_audio_audit import audit_postwrite_audio
from aroll_safe_gap_cutter import SafeGapCutter
from aroll_sentence_gap_compressor import (
    build_group_bounds,
    build_group_level_edl,
    build_sentence_gap_report,
    write_json,
)
from aroll_subtitle_fragment_grouper import group_subtitle_fragments
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
REQUESTED_SOURCE_START_US = 0
REQUESTED_SOURCE_END_US = 75_000_000
SOURCE_DURATION_US = 308_800_000
MIN_BREATH_PIECE_US = 240_000


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


def range_subtitle_indices(subtitles: list[dict[str, Any]], source_start_us: int, source_end_us: int) -> list[int]:
    return [
        int(row["subtitle_index"])
        for row in subtitles
        if int(row.get("start_us") or 0) >= source_start_us
        and int(row.get("end_us") or 0) <= source_end_us
    ]


def write_decision_merge_report(path: Path, merge_report: str, in_range_rows: list[dict[str, Any]]) -> None:
    lines = [
        merge_report.rstrip(),
        "",
        "## Phase 4D In-Range Kept Rows",
    ]
    for row in in_range_rows:
        lines.append(f"- sub_{int(row['subtitle_index']):06d}: {row.get('text')} | reason={row.get('reason')}")
    path.write_text("\n".join(lines) + "\n", "utf-8")


def write_sentence_review(path: Path, review_text: str) -> None:
    path.write_text(review_text, "utf-8")


def regression_report(
    source_subtitles: list[dict[str, Any]],
    final_subtitle_plan: list[dict[str, Any]],
    source_start_us: int,
    source_end_us: int,
) -> dict[str, Any]:
    source_text = "\n".join(
        str(row.get("subtitle_text") or "")
        for row in source_subtitles
        if int(row.get("start_us") or 0) >= source_start_us and int(row.get("start_us") or 0) < source_end_us
    )
    final_text = "\n".join(str(row.get("fragment_text") or row.get("text") or "") for row in final_subtitle_plan)

    def in_range(*needles: str) -> bool:
        return any(needle in source_text for needle in needles)

    checks: dict[str, dict[str, Any]] = {}
    if in_range("看就看到有人想爬出粪坑", "就看到有人想爬出粪坑"):
        ok = "就看到有人想爬出粪坑" in final_text and "看就看到有人想爬出粪坑" not in final_text
        checks["看/就看到有人想爬出粪坑"] = {"status": "fixed" if ok else "failed", "final_text": final_text}
    else:
        checks["看/就看到有人想爬出粪坑"] = {"status": "not_in_range"}

    if in_range("你嘲笑嘉豪", "规训"):
        ok = "你嘲笑嘉豪" in final_text and "规训" in final_text
        checks["你嘲笑嘉豪/规训"] = {"status": "fixed" if ok else "failed"}
    else:
        checks["你嘲笑嘉豪/规训"] = {"status": "not_in_range"}

    if in_range("人家年少", "寻找优越感"):
        ok = "人家年少的时候" in final_text and "寻找优越感" in final_text
        checks["人家年少时候/寻找优越感"] = {"status": "fixed" if ok else "failed"}
    else:
        checks["人家年少时候/寻找优越感"] = {"status": "not_in_range"}

    if in_range("你跪在地上你跪在地上叫大佬", "你跪在地上叫大佬"):
        ok = "你跪在地上叫大佬" in final_text and "你跪在地上你跪在地上" not in final_text
        checks["你跪在地上叫大佬"] = {"status": "fixed" if ok else "failed"}
    else:
        checks["你跪在地上叫大佬"] = {"status": "not_in_range"}

    if in_range("随意的肆意的踩踏", "肆意的踩踏"):
        ok = "肆意的踩踏" in final_text and "随意的肆意的踩踏" not in final_text
        checks["随意的/肆意的踩踏"] = {"status": "fixed" if ok else "failed"}
    else:
        checks["随意的/肆意的踩踏"] = {"status": "not_in_range"}

    for label, bad, good in [
        ("评论区评论区", "评论区评论区", "评论区"),
        ("给给老子", "给给老子", "给老子"),
        ("重新上重新上桌", "重新上重新上桌", "重新上桌"),
        ("你可以嘲笑她们/他们虚伪", "你可以嘲笑她们虚伪", "你可以嘲笑他们虚伪"),
    ]:
        if in_range(bad, good):
            ok = good in final_text and bad not in final_text
            checks[label] = {"status": "fixed" if ok else "failed"}
        else:
            checks[label] = {"status": "not_in_range"}

    return {
        "source_start_us": source_start_us,
        "source_end_us": source_end_us,
        "checks": checks,
        "final_subtitles": [str(row.get("fragment_text") or row.get("text") or "") for row in final_subtitle_plan],
    }


def _clip_piece_too_short(clip: dict[str, Any], intervals: list[dict[str, Any]], min_piece_us: int) -> bool:
    source_start = int(clip["source_start_us"])
    source_end = int(clip["source_end_us"])
    cursor = source_start
    for interval in sorted(intervals, key=lambda row: int(row["source_cut_start_us"])):
        cut_start = max(source_start, int(interval["source_cut_start_us"]))
        cut_end = min(source_end, int(interval["source_cut_end_us"]))
        if cut_end <= cut_start:
            continue
        if cut_start > cursor and cut_start - cursor < min_piece_us:
            return True
        cursor = max(cursor, cut_end)
    return cursor < source_end and source_end - cursor < min_piece_us


def filter_breath_plan_for_min_pieces(plan: dict[str, Any], clips: list[dict[str, Any]], min_piece_us: int) -> dict[str, Any]:
    clip_by_id = {str(row.get("clip_id") or ""): row for row in clips}
    accepted: list[dict[str, Any]] = []
    manual_review = list(plan.get("manual_review") or [])
    for cut in plan.get("cuts") or []:
        intervals = cut.get("source_cut_intervals") or [
            {
                "clip_id": cut.get("source_clip_id"),
                "source_cut_start_us": cut.get("source_cut_start_us"),
                "source_cut_end_us": cut.get("source_cut_end_us"),
            }
        ]
        by_clip: dict[str, list[dict[str, Any]]] = {}
        for interval in intervals:
            clip_id = str(interval.get("clip_id") or "")
            if clip_id:
                by_clip.setdefault(clip_id, []).append(interval)
        unsafe = False
        for clip_id, rows in by_clip.items():
            clip = clip_by_id.get(clip_id)
            if clip and _clip_piece_too_short(clip, rows, min_piece_us):
                unsafe = True
                break
        if unsafe:
            manual_review.append(cut | {"reject_reason": f"would_create_video_piece_under_{min_piece_us}us"})
        else:
            accepted.append(cut)

    type_counts: dict[str, int] = {}
    for row in accepted:
        key = str(row.get("cut_type") or "")
        type_counts[key] = type_counts.get(key, 0) + 1
    removed_values = [int(row.get("target_removed_us") or 0) for row in accepted]
    before_values = []
    after_values = []
    for row in accepted:
        kept = int(row.get("kept_pause_us") or 0)
        removed = int(row.get("target_removed_us") or 0)
        before_values.append(kept + removed)
        after_values.append(kept)
    filtered = dict(plan)
    filtered["cuts"] = accepted
    filtered["manual_review"] = manual_review
    filtered["breath_cut_count"] = len(accepted)
    filtered["inter_clip_compress_count"] = type_counts.get("inter_clip_compress", 0)
    filtered["split_clip_remove_internal_pause_count"] = type_counts.get("split_clip_remove_internal_pause", 0)
    filtered["trim_clip_edge_count"] = type_counts.get("trim_clip_edge", 0)
    filtered["manual_review_count"] = len(manual_review)
    filtered["estimated_removed_pause_us"] = sum(removed_values)
    filtered["estimated_removed_pause_s"] = round(sum(removed_values) / 1_000_000, 3)
    filtered["average_pause_before_ms"] = round(statistics.mean(before_values) / 1000, 3) if before_values else 0
    filtered["average_pause_after_ms"] = round(statistics.mean(after_values) / 1000, 3) if after_values else 0
    filtered["min_piece_guard_us"] = min_piece_us
    filtered["min_piece_guard_rejected_count"] = len(plan.get("cuts") or []) - len(accepted)
    return filtered


def write_human_focus(run_dir: Path, report: dict[str, Any], regression: dict[str, Any]) -> None:
    lines = [
        "# Phase 4D 75s Segment Human Review Focus",
        "",
        "打开唯一测试草稿：D:\\JianyingPro Drafts\\6月14日",
        "",
        "1. 75 秒段整体是否流畅",
        "2. 是否有重复句回归",
        "3. 是否有切字 / 断尾音",
        "4. 是否有跳切感",
        "5. 字幕是否不碎、不乱、不过长到影响观看",
        "6. 开头 / 中间 / 结尾是否仍有明显大停顿",
        "7. 「人家年少时候」「你跪在地上叫大佬」「寻找优越感」「肆意的踩踏」这些重点处是否自然",
        "",
        "## Summary",
        f"- source_range_s: {report.get('source_range_s')}",
        f"- final_duration_s: {report.get('final_duration_s')}",
        f"- removed_duration_s: {report.get('removed_duration_s')}",
        f"- video_segments: {report.get('video_segments')}",
        f"- subtitle_segments: {report.get('subtitle_segments')}",
        "",
        "## Regression",
    ]
    for key, row in (regression.get("checks") or {}).items():
        lines.append(f"- {key}: {row.get('status')}")
    lines.extend(["", "## Final subtitles"])
    for text in regression.get("final_subtitles") or []:
        lines.append(f"- {text}")
    (run_dir / "human_review_focus.md").write_text("\n".join(lines) + "\n", "utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4D 75s continuous A-Roll stability test.")
    parser.add_argument("--draft-dir", type=Path, default=DEFAULT_DRAFT_DIR)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--v5-dir", type=Path, default=DEFAULT_V5_DIR)
    parser.add_argument("--repeat-clusters", type=Path, default=DEFAULT_REPEAT_CLUSTERS)
    parser.add_argument("--word-timeline", type=Path, default=DEFAULT_WORD_TIMELINE)
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--target-keep-pause-us", type=int, default=20_000)
    args = parser.parse_args()

    run_dir = args.runtime / f"aroll_phase4d_75s_segment_test_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

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
    selected_indices = range_subtitle_indices(subtitles, REQUESTED_SOURCE_START_US, REQUESTED_SOURCE_END_US)
    if not selected_indices:
        raise RuntimeError("NO_SUBTITLES_IN_0_75S_RANGE")
    rows = selected_rows_for_range(subtitles, drops, micros, REQUESTED_SOURCE_START_US, REQUESTED_SOURCE_END_US)
    if not rows:
        raise RuntimeError("NO_KEPT_ROWS_AFTER_DECISIONS_IN_0_75S_RANGE")
    actual_start_us = min(int(row["source_start_us"]) for row in rows)
    actual_end_us = max(int(row["source_end_us"]) for row in rows)
    source_range_report = {
        "requested_source_range_s": [0.0, 75.0],
        "actual_source_range_s": [round(actual_start_us / 1_000_000, 3), round(actual_end_us / 1_000_000, 3)],
        "source_duration_s": round((actual_end_us - actual_start_us) / 1_000_000, 3),
        "subtitle_indices_in_requested_range": selected_indices,
        "kept_subtitle_indices": [int(row["subtitle_index"]) for row in rows],
        "dropped_in_range": [idx for idx in selected_indices if idx in drops],
        "micro_cleanup_in_range": [idx for idx in selected_indices if idx in micros],
    }
    write_json(run_dir / "source_range_report.json", source_range_report)
    write_decision_merge_report(run_dir / "decision_merge_report.md", merge_report, rows)
    write_json(
        run_dir / "semantic_guard_report.json",
        {
            "semantic_guard_blocks_total": len(merged.get("semantic_guard_blocks") or []),
            "semantic_guard_blocks_in_range": [
                row for row in (merged.get("semantic_guard_blocks") or [])
                if int(row.get("subtitle_index") or 0) in selected_indices
            ],
        },
    )

    grouped, group_report = group_subtitle_fragments(rows)
    repeat_check = post_merge_repeat_check(grouped)
    if not repeat_check["pass"]:
        raise RuntimeError(f"POST_MERGE_REPEAT_CHECK_FAILED:{repeat_check['residuals']}")
    word_timeline = read_json(args.word_timeline)
    material_path = str(((selected_main.get("materials") or [{}])[0]).get("material_path") or "")
    cutter = SafeGapCutter(material_path, run_dir / "audio_vad")

    hidden_report, hidden_context = diagnose_hidden_repeat(grouped, word_timeline, cutter)
    write_json(run_dir / "hidden_audio_repeat_diagnostics.json", hidden_report)
    (run_dir / "hidden_audio_repeat_context.md").write_text(hidden_context, "utf-8")

    group_bounds = build_group_bounds(grouped, word_timeline, hidden_report)
    sentence_report, sentence_review = build_sentence_gap_report(group_bounds, cutter.silences)
    write_json(run_dir / "sentence_gap_compression_report.json", sentence_report)
    write_sentence_review(run_dir / "sentence_gap_compression_review.md", sentence_review)
    sentence_edl, sentence_subtitles = build_group_level_edl(group_bounds)
    write_json(run_dir / "edl_after_sentence_gap_75s.json", sentence_edl)
    write_json(run_dir / "subtitle_plan_after_sentence_gap_75s.json", sentence_subtitles)

    audit, audit_md = audit_postwrite_audio(sentence_edl, sentence_subtitles, word_timeline, cutter)
    write_json(run_dir / "postwrite_audio_pause_audit.json", audit)
    (run_dir / "postwrite_audio_pause_review.md").write_text(audit_md, "utf-8")
    raw_breath_plan = build_breath_cut_plan(audit)
    write_json(run_dir / "intra_segment_breath_cut_plan.raw.json", raw_breath_plan)
    breath_plan = filter_breath_plan_for_min_pieces(raw_breath_plan, sentence_edl, MIN_BREATH_PIECE_US)
    write_json(run_dir / "intra_segment_breath_cut_plan.json", breath_plan)
    breath_edl = apply_breath_cuts_to_edl(sentence_edl, breath_plan)
    breath_subtitles = rebase_subtitle_plan(sentence_subtitles, breath_edl)
    write_json(run_dir / "edl_after_breath_cut_75s.json", breath_edl)
    write_json(run_dir / "subtitle_plan_after_breath_cut_75s.json", breath_subtitles)

    post_breath_audit, post_breath_md = audit_postwrite_audio(breath_edl, breath_subtitles, word_timeline, cutter)
    write_json(run_dir / "post_breath_audio_pause_audit.json", post_breath_audit)
    (run_dir / "post_breath_audio_pause_review.md").write_text(post_breath_md, "utf-8")
    tightening_report = build_pause_tightening_candidates(post_breath_audit, breath_plan, args.target_keep_pause_us)
    final_edl, apply_report = apply_tightening_to_edl(breath_edl, tightening_report)
    tightening_report["apply_report"] = apply_report
    tightening_report["actual_cut_count"] = apply_report["applied_count"]
    tightening_report["estimated_removed_pause_us"] = apply_report["actual_removed_us"]
    tightening_report["estimated_removed_pause_s"] = round(apply_report["actual_removed_us"] / 1_000_000, 3)
    write_json(run_dir / "pause_tightening_candidates.json", tightening_report)
    write_rejected_markdown(run_dir / "pause_tightening_rejected.md", tightening_report)
    final_subtitles = rebase_subtitle_plan(breath_subtitles, final_edl)
    write_json(run_dir / "word_level_edl_75s.json", final_edl)
    write_json(run_dir / "subtitle_group_plan_75s.json", final_subtitles)

    regression = regression_report(subtitles, final_subtitles, REQUESTED_SOURCE_START_US, REQUESTED_SOURCE_END_US)
    write_json(run_dir / "repeat_regression_report.json", regression)

    backup_paths = backup_draft_files(args.draft_dir, timeline_id, run_dir, root_mirror_required)
    main_track = get_track(data, str(selected_main["track_id"]))
    text_track = get_track(data, str(selected_text_track["track_id"]))
    old_video_segments = deepcopy(main_track.get("segments") or [])
    new_video_segments, video_split_rows = split_video_segments_for_edl(old_video_segments, final_edl)
    new_text_segments, text_rows = material_text_rows(data, text_track, subtitles, final_subtitles)
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

    source_duration_us = actual_end_us - actual_start_us
    final_duration_us = int(data["duration"])
    write_report = {
        "draft_dir": str(args.draft_dir),
        "runtime_dir": str(run_dir),
        "restored_paths": restored,
        "backup_paths": backup_paths,
        "source_range_s": source_range_report["actual_source_range_s"],
        "source_duration_s": round(source_duration_us / 1_000_000, 3),
        "final_duration_us": final_duration_us,
        "final_duration_s": round(final_duration_us / 1_000_000, 3),
        "removed_duration_s": round((source_duration_us - final_duration_us) / 1_000_000, 3),
        "video_segments": len(new_video_segments),
        "subtitle_segments": len(new_text_segments),
        "drop_decision_count": len(source_range_report["dropped_in_range"]),
        "micro_cleanup_count": len(source_range_report["micro_cleanup_in_range"]),
        "sentence_gap_cut_count": sentence_report.get("sentence_gap_cut_count"),
        "postwrite_pause_cut_count": breath_plan.get("breath_cut_count"),
        "tightening_cut_count": tightening_report.get("actual_cut_count"),
        "sentence_gap_removed_s": sentence_report.get("total_sentence_gap_removed_s"),
        "postwrite_pause_removed_s": breath_plan.get("estimated_removed_pause_s"),
        "tightening_removed_s": tightening_report.get("estimated_removed_pause_s"),
        "total_pause_removed_s": round(
            float(sentence_report.get("total_sentence_gap_removed_s") or 0)
            + float(breath_plan.get("estimated_removed_pause_s") or 0)
            + float(tightening_report.get("estimated_removed_pause_s") or 0),
            3,
        ),
        "average_pause_before_ms": tightening_report.get("average_pause_before_ms"),
        "average_pause_after_ms": tightening_report.get("average_pause_after_ms"),
        "manual_review_pause_count": breath_plan.get("manual_review_count"),
        "rejected_high_risk_pause_count": tightening_report.get("rejected_count"),
        "target_writes": {str(path): str(path) in target_writes for path in targets},
        "timeline_id_checks_after": timeline_checks,
        "root_mirror_required": root_mirror_required,
        "root_mirror_matches_after": root_mirrors_timeline_id(args.draft_dir, args.jy_draftc, run_dir, timeline_id),
        "merge_summary": merge_summary,
        "repeat_regression_summary": {key: row.get("status") for key, row in regression["checks"].items()},
        "risk_report": {
            "medium_high_risk_cut_executed": any(row.get("risk") in {"medium", "high"} for row in apply_report.get("applied") or []),
            "subtitles_split_again": False,
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
    write_human_focus(run_dir, write_report, regression)

    print("status=ok")
    print(f"runtime={run_dir}")
    print(f"report={run_dir / 'write_report.json'}")
    print(f"source_range_s={write_report['source_range_s']}")
    print(f"source_duration_s={write_report['source_duration_s']}")
    print(f"final_duration_s={write_report['final_duration_s']}")
    print(f"removed_duration_s={write_report['removed_duration_s']}")
    print(f"video_segments={write_report['video_segments']}")
    print(f"subtitle_segments={write_report['subtitle_segments']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
