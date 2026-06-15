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
from aroll_poc_writer import (
    backup_draft_files,
    get_track,
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
    guid,
    read_json,
    resolve_timeline_id,
    root_mirrors_timeline_id,
    write_json,
)


DEFAULT_DRAFT_DIR = Path(r"D:\JianyingPro Drafts\6月14日")
DEFAULT_BACKUP_DIR = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_roughcut_write_20260614_111435\backup")
DEFAULT_PHASE4B_DIR = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4b_word_edl_dryrun_20260614_172532")
DEFAULT_SUBTITLES = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_inspect_20260614_111146\subtitle_timeline.json")
PHASE4C_RUNTIME_PREFIX = "aroll_phase4c_word_write_poc"
SOURCE_DURATION_US = 308_800_000


def safe_copy(src: Path, dst: Path) -> None:
    if not src.exists():
        raise RuntimeError(f"RESTORE_SOURCE_MISSING:{src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def restore_original_backup(draft_dir: Path, timeline_id: str, backup_dir: Path) -> list[str]:
    timeline_dir = draft_dir / "Timelines" / timeline_id
    targets = [
        (backup_dir / "timeline" / "draft_content.json", timeline_dir / "draft_content.json"),
        (backup_dir / "timeline" / "template-2.tmp", timeline_dir / "template-2.tmp"),
        (backup_dir / "root" / "draft_content.json", draft_dir / "draft_content.json"),
        (backup_dir / "root" / "template-2.tmp", draft_dir / "template-2.tmp"),
    ]
    draft_resolved = draft_dir.resolve()
    restored: list[str] = []
    for src, dst in targets:
        if not dst.parent.resolve().is_relative_to(draft_resolved):
            raise RuntimeError(f"RESTORE_TARGET_OUTSIDE_DRAFT:{dst}")
        safe_copy(src, dst)
        restored.append(str(dst))
    return restored


def archive_existing_candidate(path: Path, archive_root: Path) -> str:
    if not path.exists():
        return ""
    archive_root.mkdir(parents=True, exist_ok=True)
    archived = archive_root / f"{path.name}_archived_{time.strftime('%Y%m%d_%H%M%S')}"
    shutil.move(str(path), str(archived))
    return str(archived)


def copy_candidate_draft(source: Path, target: Path, archive_root: Path) -> str:
    archived = archive_existing_candidate(target, archive_root)
    shutil.copytree(source, target)
    return archived


def load_inputs(phase4b_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    edl = read_json(phase4b_dir / "word_level_aroll_edl.json")
    subtitle_plan = read_json(phase4b_dir / "word_level_subtitle_plan.json")
    gap_plan = read_json(phase4b_dir / "word_gap_cut_plan.json")
    dry_report = read_json(phase4b_dir / "phase4b_dryrun_report.json")
    return edl, subtitle_plan, gap_plan, dry_report


def source_overlap(row: dict[str, Any], start_us: int, end_us: int) -> bool:
    row_start = int(row.get("source_start_us") or row.get("cut_start_us") or 0)
    row_end = int(row.get("source_end_us") or row.get("cut_end_us") or 0)
    return row_end > start_us and row_start < end_us


def rebase_selected_edl(candidate: str, selected: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[tuple[int, str, str], int]]:
    rebased: list[dict[str, Any]] = []
    target_start = 0
    target_map: dict[tuple[int, str, str], int] = {}
    ordered = sorted(selected, key=lambda row: (int(row.get("target_start_us") or 0), int(row.get("source_start_us") or 0)))
    for index, row in enumerate(ordered, start=1):
        source_start = int(row.get("source_start_us") or 0)
        source_end = int(row.get("source_end_us") or 0)
        duration = source_end - source_start
        if duration <= 0:
            raise RuntimeError(f"{candidate}:SELECTED_CLIP_NON_POSITIVE_DURATION:{row.get('clip_id')}")
        cloned = deepcopy(row)
        old_key = (
            int(row.get("target_start_us") or 0),
            str(row.get("word_start_id") or ""),
            str(row.get("word_end_id") or ""),
        )
        cloned["original_clip_id"] = row.get("clip_id")
        cloned["clip_id"] = f"{candidate}_{index:04d}"
        cloned["cut_start_us"] = source_start
        cloned["cut_end_us"] = source_end
        cloned["target_start_us"] = target_start
        cloned["target_duration_us"] = duration
        cloned["candidate"] = candidate
        rebased.append(cloned)
        target_map[old_key] = target_start
        target_start += duration
    return rebased, target_map


def select_plan_for_edl(
    subtitle_plan: list[dict[str, Any]],
    target_map: dict[tuple[int, str, str], int],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in subtitle_plan:
        key = (
            int(row.get("target_start_us") or 0),
            str(row.get("word_start_id") or ""),
            str(row.get("word_end_id") or ""),
        )
        if key not in target_map:
            continue
        cloned = deepcopy(row)
        cloned["original_target_start_us"] = int(row.get("target_start_us") or 0)
        cloned["target_start_us"] = target_map[key]
        selected.append(cloned)
    selected.sort(key=lambda row: int(row.get("target_start_us") or 0))
    return selected


def candidate_ranges(original_subtitles: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    pronoun_rows = [
        row for row in original_subtitles
        if str(row.get("subtitle_text") or "") in {"你可以嘲笑她们虚伪", "你可以嘲笑他们虚伪"}
    ]
    if len(pronoun_rows) < 2:
        raise RuntimeError("CANDIDATE_B_PRONOUN_ROWS_NOT_FOUND")
    b_start = max(0, min(int(row["start_us"]) for row in pronoun_rows) - 15_000_000)
    b_end = min(SOURCE_DURATION_US, max(int(row["end_us"]) for row in pronoun_rows) + 15_000_000)
    return {
        "candidate_A": {
            "source_start_us": 0,
            "source_end_us": 75_000_000,
            "purpose": "opening dense semantic region",
        },
        "candidate_B": {
            "source_start_us": b_start,
            "source_end_us": b_end,
            "purpose": "pronoun variant duplicate region",
        },
    }


def select_candidate_payload(
    candidate: str,
    source_start_us: int,
    source_end_us: int,
    full_edl: list[dict[str, Any]],
    full_subtitle_plan: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected = [row for row in full_edl if source_overlap(row, source_start_us, source_end_us)]
    if not selected:
        raise RuntimeError(f"{candidate}:NO_WORD_EDL_SELECTED")
    rebased_edl, target_map = rebase_selected_edl(candidate, selected)
    selected_plan = select_plan_for_edl(full_subtitle_plan, target_map)
    if not selected_plan:
        raise RuntimeError(f"{candidate}:NO_SUBTITLE_PLAN_SELECTED")
    return rebased_edl, selected_plan


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


def clone_text_material(material: dict[str, Any], fragment: dict[str, Any], word_rows: list[dict[str, Any]]) -> dict[str, Any]:
    new_text = str(fragment.get("fragment_text") or "")
    cloned = deepcopy(material)
    cloned["id"] = guid()
    cloned["recognize_text"] = new_text
    cloned["content"] = set_json_text_payload(cloned.get("content"), new_text)
    cloned["base_content"] = set_json_text_payload(cloned.get("base_content"), new_text)
    cloned.pop("subtitle_keywords", None)
    cloned["current_words"] = {}
    words_payload = {
        "start_time": [],
        "end_time": [],
        "text": [],
    }
    source_start = int(fragment.get("source_start_us") or 0)
    for word in word_rows:
        words_payload["start_time"].append(max(0, int(round((int(word.get("start_us") or 0) - source_start) / 1000))))
        words_payload["end_time"].append(max(0, int(round((int(word.get("end_us") or 0) - source_start) / 1000))))
        words_payload["text"].append(str(word.get("word_text") or ""))
    cloned["words"] = words_payload
    return cloned


def word_rows_for_fragment(word_by_id: dict[str, dict[str, Any]], fragment: dict[str, Any]) -> list[dict[str, Any]]:
    start_id = str(fragment.get("word_start_id") or "")
    end_id = str(fragment.get("word_end_id") or "")
    if not start_id or not end_id:
        return []
    try:
        start_no = int(start_id.split("_")[-1])
        end_no = int(end_id.split("_")[-1])
    except Exception:
        return []
    rows = []
    for number in range(start_no, end_no + 1):
        row = word_by_id.get(f"w_{number:06d}")
        if row:
            rows.append(row)
    return rows


def rewrite_word_level_text_segments(
    data: dict[str, Any],
    old_text_segments: list[dict[str, Any]],
    selected_plan: list[dict[str, Any]],
    word_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    text_materials = (data.get("materials") or {}).setdefault("texts", [])
    text_by_id = {str(material.get("id") or ""): material for material in text_materials}
    segment_by_subtitle_uid: dict[str, dict[str, Any]] = {}
    for segment in old_text_segments:
        material_id = str(segment.get("material_id") or "")
        material = text_by_id.get(material_id) or {}
        text = str(material.get("recognize_text") or "")
        start = segment_start(segment)
        # segment ids can change after earlier writes, so source uid from the
        # original plan is mapped later through stable text+start fallback.
        key = f"{text}|{start}"
        segment_by_subtitle_uid[key] = segment

    word_by_id = {str(row.get("word_id") or ""): row for row in word_rows}
    rewritten: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    missing_source_segments: list[dict[str, Any]] = []
    material_clones = 0

    for fragment in selected_plan:
        source_text = str(fragment.get("source_text") or "")
        source_start = int(fragment.get("source_start_us") or 0)
        source_uid = str(fragment.get("source_subtitle_uid") or "")
        source_segment = None
        for segment in old_text_segments:
            start = segment_start(segment)
            end = segment_end(segment)
            material = text_by_id.get(str(segment.get("material_id") or ""), {})
            if start <= source_start < end and str(material.get("recognize_text") or "") == source_text:
                source_segment = segment
                break
        if source_segment is None:
            for segment in old_text_segments:
                material = text_by_id.get(str(segment.get("material_id") or ""), {})
                if str(material.get("recognize_text") or "") == source_text:
                    source_segment = segment
                    break
        if source_segment is None:
            missing_source_segments.append({"source_subtitle_uid": source_uid, "source_text": source_text, "source_start_us": source_start})
            continue

        old_material = text_by_id.get(str(source_segment.get("material_id") or ""))
        if not old_material:
            missing_source_segments.append({"source_subtitle_uid": source_uid, "source_text": source_text, "reason": "MATERIAL_NOT_FOUND"})
            continue

        new_segment = deepcopy(source_segment)
        new_segment["id"] = guid()
        target_timerange = deepcopy(new_segment.get("target_timerange") or {})
        target_timerange["start"] = int(fragment.get("target_start_us") or 0)
        target_timerange["duration"] = int(fragment.get("target_duration_us") or 0)
        new_segment["target_timerange"] = target_timerange

        fragment_words = word_rows_for_fragment(word_by_id, fragment)
        cloned_material = clone_text_material(old_material, fragment, fragment_words)
        text_materials.append(cloned_material)
        text_by_id[str(cloned_material["id"])] = cloned_material
        new_segment["material_id"] = cloned_material["id"]
        rewritten.append(new_segment)
        material_clones += 1
        rows.append(
            {
                "fragment_id": fragment.get("fragment_id"),
                "source_subtitle_uid": source_uid,
                "source_text": source_text,
                "fragment_text": fragment.get("fragment_text"),
                "reason": fragment.get("reason"),
                "target_start_us": target_timerange["start"],
                "target_duration_us": target_timerange["duration"],
                "new_text_segment_id": new_segment["id"],
                "new_text_material_id": cloned_material["id"],
            }
        )

    rewritten.sort(key=segment_start)
    return rewritten, {
        "material_clone_count": material_clones,
        "rows": rows,
        "missing_source_segments": missing_source_segments,
    }


def validate_selected_edl(edl: list[dict[str, Any]]) -> list[str]:
    fatal: list[str] = []
    for row in edl:
        source_start = int(row.get("source_start_us") or row.get("cut_start_us") or 0)
        source_end = int(row.get("source_end_us") or row.get("cut_end_us") or 0)
        duration = int(row.get("target_duration_us") or 0)
        if duration <= 0:
            fatal.append(f"NON_POSITIVE_DURATION:{row.get('clip_id')}")
        if source_start < 0 or source_end > SOURCE_DURATION_US or source_end <= source_start:
            fatal.append(f"SOURCE_RANGE_UNSAFE:{row.get('clip_id')}")
    for prev, curr in zip(edl, edl[1:]):
        prev_end = int(prev["target_start_us"]) + int(prev["target_duration_us"])
        if int(curr["target_start_us"]) < prev_end:
            fatal.append(f"TARGET_OVERLAP:{prev.get('clip_id')}->{curr.get('clip_id')}")
    return fatal


def make_human_focus(candidate: str, selected_plan: list[dict[str, Any]], report: dict[str, Any]) -> str:
    texts = [str(row.get("fragment_text") or "") for row in selected_plan]
    lines = [f"# {candidate} Human Review Focus", ""]
    if candidate == "candidate_A":
        lines.extend(
            [
                "1. 开头是否明显更紧",
                "2. 是否切字/断尾音",
                "3. 字幕 fragment 是否显示正常",
                "4. 人家年少时候上下文是否顺",
                "5. 你跪在地上叫大佬是否干净",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "1. 你可以嘲笑她们虚伪是否被删",
                "2. 是否只剩你可以嘲笑他们虚伪",
                "3. 前后语义是否顺",
                "4. 是否切字/断尾音",
                "",
            ]
        )
    lines.extend(["## Final subtitle fragments", ""])
    for text in texts:
        lines.append(f"- {text}")
    lines.extend(["", "## Write summary", ""])
    lines.append(json.dumps(report.get("summary", {}), ensure_ascii=False, indent=2))
    return "\n".join(lines) + "\n"


def run_post_inspect(draft_dir: Path, run_dir: Path, jy_draftc: Path) -> dict[str, Any]:
    inspect_runtime = run_dir / "inspect_runtime"
    args = SimpleNamespace(
        draft_dir=draft_dir,
        timeline_name="",
        main_video_track_index=-1,
        main_material_path="",
        jy_draftc=jy_draftc,
        runtime=inspect_runtime,
    )
    inspect_dir, report_path, subtitle_path = inspect_build_report(args)
    report = read_json(report_path)
    selected_main = report.get("selected_main_video_track") or {}
    text_tracks = report.get("text_tracks") or []
    selected_text = next((row for row in text_tracks if row.get("selected_as_subtitle_track")), {})
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


def write_candidate(
    candidate: str,
    draft_dir: Path,
    candidate_dir: Path,
    candidate_run_dir: Path,
    selected_edl: list[dict[str, Any]],
    selected_plan: list[dict[str, Any]],
    word_rows: list[dict[str, Any]],
    jy_draftc: Path,
) -> dict[str, Any]:
    candidate_run_dir.mkdir(parents=True, exist_ok=True)
    timeline_id, timeline_name = resolve_timeline_id(candidate_dir, "")
    timeline_dir = candidate_dir / "Timelines" / timeline_id
    encrypted_path = timeline_dir / "draft_content.json"
    plain_before = candidate_run_dir / "draft_content.before.dec.json"
    plain_modified = candidate_run_dir / "draft_content.modified.dec.json"
    encrypted_out = candidate_run_dir / "draft_content.modified.enc.json"
    plain_after = candidate_run_dir / "draft_content.after.dec.json"
    report_path = candidate_run_dir / "write_report.json"

    decrypt(jy_draftc, encrypted_path, plain_before)
    data = read_json(plain_before)
    assert_timeline_content_id(data, timeline_id, encrypted_path)
    assert_layout_has_no_duplicate_timeline_ids(candidate_dir)
    assert_all_project_timeline_files_match_folder_ids(candidate_dir, jy_draftc, candidate_run_dir)

    root_mirror_required = False
    if (candidate_dir / "draft_content.json").exists():
        root_mirror_required = root_mirrors_timeline_id(candidate_dir, jy_draftc, candidate_run_dir, timeline_id)

    video_candidates, selected_main, video_fatals, video_warnings, main_speed_safe = inspect_video_tracks(data)
    subtitles, text_tracks, selected_text_track = subtitle_timeline(data)
    audio_tracks, has_independent_audio, has_complex_audio, audio_fatals = inspect_audio_tracks(data)
    main_total_duration_us = int((selected_main or {}).get("total_target_duration_us") or 0)
    filter_tracks, has_global_filter, has_complex_filter, filter_fatals = inspect_filter_tracks(data, main_total_duration_us)

    fatal: list[str] = []
    warnings: list[str] = []
    fatal.extend(video_fatals)
    warnings.extend(video_warnings)
    if not selected_main:
        fatal.append("MAIN_VIDEO_TRACK_NOT_FOUND")
    if not selected_text_track:
        fatal.append("TEXT_TRACK_NOT_FOUND")
    if len(subtitles) != 115:
        fatal.append(f"RESTORE_SUBTITLE_COUNT_NOT_115:{len(subtitles)}")
    if main_total_duration_us < 300_000_000:
        fatal.append(f"RESTORE_NOT_FULL_SOURCE_DURATION:{main_total_duration_us}")
    if audio_tracks or has_independent_audio or has_complex_audio:
        fatal.append("AUDIO_TRACK_PRESENT_UNSUPPORTED_FOR_PHASE4C")
        fatal.extend(f"AUDIO:{reason}" for reason in audio_fatals)
    if filter_tracks or has_global_filter or has_complex_filter:
        fatal.append("FILTER_TRACK_PRESENT_UNSUPPORTED_FOR_PHASE4C")
        fatal.extend(f"FILTER:{reason}" for reason in filter_fatals)
    if not main_speed_safe:
        fatal.append("MAIN_VIDEO_SPEED_UNSAFE")
    fatal.extend(validate_selected_edl(selected_edl))
    if fatal:
        report = {
            "candidate": candidate,
            "draft_dir": str(candidate_dir),
            "fatal_reasons": sorted(set(fatal)),
            "warnings": sorted(set(warnings)),
        }
        write_json(report_path, report)
        raise RuntimeError(f"{candidate}:PHASE4C_PREFLIGHT_BLOCKED:{report['fatal_reasons']}; report={report_path}")

    backup_paths = backup_draft_files(candidate_dir, timeline_id, candidate_run_dir, root_mirror_required)
    write_json(candidate_run_dir / "selected_word_edl.json", selected_edl)
    write_json(candidate_run_dir / "selected_subtitle_plan.json", selected_plan)

    main_track = get_track(data, str(selected_main["track_id"]))
    text_track = get_track(data, str(selected_text_track["track_id"]))
    if main_track is None or text_track is None:
        raise RuntimeError(f"{candidate}:SELECTED_TRACK_NOT_FOUND")

    old_video_segments = deepcopy(main_track.get("segments") or [])
    old_text_segments = deepcopy(text_track.get("segments") or [])
    new_video_segments, video_split_rows = split_video_segments_for_edl(old_video_segments, selected_edl)
    new_text_segments, subtitle_report = rewrite_word_level_text_segments(data, old_text_segments, selected_plan, word_rows)
    if not new_video_segments:
        raise RuntimeError(f"{candidate}:NO_VIDEO_SEGMENTS_WRITTEN")
    if not new_text_segments:
        raise RuntimeError(f"{candidate}:NO_TEXT_SEGMENTS_WRITTEN")
    if subtitle_report["missing_source_segments"]:
        raise RuntimeError(f"{candidate}:TEXT_SOURCE_SEGMENT_MISSING:{subtitle_report['missing_source_segments'][:3]}")

    before_video_segments = len(old_video_segments)
    before_text_segments = len(old_text_segments)
    before_duration = total_target_duration(old_video_segments)
    main_track["segments"] = new_video_segments
    text_track["segments"] = new_text_segments
    after_duration = total_target_duration(new_video_segments)
    data["duration"] = after_duration

    write_json(plain_modified, data)
    encrypt(jy_draftc, plain_modified, encrypted_out)

    targets = [
        timeline_dir / "draft_content.json",
        timeline_dir / "template-2.tmp",
    ]
    if root_mirror_required:
        targets.extend([candidate_dir / "draft_content.json", candidate_dir / "template-2.tmp"])
    target_writes = write_encrypted_to_targets(encrypted_out, targets)

    decrypt(jy_draftc, encrypted_path, plain_after)
    verify_data = read_json(plain_after)
    timeline_checks, check_fatals = timeline_id_checks_after(
        draft_dir=candidate_dir,
        jy_draftc=jy_draftc,
        run_dir=candidate_run_dir,
        plain_path=plain_after,
        encrypted_path=encrypted_path,
        timeline_id=timeline_id,
    )
    root_mirror_after = None
    if root_mirror_required:
        root_mirror_after = root_mirrors_timeline_id(candidate_dir, jy_draftc, candidate_run_dir, timeline_id)

    verify_video_track = get_track(verify_data, str(selected_main["track_id"])) or {}
    verify_text_track = get_track(verify_data, str(selected_text_track["track_id"])) or {}
    after_video_segments = len(verify_video_track.get("segments") or [])
    after_text_segments = len(verify_text_track.get("segments") or [])
    after_duration_verify = total_target_duration(verify_video_track.get("segments") or [])

    summary = {
        "candidate": candidate,
        "draft_dir": str(candidate_dir),
        "timeline_id": timeline_id,
        "timeline_name": timeline_name,
        "source_range_us": [
            min(int(row["source_start_us"]) for row in selected_edl),
            max(int(row["source_end_us"]) for row in selected_edl),
        ],
        "final_duration_us": after_duration_verify,
        "video_segments_before": before_video_segments,
        "video_segments_after": after_video_segments,
        "text_segments_before": before_text_segments,
        "text_segments_after": after_text_segments,
        "subtitle_fragments": len(selected_plan),
        "micro_cleanups": sum(1 for row in selected_plan if row.get("reason") == "micro_cleanup"),
        "text_changed_fragments": sum(1 for row in selected_plan if str(row.get("source_text") or "") != str(row.get("fragment_text") or "")),
        "word_gap_cuts": sum(1 for row in selected_edl if row.get("source_reason") == "word_gap_split"),
        "backup_paths": backup_paths,
        "template_2_tmp_written": str(timeline_dir / "template-2.tmp") in target_writes,
        "root_mirror_required": root_mirror_required,
        "root_mirror_matches_after": root_mirror_after,
        "timeline_id_checks_after": timeline_checks,
        "fatal_reasons": sorted(set(check_fatals)),
        "warnings": sorted(set(warnings)),
    }
    report = {
        "summary": summary,
        "selected_word_edl_path": str(candidate_run_dir / "selected_word_edl.json"),
        "selected_subtitle_plan_path": str(candidate_run_dir / "selected_subtitle_plan.json"),
        "draft_content_before_dec": str(plain_before),
        "draft_content_after_dec": str(plain_after),
        "video_split_rows": video_split_rows,
        "subtitle_rewrite_report": subtitle_report,
        "timeline_layout_modified": False,
        "project_json_modified": False,
    }
    write_json(report_path, report)
    post_inspect = run_post_inspect(candidate_dir, candidate_run_dir, jy_draftc)
    write_json(candidate_run_dir / "post_inspect_summary.json", post_inspect)
    (candidate_run_dir / "human_review_focus.md").write_text(make_human_focus(candidate, selected_plan, report), "utf-8")
    return report | {"post_inspect": post_inspect}


def restore_and_inspect_original(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    timeline_id, _timeline_name = resolve_timeline_id(args.draft_dir, "")
    restored_paths = restore_original_backup(args.draft_dir, timeline_id, args.backup_dir)
    post_restore = run_post_inspect(args.draft_dir, run_dir / "restore_inspect", args.jy_draftc)
    fatal = []
    duration = int(post_restore.get("duration_us") or 0)
    subtitles = int(post_restore.get("subtitle_segment_count") or 0)
    if abs(duration - SOURCE_DURATION_US) > 1_500_000:
        fatal.append(f"RESTORE_DURATION_NOT_308S:{duration}")
    if subtitles != 115:
        fatal.append(f"RESTORE_SUBTITLE_COUNT_NOT_115:{subtitles}")
    if post_restore.get("fatal_reasons"):
        fatal.extend(post_restore.get("fatal_reasons") or [])
    result = {
        "timeline_id": timeline_id,
        "restored_paths": restored_paths,
        "inspect": post_restore,
        "fatal_reasons": sorted(set(fatal)),
    }
    write_json(run_dir / "restore_original_result.json", result)
    if fatal:
        raise RuntimeError(f"RESTORE_ORIGINAL_FAILED:{fatal}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4C word-level partial write PoC for Jianying A-Roll.")
    parser.add_argument("--draft-dir", type=Path, default=DEFAULT_DRAFT_DIR)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--phase4b-dir", type=Path, default=DEFAULT_PHASE4B_DIR)
    parser.add_argument("--subtitle-timeline", type=Path, default=DEFAULT_SUBTITLES)
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    args = parser.parse_args()

    run_dir = args.runtime / f"{PHASE4C_RUNTIME_PREFIX}_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    original_subtitles = read_json(args.subtitle_timeline)
    full_edl, full_subtitle_plan, _gap_plan, dry_report = load_inputs(args.phase4b_dir)
    word_rows = read_json(args.phase4b_dir / "word_level_aroll_edl.json")
    # Use the original word timeline for fragment words. It is referenced from the dry-run report.
    word_timeline_path = Path(str((dry_report.get("inputs") or {}).get("word_timeline") or ""))
    if not word_timeline_path.exists():
        word_timeline_path = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4_diagnostics_20260614_171206\word_timeline.json")
    word_rows = read_json(word_timeline_path)

    restore_result = restore_and_inspect_original(args, run_dir)
    archive_root = run_dir / "archived_existing_candidate_dirs"
    candidate_dirs = {
        "candidate_A": args.draft_dir.parent / f"{args.draft_dir.name}_Phase4C_A",
        "candidate_B": args.draft_dir.parent / f"{args.draft_dir.name}_Phase4C_B",
    }
    archived_dirs: dict[str, str] = {}
    for candidate, candidate_dir in candidate_dirs.items():
        archived_dirs[candidate] = copy_candidate_draft(args.draft_dir, candidate_dir, archive_root)

    ranges = candidate_ranges(original_subtitles)
    reports: dict[str, Any] = {}
    for candidate, spec in ranges.items():
        candidate_edl, candidate_plan = select_candidate_payload(
            candidate,
            int(spec["source_start_us"]),
            int(spec["source_end_us"]),
            full_edl,
            full_subtitle_plan,
        )
        candidate_run_dir = run_dir / candidate
        report = write_candidate(
            candidate=candidate,
            draft_dir=args.draft_dir,
            candidate_dir=candidate_dirs[candidate],
            candidate_run_dir=candidate_run_dir,
            selected_edl=candidate_edl,
            selected_plan=candidate_plan,
            word_rows=word_rows,
            jy_draftc=args.jy_draftc,
        )
        report["candidate_spec"] = spec
        report["archived_existing_candidate_dir"] = archived_dirs[candidate]
        write_json(candidate_run_dir / "write_report.json", report)
        reports[candidate] = report

    summary = {
        "runtime_dir": str(run_dir),
        "original_draft_dir": str(args.draft_dir),
        "restore_result": restore_result,
        "candidate_dirs": {key: str(value) for key, value in candidate_dirs.items()},
        "archived_existing_candidate_dirs": archived_dirs,
        "phase4b_dir": str(args.phase4b_dir),
        "candidates": reports,
        "safety": {
            "restored_original_full_draft": True,
            "copied_candidate_drafts": True,
            "wrote_original_draft_for_restore_only": True,
            "wrote_candidate_drafts": True,
            "encrypt_called": True,
            "deepseek_called": False,
            "audio_filter_tracks_modified": False,
            "project_json_modified": False,
            "timeline_layout_modified": False,
        },
    }
    write_json(run_dir / "phase4c_word_write_poc_summary.json", summary)
    print("status=ok")
    print(f"runtime={run_dir}")
    print(f"summary={run_dir / 'phase4c_word_write_poc_summary.json'}")
    for candidate, report in reports.items():
        s = report["summary"]
        print(f"{candidate} draft={s['draft_dir']}")
        print(f"{candidate} final_duration_s={round(s['final_duration_us']/1_000_000,3)}")
        print(f"{candidate} video_segments={s['video_segments_after']} subtitle_fragments={s['subtitle_fragments']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
