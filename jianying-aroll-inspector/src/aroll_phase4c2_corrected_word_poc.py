from __future__ import annotations

import argparse
import json
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aroll_contract_check import timeline_id_checks_after
from aroll_decision_merger import decision_maps, merge_decisions
from aroll_inspect import (
    DEFAULT_RUNTIME,
    build_report as inspect_build_report,
    inspect_audio_tracks,
    inspect_filter_tracks,
    inspect_video_tracks,
    segment_end,
    segment_start,
    subtitle_timeline,
    total_target_duration,
)
from aroll_poc_writer import backup_draft_files, get_track, split_video_segments_for_edl, write_encrypted_to_targets
from aroll_safe_gap_cutter import (
    REPEAT_BOUNDARY_LEAD_PAD_US,
    REPEAT_BOUNDARY_TAIL_PAD_US,
    SafeGapCutter,
)
from aroll_safe_gap_cutter import build_safe_gap_plan
from aroll_subtitle_fragment_grouper import group_subtitle_fragments
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


DEFAULT_DRAFT_DIR = Path(r"D:\JianyingPro Drafts\6月14日")
DEFAULT_BACKUP_DIR = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_roughcut_write_20260614_111435\backup")
DEFAULT_V5_DIR = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_corrective_v5_20260614_163617")
DEFAULT_REPEAT_CLUSTERS = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4_diagnostics_20260614_171206\repeat_clusters.json")
DEFAULT_PHASE4B_DIR = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4b_word_edl_dryrun_20260614_172532")
SOURCE_RANGE_START_US = 113_447_000
SOURCE_RANGE_END_US = 150_797_000
SOURCE_DURATION_US = 308_800_000
SPEECH_LEAD_PAD_US = 90_000
SPEECH_TAIL_PAD_US = 120_000


def safe_copy(src: Path, dst: Path) -> None:
    if not src.exists():
        raise RuntimeError(f"RESTORE_SOURCE_MISSING:{src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())


def restore_original_backup(draft_dir: Path, timeline_id: str, backup_dir: Path) -> list[str]:
    timeline_dir = draft_dir / "Timelines" / timeline_id
    pairs = [
        (backup_dir / "timeline" / "draft_content.json", timeline_dir / "draft_content.json"),
        (backup_dir / "timeline" / "template-2.tmp", timeline_dir / "template-2.tmp"),
        (backup_dir / "root" / "draft_content.json", draft_dir / "draft_content.json"),
        (backup_dir / "root" / "template-2.tmp", draft_dir / "template-2.tmp"),
    ]
    restored = []
    root = draft_dir.resolve()
    for src, dst in pairs:
        if not dst.parent.resolve().is_relative_to(root):
            raise RuntimeError(f"RESTORE_TARGET_OUTSIDE_DRAFT:{dst}")
        safe_copy(src, dst)
        restored.append(str(dst))
    return restored


def run_post_inspect(draft_dir: Path, run_dir: Path, jy_draftc: Path) -> dict[str, Any]:
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


def set_json_text_payload(value: Any, new_text: str) -> Any:
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return value
        if isinstance(parsed, dict):
            parsed["text"] = new_text
            styles = parsed.get("styles")
            if isinstance(styles, list) and styles:
                first = deepcopy(styles[0])
                first["range"] = [0, len(new_text)]
                parsed["styles"] = [first]
            return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        return value
    if isinstance(value, dict):
        cloned = deepcopy(value)
        cloned["text"] = new_text
        styles = cloned.get("styles")
        if isinstance(styles, list) and styles:
            first = deepcopy(styles[0])
            first["range"] = [0, len(new_text)]
            cloned["styles"] = [first]
        return cloned
    return value


def clone_text_material(material: dict[str, Any], new_text: str) -> dict[str, Any]:
    cloned = deepcopy(material)
    cloned["id"] = guid()
    cloned["recognize_text"] = new_text
    cloned["content"] = set_json_text_payload(cloned.get("content"), new_text)
    cloned["base_content"] = set_json_text_payload(cloned.get("base_content"), new_text)
    cloned["words"] = {}
    cloned["current_words"] = {}
    cloned.pop("subtitle_keywords", None)
    return cloned


def selected_rows(
    subtitles: list[dict[str, Any]],
    drops: dict[int, dict[str, Any]],
    micros: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for row in subtitles:
        idx = int(row["subtitle_index"])
        start = int(row["start_us"])
        end = int(row["end_us"])
        if start < SOURCE_RANGE_START_US or end > SOURCE_RANGE_END_US:
            continue
        if idx in drops:
            continue
        text = str(row.get("subtitle_text") or "")
        if idx in micros:
            text = str(micros[idx].get("kept_text") or text)
        rows.append(
            {
                "subtitle_uid": row["subtitle_uid"],
                "subtitle_index": idx,
                "source_text": row.get("subtitle_text") or "",
                "text": text,
                "source_start_us": start,
                "source_end_us": end,
                "reason": "micro_cleanup" if idx in micros else "normal",
                "text_segment_id": row.get("text_segment_id"),
                "text_material_id": row.get("text_material_id"),
            }
        )
    return rows


def build_video_clips(
    kept_rows: list[dict[str, Any]],
    drops: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not kept_rows:
        raise RuntimeError("NO_KEPT_ROWS_IN_SELECTED_RANGE")
    kept_by_idx = {int(row["subtitle_index"]): row for row in kept_rows}
    selected_indices = list(range(
        min(int(row["subtitle_index"]) for row in kept_rows + [{"subtitle_index": min(drops) if drops else 999999}]),
        max(int(row["subtitle_index"]) for row in kept_rows + [{"subtitle_index": max(drops) if drops else 0}]) + 1,
    ))
    selected_indices = [idx for idx in selected_indices if SOURCE_RANGE_START_US <= int((kept_by_idx.get(idx) or {}).get("source_start_us", SOURCE_RANGE_START_US)) <= SOURCE_RANGE_END_US or idx in drops]

    runs: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for idx in range(42, 57):
        if idx in kept_by_idx:
            if current and idx == int(current[-1]["subtitle_index"]) + 1:
                current.append(kept_by_idx[idx])
            else:
                if current:
                    runs.append(current)
                current = [kept_by_idx[idx]]
        else:
            if current:
                runs.append(current)
                current = []
    if current:
        runs.append(current)

    clips: list[dict[str, Any]] = []
    boundaries: list[dict[str, Any]] = []
    target_start = 0
    for clip_idx, run in enumerate(runs, start=1):
        first = run[0]
        last = run[-1]
        prev_idx = int(first["subtitle_index"]) - 1
        next_idx = int(last["subtitle_index"]) + 1
        lead = REPEAT_BOUNDARY_LEAD_PAD_US if prev_idx in drops else SPEECH_LEAD_PAD_US
        tail = REPEAT_BOUNDARY_TAIL_PAD_US if next_idx in drops else SPEECH_TAIL_PAD_US
        cut_start = max(0, int(first["source_start_us"]) - lead)
        cut_end = min(SOURCE_DURATION_US, int(last["source_end_us"]) + tail)
        duration = cut_end - cut_start
        if duration <= 0:
            raise RuntimeError(f"CLIP_NON_POSITIVE:{clip_idx}")
        clips.append(
            {
                "clip_id": f"c2_{clip_idx:03d}",
                "subtitle_start_uid": first["subtitle_uid"],
                "subtitle_end_uid": last["subtitle_uid"],
                "subtitle_start_index": int(first["subtitle_index"]),
                "subtitle_end_index": int(last["subtitle_index"]),
                "source_start_us": cut_start,
                "source_end_us": cut_end,
                "cut_start_us": cut_start,
                "cut_end_us": cut_end,
                "target_start_us": target_start,
                "target_duration_us": duration,
                "source_reason": "phrase_block_with_drop_boundaries",
                "subtitle_texts": [row["text"] for row in run],
            }
        )
        target_start += duration

    for prev, curr in zip(clips, clips[1:]):
        dropped_indices = [
            idx for idx in range(int(prev["subtitle_end_index"]) + 1, int(curr["subtitle_start_index"]))
            if idx in drops
        ]
        if not dropped_indices:
            continue
        drop_start = min(int(drops[idx].get("subtitle_index") or idx) for idx in dropped_indices)
        drop_end = max(int(drops[idx].get("subtitle_index") or idx) for idx in dropped_indices)
        # Source subtitle table uses contiguous indices; actual end times come
        # from clip boundary context to avoid importing another map.
        boundaries.append(
            {
                "gap_id": f"safe_gap_{len(boundaries) + 1:03d}",
                "boundary_type": "repeat_drop_boundary",
                "dropped_indices": dropped_indices,
                "left_clip_id": prev["clip_id"],
                "right_clip_id": curr["clip_id"],
                "cut_start_us": int(prev["cut_end_us"]),
                "cut_end_us": int(curr["cut_start_us"]),
                "silence_check_start_us": int(prev["cut_end_us"]),
                "silence_check_end_us": int(curr["cut_start_us"]),
                "left_text": " / ".join(prev.get("subtitle_texts") or []),
                "right_text": " / ".join(curr.get("subtitle_texts") or []),
                "reason": "dropped repeated take boundary",
                "drop_start_index": drop_start,
                "drop_end_index": drop_end,
            }
        )
    return clips, boundaries


def refine_boundaries_with_subtitles(boundaries: list[dict[str, Any]], subtitles: list[dict[str, Any]]) -> None:
    by_index = {int(row["subtitle_index"]): row for row in subtitles}
    for row in boundaries:
        drop_end_index = int(row["drop_end_index"])
        right_index = int(row["drop_end_index"]) + 1
        if drop_end_index in by_index and right_index in by_index:
            dropped_end = int(by_index[drop_end_index]["end_us"])
            kept_start = int(by_index[right_index]["start_us"])
            row["silence_check_start_us"] = dropped_end
            row["silence_check_end_us"] = kept_start


def build_subtitle_segments(
    data: dict[str, Any],
    text_track: dict[str, Any],
    original_subtitles: list[dict[str, Any]],
    grouped: list[dict[str, Any]],
    clips: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    materials = (data.get("materials") or {}).setdefault("texts", [])
    material_by_id = {str(item.get("id") or ""): item for item in materials}
    segment_by_uid = {
        str(row["subtitle_uid"]): row.get("segment") or {}
        for row in original_subtitles
    }
    material_id_by_uid = {
        str(row["subtitle_uid"]): str(row.get("text_material_id") or "")
        for row in original_subtitles
    }
    clips_sorted = sorted(clips, key=lambda row: int(row["cut_start_us"]))
    new_segments: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for item in grouped:
        source_start = int(item["source_start_us"])
        source_end = int(item["source_end_us"])
        clip = next((row for row in clips_sorted if int(row["cut_start_us"]) <= source_start and source_end <= int(row["cut_end_us"])), None)
        if clip is None:
            continue
        uid = str((item.get("source_subtitle_uids") or [""])[0])
        template_segment = segment_by_uid.get(uid)
        old_material = material_by_id.get(material_id_by_uid.get(uid, ""))
        if not template_segment or not old_material:
            continue
        new_segment = deepcopy(template_segment)
        new_segment["id"] = guid()
        target_start = int(clip["target_start_us"]) + source_start - int(clip["cut_start_us"])
        target_duration = source_end - source_start
        target_timerange = deepcopy(new_segment.get("target_timerange") or {})
        target_timerange["start"] = target_start
        target_timerange["duration"] = target_duration
        new_segment["target_timerange"] = target_timerange
        cloned_material = clone_text_material(old_material, str(item["fragment_text"]))
        materials.append(cloned_material)
        new_segment["material_id"] = cloned_material["id"]
        new_segments.append(new_segment)
        rows.append({
            "fragment_id": item["fragment_id"],
            "text": item["fragment_text"],
            "source_subtitle_uids": item["source_subtitle_uids"],
            "target_start_us": target_start,
            "target_duration_us": target_duration,
        })
    new_segments.sort(key=segment_start)
    return new_segments, {"rows": rows, "material_clone_count": len(rows)}


def post_merge_repeat_check(grouped: list[dict[str, Any]]) -> dict[str, Any]:
    texts = [str(row.get("fragment_text") or "") for row in grouped]
    joined = "\n".join(texts)
    residuals = []
    checks = {
        "near_duplicate": 0,
        "pronoun_variant_duplicate": 0,
        "prefix_fragment": 0,
        "same_subtitle_repeated_phrase": 0,
    }
    patterns = {
        "same_subtitle_repeated_phrase": ["评论区评论区", "给给老子", "重新上重新上", "你跪在地上你跪在地上"],
        "pronoun_variant_duplicate": ["你可以嘲笑她们虚伪"],
        "prefix_fragment": ["但在金融市场的角"],
    }
    for category, pats in patterns.items():
        for pat in pats:
            if pat in joined:
                checks[category] += 1
                residuals.append({"category": category, "pattern": pat})
    if "你可以" in texts and "嘲笑他们虚伪" in texts:
        residuals.append({"category": "subtitle_fragment_split", "pattern": "你可以 / 嘲笑他们虚伪"})
    return {
        "counts": checks,
        "residuals": residuals,
        "pass": not residuals,
        "final_texts": texts,
    }


def write_markdown_reports(run_dir: Path, merge_report: str, unsafe: list[dict[str, Any]], group_report: dict[str, Any], final_texts: list[str]) -> None:
    (run_dir / "decision_merge_report.md").write_text(merge_report, "utf-8")
    unsafe_lines = ["# Unsafe Gap Rejected Report", ""]
    if not unsafe:
        unsafe_lines.append("No high-risk gap cuts rejected in the selected PoC range.")
    for row in unsafe:
        unsafe_lines.append(f"- {row.get('gap_id')}: {row.get('left_text')} -> {row.get('right_text')} | reason={row.get('reason')}")
    (run_dir / "unsafe_gap_rejected_report.md").write_text("\n".join(unsafe_lines) + "\n", "utf-8")
    group_lines = [
        "# Subtitle Fragment Group Report",
        "",
        f"- 原 word-level subtitle fragments 数：{group_report.get('input_fragment_count')}",
        f"- 合并后字幕数：{group_report.get('grouped_subtitle_count')}",
        f"- 单字字幕数量：{group_report.get('single_char_subtitle_count')}",
        f"- 是否仍存在「你可以 / 嘲笑他们虚伪」拆分：{group_report.get('has_split_ni_keyi_xiao_tamen')}",
        "",
        "## Final subtitles",
    ]
    group_lines.extend(f"- {text}" for text in final_texts)
    (run_dir / "subtitle_fragment_group_report.md").write_text("\n".join(group_lines) + "\n", "utf-8")
    focus = [
        "# Phase 4C-2 Human Review Focus",
        "",
        "1. 「你可以嘲笑她们虚伪」是否被删",
        "2. 是否只剩自然的「你可以嘲笑他们虚伪」",
        "3. 两个重复句之间的废气口是否被切掉",
        "4. 有没有切掉「你可以嘲笑他们虚伪」的字头/尾音",
        "5. 字幕是否合并自然，不再碎成「你可以 / 嘲笑他们虚伪」",
        "6. 是否有跳切感",
        "",
        "## Final subtitles",
    ]
    focus.extend(f"- {text}" for text in final_texts)
    (run_dir / "human_review_focus.md").write_text("\n".join(focus) + "\n", "utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4C-2 corrected word-level local PoC writer.")
    parser.add_argument("--draft-dir", type=Path, default=DEFAULT_DRAFT_DIR)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--v5-dir", type=Path, default=DEFAULT_V5_DIR)
    parser.add_argument("--repeat-clusters", type=Path, default=DEFAULT_REPEAT_CLUSTERS)
    parser.add_argument("--phase4b-dir", type=Path, default=DEFAULT_PHASE4B_DIR)
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    args = parser.parse_args()

    run_dir = args.runtime / f"aroll_phase4c2_corrected_word_poc_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    timeline_id, _timeline_name = resolve_timeline_id(args.draft_dir, "")
    restored = restore_original_backup(args.draft_dir, timeline_id, args.backup_dir)
    restore_inspect = run_post_inspect(args.draft_dir, run_dir / "restore_check", args.jy_draftc)
    if int(restore_inspect.get("duration_us") or 0) < 300_000_000 or int(restore_inspect.get("subtitle_segment_count") or 0) != 115:
        raise RuntimeError(f"RESTORE_FAILED:{restore_inspect}")

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
    audio_tracks, has_independent_audio, has_complex_audio, audio_fatals = inspect_audio_tracks(data)
    main_total = int((selected_main or {}).get("total_target_duration_us") or 0)
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

    rows = selected_rows(subtitles, drops, micros)
    grouped, group_report = group_subtitle_fragments(rows)
    repeat_check = post_merge_repeat_check(grouped)
    write_json(run_dir / "post_merge_repeat_check.json", repeat_check)
    if not repeat_check["pass"]:
        raise RuntimeError(f"POST_MERGE_REPEAT_CHECK_FAILED:{repeat_check['residuals']}")

    clips, boundaries = build_video_clips(rows, drops)
    refine_boundaries_with_subtitles(boundaries, subtitles)
    material_path = str(((selected_main.get("materials") or [{}])[0]).get("material_path") or "")
    cutter = SafeGapCutter(material_path, run_dir / "audio_vad")
    phase4b_report = read_json(args.phase4b_dir / "phase4b_dryrun_report.json")
    accepted_gaps, rejected_gaps, gap_summary = build_safe_gap_plan(cutter, boundaries, int(phase4b_report.get("word_gap_cut_count") or 0))
    write_json(run_dir / "safe_gap_cut_plan.json", {"summary": gap_summary, "accepted": accepted_gaps})
    if rejected_gaps:
        raise RuntimeError(f"SAFE_GAP_REJECTED:{rejected_gaps}")

    # Rebase clip target starts after final acceptance.
    target_start = 0
    for clip in clips:
        clip["target_start_us"] = target_start
        clip["target_duration_us"] = int(clip["cut_end_us"]) - int(clip["cut_start_us"])
        target_start += int(clip["target_duration_us"])
    for group in grouped:
        clip = next(row for row in clips if int(row["cut_start_us"]) <= int(group["source_start_us"]) and int(group["source_end_us"]) <= int(row["cut_end_us"]))
        group["target_start_us"] = int(clip["target_start_us"]) + int(group["source_start_us"]) - int(clip["cut_start_us"])
        group["target_duration_us"] = int(group["source_end_us"]) - int(group["source_start_us"])
    group_report["final_subtitle_texts"] = [group["fragment_text"] for group in grouped]
    write_json(run_dir / "grouped_subtitle_plan.json", grouped)
    write_json(run_dir / "selected_word_edl_corrected.json", clips)
    write_json(run_dir / "selected_subtitle_plan_corrected.json", grouped)

    backup_paths = backup_draft_files(args.draft_dir, timeline_id, run_dir, root_mirror_required)
    main_track = get_track(data, str(selected_main["track_id"]))
    text_track = get_track(data, str(selected_text_track["track_id"]))
    old_video_segments = deepcopy(main_track.get("segments") or [])
    old_text_segments = deepcopy(text_track.get("segments") or [])
    new_video_segments, video_split_rows = split_video_segments_for_edl(old_video_segments, clips)

    materials = (data.get("materials") or {}).setdefault("texts", [])
    material_by_id = {str(item.get("id") or ""): item for item in materials}
    sub_by_uid = {str(row["subtitle_uid"]): row for row in subtitles}
    new_text_segments = []
    text_rows = []
    for group in grouped:
        uid = str((group.get("source_subtitle_uids") or [""])[0])
        source_row = sub_by_uid[uid]
        source_segment = source_row["segment"]
        source_material = material_by_id[str(source_row["text_material_id"])]
        new_segment = deepcopy(source_segment)
        new_segment["id"] = guid()
        target_timerange = deepcopy(new_segment.get("target_timerange") or {})
        target_timerange["start"] = int(group["target_start_us"])
        target_timerange["duration"] = int(group["target_duration_us"])
        new_segment["target_timerange"] = target_timerange
        cloned_material = clone_text_material(source_material, str(group["fragment_text"]))
        materials.append(cloned_material)
        new_segment["material_id"] = cloned_material["id"]
        new_text_segments.append(new_segment)
        text_rows.append({"text": group["fragment_text"], "target_start_us": group["target_start_us"], "target_duration_us": group["target_duration_us"]})
    new_text_segments.sort(key=segment_start)

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
    post_inspect = run_post_inspect(args.draft_dir, run_dir, args.jy_draftc)
    write_json(run_dir / "post_inspect_summary.json", post_inspect)
    write_markdown_reports(run_dir, merge_report, rejected_gaps, group_report, group_report["final_subtitle_texts"])

    write_report = {
        "draft_dir": str(args.draft_dir),
        "runtime_dir": str(run_dir),
        "restored_paths": restored,
        "backup_paths": backup_paths,
        "source_range_s": [SOURCE_RANGE_START_US / 1_000_000, SOURCE_RANGE_END_US / 1_000_000],
        "final_duration_us": data["duration"],
        "video_segments": len(new_video_segments),
        "subtitle_segments": len(new_text_segments),
        "video_split_rows": video_split_rows,
        "subtitle_rows": text_rows,
        "target_writes": {str(path): str(path) in target_writes for path in targets},
        "timeline_id_checks_after": timeline_checks,
        "root_mirror_required": root_mirror_required,
        "root_mirror_matches_after": root_mirrors_timeline_id(args.draft_dir, args.jy_draftc, run_dir, timeline_id),
        "merge_summary": merge_summary,
        "safe_gap_summary": gap_summary,
        "group_report": group_report,
        "post_merge_repeat_check": repeat_check,
        "fatal_reasons": sorted(set(check_fatals)),
        "warnings": sorted(set(video_warnings)),
        "project_json_modified": False,
        "timeline_layout_modified": False,
        "audio_filter_tracks_modified": False,
        "deepseek_called": False,
    }
    write_json(run_dir / "write_report.json", write_report)
    print("status=ok")
    print(f"runtime={run_dir}")
    print(f"report={run_dir / 'write_report.json'}")
    print(f"duration_s={round(data['duration'] / 1_000_000, 3)}")
    print(f"video_segments={len(new_video_segments)}")
    print(f"subtitle_segments={len(new_text_segments)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
