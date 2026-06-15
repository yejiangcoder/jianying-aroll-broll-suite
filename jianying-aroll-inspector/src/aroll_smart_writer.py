from __future__ import annotations

import argparse
import re
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
LEAD_GUARD_US = 200_000
TAIL_GUARD_US = 300_000
MERGE_KEEP_GAP_US = 350_000
MAX_PAUSE_AFTER_US = 600_000
DEFAULT_PAUSE_AFTER_US = 60_000
FORCE_KEEP_CLUSTERS = {"tc_004", "tc_010"}


def uid_number(uid: str) -> int:
    try:
        return int(str(uid).split("_")[-1])
    except Exception:
        return 0


def clamp_pause_after_us(span: dict[str, Any]) -> int:
    if "pause_after_ms" not in span:
        return DEFAULT_PAUSE_AFTER_US
    try:
        pause_us = int(float(span.get("pause_after_ms") or 0) * 1000)
    except Exception:
        pause_us = DEFAULT_PAUSE_AFTER_US
    return max(0, min(MAX_PAUSE_AFTER_US, pause_us))


def parse_drop_confidence(review_text: str) -> dict[tuple[str, str], str]:
    confidence_by_range: dict[tuple[str, str], str] = {}
    current_start = ""
    current_end = ""
    for line in review_text.splitlines():
        span_match = re.match(r"- Drop span:\s*(sub_\d+)\s*->\s*(sub_\d+)", line.strip())
        if span_match:
            current_start, current_end = span_match.group(1), span_match.group(2)
            continue
        confidence_match = re.match(r"- Confidence:\s*(\w+)", line.strip())
        if confidence_match and current_start and current_end:
            confidence_by_range[(current_start, current_end)] = confidence_match.group(1).lower()
            current_start = ""
            current_end = ""
    return confidence_by_range


def candidate_quality_confidence(cluster: dict[str, Any], take_id: str) -> str:
    candidates = cluster.get("candidates") or []
    dropped = next((row for row in candidates if row.get("take_id") == take_id), None)
    kept = next((row for row in candidates if row.get("take_id") == cluster.get("best_take_id")), None)
    if not dropped or not kept:
        return "unknown"
    try:
        diff = int(kept.get("quality_score") or 0) - int(dropped.get("quality_score") or 0)
    except Exception:
        return "unknown"
    if diff >= 12:
        return "high"
    if diff >= 5:
        return "medium"
    return "low"


def conservative_review(
    clusters: dict[str, Any],
    decisions: dict[str, Any],
    review_text: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    clusters_by_id = {
        str(cluster.get("cluster_id") or ""): cluster
        for cluster in clusters.get("clusters") or []
    }
    confidence_by_range = parse_drop_confidence(review_text)
    reviewed = deepcopy(decisions)
    original_drop_count = 0
    override_count = 0
    executed_drop_count = 0
    force_keep_rows: list[dict[str, Any]] = []

    for span in reviewed.get("spans") or []:
        span["original_decision"] = str(span.get("decision") or "").lower()
        span["decision"] = span["original_decision"]
        span["review_action"] = "unchanged"
        span["review_reason"] = ""
        if span["original_decision"] != "drop":
            continue

        original_drop_count += 1
        cluster_id = str(span.get("cluster_id") or "")
        take_id = str(span.get("take_id") or "")
        confidence = confidence_by_range.get(
            (str(span.get("subtitle_start_uid") or ""), str(span.get("subtitle_end_uid") or ""))
        )
        if not confidence:
            confidence = candidate_quality_confidence(clusters_by_id.get(cluster_id) or {}, take_id)
        span["review_confidence"] = confidence

        force_reason = ""
        if cluster_id in FORCE_KEEP_CLUSTERS:
            force_reason = f"{cluster_id} is manually forced keep for semantic-risk control"
        elif confidence != "high":
            force_reason = f"drop confidence is {confidence}, conservative mode keeps it"

        if force_reason:
            span["decision"] = "keep"
            span["pause_after_ms"] = 60
            span["pause_type"] = "normal"
            span["review_action"] = "force_keep"
            span["review_reason"] = force_reason
            override_count += 1
            force_keep_rows.append(
                {
                    "cluster_id": cluster_id,
                    "span_id": span.get("span_id"),
                    "take_id": take_id,
                    "subtitle_start_uid": span.get("subtitle_start_uid"),
                    "subtitle_end_uid": span.get("subtitle_end_uid"),
                    "subtitle_start_index": span.get("subtitle_start_index"),
                    "subtitle_end_index": span.get("subtitle_end_index"),
                    "mapped_text": span.get("mapped_text"),
                    "confidence": confidence,
                    "reason": force_reason,
                }
            )
        else:
            span["review_action"] = "execute_drop"
            span["review_reason"] = "high confidence duplicate / half sentence / stutter"
            executed_drop_count += 1

    reviewed["decision_mode"] = "conservative_reviewed_deepseek_take_cluster_selection"
    summary = {
        "original_drop_count": original_drop_count,
        "force_keep_drop_count": override_count,
        "final_drop_count": executed_drop_count,
        "force_keep_clusters": sorted(FORCE_KEEP_CLUSTERS),
        "force_keep_rows": force_keep_rows,
    }
    reviewed["conservative_review_summary"] = summary
    return reviewed, summary


def row_start(rows_by_index: dict[int, dict[str, Any]], index: int) -> int:
    return int(rows_by_index[index]["start_us"])


def row_end(rows_by_index: dict[int, dict[str, Any]], index: int) -> int:
    return int(rows_by_index[index]["end_us"])


def build_smart_edl(
    reviewed_decisions: dict[str, Any],
    subtitles: list[dict[str, Any]],
    main_total_duration_us: int,
) -> list[dict[str, Any]]:
    rows_by_index = {int(row["subtitle_index"]): row for row in subtitles}
    spans = sorted(
        reviewed_decisions.get("spans") or [],
        key=lambda item: (int(item["subtitle_start_index"]), int(item["subtitle_end_index"])),
    )
    regions: list[dict[str, Any]] = []
    for position, span in enumerate(spans):
        if span.get("decision") != "keep":
            continue
        start_index = int(span["subtitle_start_index"])
        end_index = int(span["subtitle_end_index"])
        subtitle_start_us = row_start(rows_by_index, start_index)
        subtitle_end_us = row_end(rows_by_index, end_index)
        cut_start_us = max(0, subtitle_start_us - LEAD_GUARD_US)
        cut_end_us = min(main_total_duration_us, subtitle_end_us + TAIL_GUARD_US)

        previous_span = spans[position - 1] if position > 0 else None
        next_span = spans[position + 1] if position + 1 < len(spans) else None
        if previous_span and previous_span.get("decision") == "drop":
            cut_start_us = max(cut_start_us, row_end(rows_by_index, int(previous_span["subtitle_end_index"])))
        if next_span and next_span.get("decision") == "drop":
            cut_end_us = min(cut_end_us, row_start(rows_by_index, int(next_span["subtitle_start_index"])))
        if cut_end_us <= cut_start_us:
            continue

        regions.append(
            {
                "clip_id": f"smart_src_{len(regions) + 1:03d}",
                "subtitle_start_uid": rows_by_index[start_index]["subtitle_uid"],
                "subtitle_end_uid": rows_by_index[end_index]["subtitle_uid"],
                "subtitle_start_index": start_index,
                "subtitle_end_index": end_index,
                "subtitle_start_us": subtitle_start_us,
                "subtitle_end_us": subtitle_end_us,
                "cut_start_us": cut_start_us,
                "cut_end_us": cut_end_us,
                "target_duration_us": cut_end_us - cut_start_us,
                "pause_after_us": clamp_pause_after_us(span),
                "source_span_ids": [span.get("span_id")],
                "source_subtitle_count": end_index - start_index + 1,
                "subtitle_texts": [
                    rows_by_index[index]["subtitle_text"]
                    for index in range(start_index, end_index + 1)
                    if index in rows_by_index
                ],
            }
        )

    merged: list[dict[str, Any]] = []
    for region in regions:
        if not merged:
            merged.append(deepcopy(region))
            continue
        current = merged[-1]
        adjacent_subtitles = int(region["subtitle_start_index"]) == int(current["subtitle_end_index"]) + 1
        gap_us = int(region["cut_start_us"]) - int(current["cut_end_us"])
        if adjacent_subtitles and gap_us <= MERGE_KEEP_GAP_US:
            current["subtitle_end_uid"] = region["subtitle_end_uid"]
            current["subtitle_end_index"] = region["subtitle_end_index"]
            current["subtitle_end_us"] = region["subtitle_end_us"]
            current["cut_end_us"] = max(int(current["cut_end_us"]), int(region["cut_end_us"]))
            current["target_duration_us"] = int(current["cut_end_us"]) - int(current["cut_start_us"])
            current["pause_after_us"] = region["pause_after_us"]
            current["source_span_ids"].extend(region.get("source_span_ids") or [])
            current["source_subtitle_count"] += int(region["source_subtitle_count"])
            current["subtitle_texts"].extend(region.get("subtitle_texts") or [])
        else:
            merged.append(deepcopy(region))

    edl: list[dict[str, Any]] = []
    target_start_us = 0
    for index, region in enumerate(merged, start=1):
        duration_us = int(region["target_duration_us"])
        if duration_us <= 0:
            continue
        clip = deepcopy(region)
        clip["clip_id"] = f"smart_{index:03d}"
        clip["target_start_us"] = target_start_us
        clip["boundary_mode"] = "reviewed_deepseek_keep_span_with_guard"
        edl.append(clip)
        target_start_us += duration_us + int(clip.get("pause_after_us") or 0)
    return edl


def summarize_edl(
    edl: list[dict[str, Any]],
    reviewed: dict[str, Any],
    source_duration_us: int,
) -> dict[str, Any]:
    keep_subtitle_indices: set[int] = set()
    drop_subtitle_indices: set[int] = set()
    for span in reviewed.get("spans") or []:
        target = keep_subtitle_indices if span.get("decision") == "keep" else drop_subtitle_indices
        target.update(range(int(span["subtitle_start_index"]), int(span["subtitle_end_index"]) + 1))
    output_duration_us = 0
    if edl:
        output_duration_us = max(int(row["target_start_us"]) + int(row["target_duration_us"]) for row in edl)
    return {
        "smart_clip_count": len(edl),
        "kept_subtitle_count": len(keep_subtitle_indices),
        "dropped_subtitle_count": len(drop_subtitle_indices),
        "source_duration_us": source_duration_us,
        "output_duration_us": output_duration_us,
        "estimated_deleted_duration_us": max(0, source_duration_us - output_duration_us),
        "first_5_clips": edl[:5],
        "last_5_clips": edl[-5:],
    }


def run_smart_write(args: argparse.Namespace) -> tuple[Path, Path]:
    run_dir = args.runtime / f"aroll_smart_write_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    clusters_path = args.deepseek_run / "take_clusters.json"
    decisions_path = args.deepseek_run / "deepseek_aroll_decisions.json"
    review_path = args.deepseek_run / "human_review_drops.md"
    clusters = read_json(clusters_path)
    decisions = read_json(decisions_path)
    review_text = review_path.read_text("utf-8")

    timeline_id, timeline_name = resolve_timeline_id(args.draft_dir, args.timeline_name)
    timeline_dir = args.draft_dir / "Timelines" / timeline_id
    encrypted_path = timeline_dir / "draft_content.json"
    plain_before = run_dir / "draft_content.before.dec.json"
    plain_modified = run_dir / "draft_content.modified.dec.json"
    encrypted_out = run_dir / "draft_content.modified.enc.json"
    plain_after = run_dir / "draft_content.after.dec.json"
    subtitle_before_path = run_dir / "subtitle_timeline.before.json"
    reviewed_path = run_dir / "reviewed_aroll_decisions.json"
    edl_path = run_dir / "smart_aroll_edl.json"
    report_path = run_dir / "aroll_smart_write_report.json"

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
        fatal_reasons.append("AUDIO_TRACK_PRESENT_UNSUPPORTED_FOR_SMART_WRITE")
    if has_complex_audio:
        fatal_reasons.extend(f"AUDIO:{reason}" for reason in audio_fatals)
    if has_global_filter or has_complex_filter or filter_tracks:
        fatal_reasons.append("FILTER_TRACK_PRESENT_UNSUPPORTED_FOR_SMART_WRITE")
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
            },
        )
        raise RuntimeError(f"SMART_WRITE_PREFLIGHT_BLOCKED:{sorted(set(fatal_reasons))}; report={report_path}")

    backup_paths = backup_draft_files(args.draft_dir, timeline_id, run_dir, root_mirror_required)
    reviewed, review_summary = conservative_review(clusters, decisions, review_text)
    write_json(reviewed_path, reviewed)
    edl = build_smart_edl(reviewed, subtitles, main_total_duration_us)
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
        raise RuntimeError("SMART_REWRITE_PRODUCED_NO_VIDEO_SEGMENTS")
    if not new_text_segments:
        raise RuntimeError("SMART_REWRITE_PRODUCED_NO_TEXT_SEGMENTS")

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
    edl_summary = summarize_edl(edl, reviewed, before_video["total_duration_us"])

    report = {
        "draft_dir": str(args.draft_dir),
        "timeline_id": timeline_id,
        "timeline_name": timeline_name,
        "runtime_dir": str(run_dir),
        "deepseek_run": str(args.deepseek_run),
        "backup_paths": backup_paths,
        "draft_content_before_dec_path": str(plain_before),
        "subtitle_timeline_before_path": str(subtitle_before_path),
        "reviewed_aroll_decisions_path": str(reviewed_path),
        "smart_aroll_edl_path": str(edl_path),
        "draft_content_after_dec_path": str(plain_after),
        "wrote_timeline_draft_content": str(timeline_dir / "draft_content.json") in target_writes,
        "wrote_timeline_template_2_tmp": str(timeline_dir / "template-2.tmp") in target_writes,
        "wrote_root_draft_content": str(args.draft_dir / "draft_content.json") in target_writes,
        "wrote_root_template_2_tmp": str(args.draft_dir / "template-2.tmp") in target_writes,
        "video_track_before": before_video,
        "video_track_after": after_video,
        "text_track_before": before_text,
        "text_track_after": after_text,
        "conservative_review_summary": review_summary,
        "edl_summary": edl_summary,
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
    parser = argparse.ArgumentParser(description="Write conservative DeepSeek Smart A-Roll into a sacrificial Jianying draft.")
    parser.add_argument("--draft-dir", type=Path, required=True)
    parser.add_argument("--deepseek-run", type=Path, default=DEFAULT_DEEPSEEK_RUN)
    parser.add_argument("--timeline-name", default="")
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    args = parser.parse_args()

    run_dir, report_path = run_smart_write(args)
    report = read_json(report_path)
    review = report.get("conservative_review_summary") or {}
    edl = report.get("edl_summary") or {}
    print("status=ok" if not report.get("fatal_reasons") else "status=blocked")
    print(f"runtime={run_dir}")
    print(f"report={report_path}")
    print(f"reviewed_aroll_decisions={report.get('reviewed_aroll_decisions_path')}")
    print(f"smart_aroll_edl={report.get('smart_aroll_edl_path')}")
    print(f"original_drops={review.get('original_drop_count')}")
    print(f"force_keep_drops={review.get('force_keep_drop_count')}")
    print(f"final_drops={review.get('final_drop_count')}")
    print(f"smart_clips={edl.get('smart_clip_count')}")
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
