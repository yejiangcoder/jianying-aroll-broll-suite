from __future__ import annotations

import argparse
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from aroll_contract_check import timeline_id_checks_after
from aroll_decision_dryrun import read_json
from aroll_inspect import (
    DEFAULT_RUNTIME,
    inspect_audio_tracks,
    inspect_filter_tracks,
    inspect_video_tracks,
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
from aroll_smart_writer import conservative_review
from jy_bridge import (
    DEFAULT_JY_DRAFTC,
    assert_all_project_timeline_files_match_folder_ids,
    assert_layout_has_no_duplicate_timeline_ids,
    assert_timeline_content_id,
    decrypt,
    encrypt,
    root_mirrors_timeline_id,
    resolve_timeline_id,
    write_json,
)


DEFAULT_DEEPSEEK_RUN = Path(
    r"D:\video tools\jianying-aroll-inspector\runtime\aroll_deepseek_decision_20260614_114516"
)
LEAD_GUARD_US = 250_000
TAIL_GUARD_US = 400_000
MERGE_KEEP_GAP_US = 350_000
MICRO_LEAD_GUARD_US = 80_000
MAX_PAUSE_AFTER_US = 600_000
DEFAULT_PAUSE_AFTER_US = 60_000


def clamp_pause_after_us(span: dict[str, Any]) -> int:
    if "pause_after_ms" not in span:
        return DEFAULT_PAUSE_AFTER_US
    try:
        pause_us = int(float(span.get("pause_after_ms") or 0) * 1000)
    except Exception:
        pause_us = DEFAULT_PAUSE_AFTER_US
    return max(0, min(MAX_PAUSE_AFTER_US, pause_us))


def make_residual_cleanup_overrides() -> dict[str, Any]:
    return {
        "source": "user_feedback",
        "rules": [
            {
                "rule_id": "fb_001",
                "type": "search_and_cleanup",
                "pattern": "你嘲笑嘉豪",
                "problem": "句内/相邻断句残留：对自己人 / 的是对自己人的规训",
                "mode": "conservative_detect_then_cleanup",
                "expected_text_contains_any": ["你嘲笑嘉豪", "对自己人", "规训"],
            },
            {
                "rule_id": "fb_002",
                "type": "dedupe_repeated_phrase",
                "pattern": "你跪在地上",
                "problem": "句内重复：你跪在地上 你跪在地上叫大佬",
                "mode": "keep_last_occurrence",
                "expected_text_contains_any": ["你跪在地上", "叫大佬"],
            },
        ],
    }


def neighbor_context(rows: list[dict[str, Any]], index: int, radius: int = 2) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        row_index = int(row["subtitle_index"])
        if index - radius <= row_index <= index + radius:
            out.append(compact_subtitle(row))
    return out


def compact_subtitle(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "uid": row["subtitle_uid"],
        "index": int(row["subtitle_index"]),
        "text": row.get("subtitle_text") or "",
        "start_us": int(row["start_us"]),
        "duration_us": int(row["duration_us"]),
        "end_us": int(row["end_us"]),
    }


def diagnose_residuals(rows: list[dict[str, Any]], overrides: dict[str, Any]) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    diagnosis = {
        "source": "subtitle_timeline",
        "matches": [],
        "fatal_reasons": [],
        "warnings": [],
    }
    micro_cuts: dict[int, dict[str, Any]] = {}
    rows_by_index = {int(row["subtitle_index"]): row for row in rows}

    for rule in overrides["rules"]:
        rule_id = rule["rule_id"]
        contains = rule.get("expected_text_contains_any") or [rule.get("pattern")]
        matched = [
            compact_subtitle(row)
            for row in rows
            if any(str(needle) in str(row.get("subtitle_text") or "") for needle in contains)
        ]
        contexts: list[dict[str, Any]] = []
        for match in matched:
            contexts.append(
                {
                    "match": match,
                    "neighbor_context": neighbor_context(rows, int(match["index"])),
                }
            )
        action = "keep_for_safety"
        reason = ""
        if rule_id == "fb_001":
            sub2 = rows_by_index.get(2)
            sub3 = rows_by_index.get(3)
            if not sub2 or not sub3:
                diagnosis["fatal_reasons"].append("FB_001_EXPECTED_SUB_2_3_NOT_FOUND")
            action = "needs_manual_or_audio_word_alignment"
            reason = (
                "命中 sub_000002/sub_000003，相邻字幕共同构成完整语义；"
                "自动删除任一条会造成语义残缺，本轮保守不动。"
            )
        elif rule_id == "fb_002":
            target = next(
                (
                    row for row in rows
                    if "你跪在地上你跪在地上叫大佬" in str(row.get("subtitle_text") or "")
                ),
                None,
            )
            if not target:
                diagnosis["fatal_reasons"].append("FB_002_EXACT_REPEAT_NOT_FOUND")
                action = "blocked"
                reason = "没有找到用户指出的精确句内重复。"
            else:
                text = str(target.get("subtitle_text") or "")
                phrase = "你跪在地上"
                first = text.find(phrase)
                last = text.rfind(phrase)
                if first < 0 or last <= first:
                    diagnosis["fatal_reasons"].append("FB_002_REPEAT_POSITION_UNSTABLE")
                    action = "blocked"
                    reason = "重复 phrase 位置无法稳定估算。"
                else:
                    start_us = int(target["start_us"])
                    duration_us = int(target["duration_us"])
                    estimated_cut_us = start_us + int(duration_us * (last / max(1, len(text))))
                    micro_cut_start_us = max(start_us, estimated_cut_us - MICRO_LEAD_GUARD_US)
                    target_index = int(target["subtitle_index"])
                    micro_cuts[target_index] = {
                        "rule_id": rule_id,
                        "subtitle_uid": target["subtitle_uid"],
                        "subtitle_index": target_index,
                        "text": text,
                        "repeat_phrase": phrase,
                        "keep_occurrence": "last",
                        "first_occurrence_char_start": first,
                        "last_occurrence_char_start": last,
                        "text_length": len(text),
                        "estimated_cut_us": estimated_cut_us,
                        "micro_lead_guard_us": MICRO_LEAD_GUARD_US,
                        "micro_cut_start_us": micro_cut_start_us,
                        "kept_text_estimate": text[last:],
                        "subtitle_text_modified": False,
                    }
                    action = "micro cut"
                    reason = "同一字幕内部重复 phrase，删除前一次重复，保留最后一次完整表达。"
        diagnosis["matches"].append(
            {
                "rule_id": rule_id,
                "rule": rule,
                "matched_subtitles": matched,
                "neighbor_context": contexts,
                "action": action,
                "reason": reason,
            }
        )

    if diagnosis["fatal_reasons"]:
        return diagnosis, {}
    return diagnosis, micro_cuts


def apply_cleanup_metadata(reviewed: dict[str, Any], diagnosis: dict[str, Any], micro_cuts: dict[int, dict[str, Any]]) -> dict[str, Any]:
    reviewed_v2 = deepcopy(reviewed)
    for span in reviewed_v2.get("spans") or []:
        start_index = int(span["subtitle_start_index"])
        end_index = int(span["subtitle_end_index"])
        span["residual_cleanup_action"] = "none"
        for index in range(start_index, end_index + 1):
            if index in micro_cuts:
                span["residual_cleanup_action"] = "micro_cut"
                span["micro_cut"] = micro_cuts[index]
    reviewed_v2["decision_mode"] = "conservative_deepseek_plus_residual_cleanup_v2"
    reviewed_v2["residual_cleanup_summary"] = {
        "rule_count": len(diagnosis.get("matches") or []),
        "executed_cleanup_count": len(micro_cuts),
        "skipped_cleanup_count": len([m for m in diagnosis.get("matches") or [] if m.get("action") != "micro cut"]),
        "micro_cut_count": len(micro_cuts),
        "adjacent_subtitle_drop_count": 0,
        "forced_keep_count": len([
            span for span in reviewed_v2.get("spans") or []
            if span.get("review_action") == "force_keep"
        ]),
        "micro_cuts": list(micro_cuts.values()),
    }
    return reviewed_v2


def previous_or_next_drop_indices(spans: list[dict[str, Any]]) -> set[int]:
    drop_indices: set[int] = set()
    for span in spans:
        if span.get("decision") == "drop":
            drop_indices.update(range(int(span["subtitle_start_index"]), int(span["subtitle_end_index"]) + 1))
    return drop_indices


def build_smart_v2_edl(
    reviewed_decisions: dict[str, Any],
    subtitles: list[dict[str, Any]],
    main_total_duration_us: int,
    micro_cuts: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    rows_by_index = {int(row["subtitle_index"]): row for row in subtitles}
    spans = sorted(
        reviewed_decisions.get("spans") or [],
        key=lambda item: (int(item["subtitle_start_index"]), int(item["subtitle_end_index"])),
    )
    drop_indices = previous_or_next_drop_indices(spans)
    strict_boundary_count = 0
    regions: list[dict[str, Any]] = []

    for span in spans:
        if span.get("decision") != "keep":
            continue
        for index in range(int(span["subtitle_start_index"]), int(span["subtitle_end_index"]) + 1):
            if index not in rows_by_index:
                continue
            row = rows_by_index[index]
            start_us = int(row["start_us"])
            end_us = int(row["end_us"])
            cut_start_us = max(0, start_us - LEAD_GUARD_US)
            cut_end_us = min(main_total_duration_us, end_us + TAIL_GUARD_US)
            drop_boundary_strict = False

            if index - 1 in drop_indices:
                cut_start_us = max(cut_start_us, start_us)
                drop_boundary_strict = True
                strict_boundary_count += 1
            if index + 1 in drop_indices:
                cut_end_us = min(cut_end_us, end_us)
                drop_boundary_strict = True
                strict_boundary_count += 1
            if index in micro_cuts:
                cut_start_us = max(cut_start_us, int(micro_cuts[index]["micro_cut_start_us"]))
                drop_boundary_strict = True

            if cut_end_us <= cut_start_us:
                continue
            regions.append(
                {
                    "clip_id": f"smart_v2_src_{len(regions) + 1:03d}",
                    "subtitle_start_uid": row["subtitle_uid"],
                    "subtitle_end_uid": row["subtitle_uid"],
                    "subtitle_start_index": index,
                    "subtitle_end_index": index,
                    "subtitle_start_us": start_us,
                    "subtitle_end_us": end_us,
                    "cut_start_us": cut_start_us,
                    "cut_end_us": cut_end_us,
                    "target_duration_us": cut_end_us - cut_start_us,
                    "pause_after_us": clamp_pause_after_us(span),
                    "source_span_ids": [span.get("span_id")],
                    "source_subtitle_count": 1,
                    "subtitle_texts": [row.get("subtitle_text") or ""],
                    "drop_boundary_strict": drop_boundary_strict,
                    "micro_cut": micro_cuts.get(index),
                }
            )

    merged: list[dict[str, Any]] = []
    for region in regions:
        if not merged:
            merged.append(deepcopy(region))
            continue
        current = merged[-1]
        adjacent = int(region["subtitle_start_index"]) == int(current["subtitle_end_index"]) + 1
        gap_us = int(region["cut_start_us"]) - int(current["cut_end_us"])
        has_micro_boundary = bool(region.get("micro_cut")) or bool(current.get("micro_cut"))
        if adjacent and gap_us <= MERGE_KEEP_GAP_US and not has_micro_boundary:
            current["subtitle_end_uid"] = region["subtitle_end_uid"]
            current["subtitle_end_index"] = region["subtitle_end_index"]
            current["subtitle_end_us"] = region["subtitle_end_us"]
            current["cut_end_us"] = max(int(current["cut_end_us"]), int(region["cut_end_us"]))
            current["target_duration_us"] = int(current["cut_end_us"]) - int(current["cut_start_us"])
            current["pause_after_us"] = region["pause_after_us"]
            current["source_span_ids"].extend(region.get("source_span_ids") or [])
            current["source_subtitle_count"] += int(region["source_subtitle_count"])
            current["subtitle_texts"].extend(region.get("subtitle_texts") or [])
            current["drop_boundary_strict"] = bool(current.get("drop_boundary_strict")) or bool(region.get("drop_boundary_strict"))
        else:
            merged.append(deepcopy(region))

    edl: list[dict[str, Any]] = []
    target_start_us = 0
    for index, region in enumerate(merged, start=1):
        duration_us = int(region["target_duration_us"])
        if duration_us <= 0:
            continue
        clip = deepcopy(region)
        clip["clip_id"] = f"smart_v2_{index:03d}"
        clip["target_start_us"] = target_start_us
        clip["boundary_mode"] = "smart_v2_residual_cleanup_with_guard"
        edl.append(clip)
        target_start_us += duration_us + int(clip.get("pause_after_us") or 0)
    return edl, strict_boundary_count


def summarize_edl(edl: list[dict[str, Any]], reviewed: dict[str, Any], source_duration_us: int, v1_duration_us: int) -> dict[str, Any]:
    keep_indices: set[int] = set()
    drop_indices: set[int] = set()
    for span in reviewed.get("spans") or []:
        target = keep_indices if span.get("decision") == "keep" else drop_indices
        target.update(range(int(span["subtitle_start_index"]), int(span["subtitle_end_index"]) + 1))
    output_duration_us = max((int(row["target_start_us"]) + int(row["target_duration_us"]) for row in edl), default=0)
    return {
        "smart_clip_count": len(edl),
        "kept_subtitle_count": len(keep_indices),
        "dropped_subtitle_count": len(drop_indices),
        "micro_cut_clip_count": len([row for row in edl if row.get("micro_cut")]),
        "source_duration_us": source_duration_us,
        "output_duration_us": output_duration_us,
        "estimated_deleted_duration_us": max(0, source_duration_us - output_duration_us),
        "reduced_vs_v1_us": max(0, v1_duration_us - output_duration_us),
        "first_5_clips": edl[:5],
        "last_5_clips": edl[-5:],
    }


def run_smart_v2_write(args: argparse.Namespace) -> tuple[Path, Path]:
    run_dir = args.runtime / f"aroll_smart_v2_write_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    clusters = read_json(args.deepseek_run / "take_clusters.json")
    decisions = read_json(args.deepseek_run / "deepseek_aroll_decisions.json")
    review_text = (args.deepseek_run / "human_review_drops.md").read_text("utf-8")
    source_subtitles = sorted(read_json(args.original_subtitle_timeline), key=lambda item: int(item["subtitle_index"]))

    overrides = make_residual_cleanup_overrides()
    diagnosis, micro_cuts = diagnose_residuals(source_subtitles, overrides)
    overrides_path = run_dir / "residual_cleanup_overrides.json"
    diagnosis_path = run_dir / "residual_cleanup_diagnosis.json"
    write_json(overrides_path, overrides)
    write_json(diagnosis_path, diagnosis)
    if diagnosis.get("fatal_reasons"):
        report_path = run_dir / "aroll_smart_v2_write_report.json"
        write_json(
            report_path,
            {
                "runtime_dir": str(run_dir),
                "fatal_reasons": diagnosis["fatal_reasons"],
                "warnings": diagnosis.get("warnings") or [],
                "residual_cleanup_overrides_path": str(overrides_path),
                "residual_cleanup_diagnosis_path": str(diagnosis_path),
            },
        )
        raise RuntimeError(f"RESIDUAL_CLEANUP_DIAGNOSIS_BLOCKED:{diagnosis['fatal_reasons']}; report={report_path}")

    timeline_id, timeline_name = resolve_timeline_id(args.draft_dir, args.timeline_name)
    timeline_dir = args.draft_dir / "Timelines" / timeline_id
    encrypted_path = timeline_dir / "draft_content.json"
    plain_before = run_dir / "draft_content.before.dec.json"
    plain_modified = run_dir / "draft_content.modified.dec.json"
    encrypted_out = run_dir / "draft_content.modified.enc.json"
    plain_after = run_dir / "draft_content.after.dec.json"
    subtitle_before_path = run_dir / "subtitle_timeline.before.json"
    reviewed_path = run_dir / "reviewed_aroll_decisions_v2.json"
    edl_path = run_dir / "smart_aroll_v2_edl.json"
    report_path = run_dir / "aroll_smart_v2_write_report.json"

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
    if len(subtitles) != 115:
        fatal_reasons.append(f"UNEXPECTED_SUBTITLE_COUNT:{len(subtitles)}")
    if main_total_duration_us < 300_000_000:
        fatal_reasons.append(f"RESTORE_NOT_FULL_SOURCE_DURATION:{main_total_duration_us}")
    if has_independent_audio or audio_tracks:
        fatal_reasons.append("AUDIO_TRACK_PRESENT_UNSUPPORTED_FOR_SMART_V2_WRITE")
    if has_complex_audio:
        fatal_reasons.extend(f"AUDIO:{reason}" for reason in audio_fatals)
    if has_global_filter or has_complex_filter or filter_tracks:
        fatal_reasons.append("FILTER_TRACK_PRESENT_UNSUPPORTED_FOR_SMART_V2_WRITE")
        fatal_reasons.extend(f"FILTER:{reason}" for reason in filter_fatals)
    if not main_speed_safe:
        fatal_reasons.append("MAIN_VIDEO_SPEED_UNSAFE")
    if fatal_reasons:
        write_json(
            report_path,
            {
                "draft_dir": str(args.draft_dir),
                "timeline_id": timeline_id,
                "timeline_name": timeline_name,
                "runtime_dir": str(run_dir),
                "fatal_reasons": sorted(set(fatal_reasons)),
                "warnings": sorted(set(warnings)),
                "residual_cleanup_overrides_path": str(overrides_path),
                "residual_cleanup_diagnosis_path": str(diagnosis_path),
            },
        )
        raise RuntimeError(f"SMART_V2_PREFLIGHT_BLOCKED:{sorted(set(fatal_reasons))}; report={report_path}")

    backup_paths = backup_draft_files(args.draft_dir, timeline_id, run_dir, root_mirror_required)
    reviewed, conservative_summary = conservative_review(clusters, decisions, review_text)
    reviewed_v2 = apply_cleanup_metadata(reviewed, diagnosis, micro_cuts)
    write_json(reviewed_path, reviewed_v2)
    edl, strict_boundary_count = build_smart_v2_edl(reviewed_v2, subtitles, main_total_duration_us, micro_cuts)
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
        raise RuntimeError("SMART_V2_REWRITE_PRODUCED_NO_VIDEO_SEGMENTS")
    if not new_text_segments:
        raise RuntimeError("SMART_V2_REWRITE_PRODUCED_NO_TEXT_SEGMENTS")

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
    edl_summary = summarize_edl(edl, reviewed_v2, before_video["total_duration_us"], args.v1_duration_us)

    report = {
        "draft_dir": str(args.draft_dir),
        "timeline_id": timeline_id,
        "timeline_name": timeline_name,
        "runtime_dir": str(run_dir),
        "deepseek_run": str(args.deepseek_run),
        "original_subtitle_timeline": str(args.original_subtitle_timeline),
        "backup_paths": backup_paths,
        "draft_content_before_dec_path": str(plain_before),
        "subtitle_timeline_before_path": str(subtitle_before_path),
        "residual_cleanup_overrides_path": str(overrides_path),
        "residual_cleanup_diagnosis_path": str(diagnosis_path),
        "reviewed_aroll_decisions_v2_path": str(reviewed_path),
        "smart_aroll_v2_edl_path": str(edl_path),
        "draft_content_after_dec_path": str(plain_after),
        "wrote_timeline_draft_content": str(timeline_dir / "draft_content.json") in target_writes,
        "wrote_timeline_template_2_tmp": str(timeline_dir / "template-2.tmp") in target_writes,
        "wrote_root_draft_content": str(args.draft_dir / "draft_content.json") in target_writes,
        "wrote_root_template_2_tmp": str(args.draft_dir / "template-2.tmp") in target_writes,
        "video_track_before": before_video,
        "video_track_after": after_video,
        "text_track_before": before_text,
        "text_track_after": after_text,
        "conservative_review_summary": conservative_summary,
        "residual_cleanup_summary": reviewed_v2["residual_cleanup_summary"],
        "drop_boundary_strict_count": strict_boundary_count,
        "edl_summary": edl_summary,
        "video_split_count": len(video_split_rows),
        "kept_subtitle_count": len(kept_subtitle_rows),
        "timeline_id_checks_after": timeline_checks,
        "root_mirror_required": root_mirror_required,
        "root_mirror_matches_after": root_mirror_after if root_mirror_required else None,
        "timeline_layout_modified": False,
        "fatal_reasons": sorted(set(check_fatals)),
        "warnings": sorted(set(warnings + [
            "MICRO_CUT_SUBTITLE_TEXT_NOT_MODIFIED; subtitle may still display full original text for sub_000023"
        ] if micro_cuts else warnings)),
    }
    write_json(report_path, report)
    return run_dir, report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Write Smart A-Roll v2 with deterministic residual stutter cleanup.")
    parser.add_argument("--draft-dir", type=Path, required=True)
    parser.add_argument("--deepseek-run", type=Path, default=DEFAULT_DEEPSEEK_RUN)
    parser.add_argument("--original-subtitle-timeline", type=Path, default=Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_inspect_20260614_111146\subtitle_timeline.json"))
    parser.add_argument("--timeline-name", default="")
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--v1-duration-us", type=int, default=240_879_999)
    args = parser.parse_args()

    run_dir, report_path = run_smart_v2_write(args)
    report = read_json(report_path)
    cleanup = report.get("residual_cleanup_summary") or {}
    edl = report.get("edl_summary") or {}
    print("status=ok" if not report.get("fatal_reasons") else "status=blocked")
    print(f"runtime={run_dir}")
    print(f"report={report_path}")
    print(f"residual_cleanup_overrides={report.get('residual_cleanup_overrides_path')}")
    print(f"residual_cleanup_diagnosis={report.get('residual_cleanup_diagnosis_path')}")
    print(f"reviewed_aroll_decisions_v2={report.get('reviewed_aroll_decisions_v2_path')}")
    print(f"smart_aroll_v2_edl={report.get('smart_aroll_v2_edl_path')}")
    print(f"cleanup_rules={cleanup.get('rule_count')}")
    print(f"executed_cleanup={cleanup.get('executed_cleanup_count')}")
    print(f"micro_cuts={cleanup.get('micro_cut_count')}")
    print(f"smart_v2_clips={edl.get('smart_clip_count')}")
    print(f"kept_subtitles={edl.get('kept_subtitle_count')}")
    print(f"dropped_subtitles={edl.get('dropped_subtitle_count')}")
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
