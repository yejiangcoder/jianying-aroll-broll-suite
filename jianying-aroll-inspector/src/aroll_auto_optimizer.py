from __future__ import annotations

import argparse
import json
import re
import shutil
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
    material_index,
    material_text,
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
from aroll_smart_writer import conservative_review
from jy_bridge import (
    DEFAULT_JY_DRAFTC,
    assert_all_project_timeline_files_match_folder_ids,
    assert_layout_has_no_duplicate_timeline_ids,
    assert_timeline_content_id,
    decrypt,
    encrypt,
    guid,
    read_json as read_json_file,
    resolve_timeline_id,
    root_mirrors_timeline_id,
    write_json,
)


DEFAULT_DEEPSEEK_RUN = Path(
    r"D:\video tools\jianying-aroll-inspector\runtime\aroll_deepseek_decision_20260614_114516"
)
DEFAULT_ORIGINAL_SUBTITLES = Path(
    r"D:\video tools\jianying-aroll-inspector\runtime\aroll_inspect_20260614_111146\subtitle_timeline.json"
)
DEFAULT_SOURCE_BACKUP = Path(
    r"D:\video tools\jianying-aroll-inspector\runtime\aroll_roughcut_write_20260614_111435\backup"
)
DEFAULT_SCRIPT = Path(
    r"D:\idea-project\Jackson WorldViews\src\main\java\jackson\worldviews\content\shoortvideoScript\S16\S16正文脚本\S16-3-嘉豪.md"
)
V2_DURATION_US = 235_804_357


def clean_script_markdown(text: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#") or line.startswith("---"):
            continue
        if line.startswith("**") and line.endswith("**"):
            continue
        if line.startswith("* ") or line.startswith("> "):
            line = line[2:].strip()
        line = re.sub(r"^\*\*([^*]+)\*\*[:：]?", r"\1：", line)
        line = re.sub(r"\*\*", "", line)
        if line:
            lines.append(line)
    return "\n".join(lines).strip() + "\n"


def safe_copy(src: Path, dst: Path) -> None:
    if not src.exists():
        raise RuntimeError(f"RESTORE_SOURCE_MISSING:{src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def restore_original_backup(draft_dir: Path, timeline_id: str, backup_dir: Path) -> None:
    timeline_dir = draft_dir / "Timelines" / timeline_id
    targets = [
        (backup_dir / "timeline" / "draft_content.json", timeline_dir / "draft_content.json"),
        (backup_dir / "timeline" / "template-2.tmp", timeline_dir / "template-2.tmp"),
        (backup_dir / "root" / "draft_content.json", draft_dir / "draft_content.json"),
        (backup_dir / "root" / "template-2.tmp", draft_dir / "template-2.tmp"),
    ]
    draft_resolved = draft_dir.resolve()
    for src, dst in targets:
        if not dst.parent.resolve().is_relative_to(draft_resolved):
            raise RuntimeError(f"RESTORE_TARGET_OUTSIDE_DRAFT:{dst}")
        safe_copy(src, dst)


def clone_text_material(material: dict[str, Any], new_text: str) -> dict[str, Any]:
    cloned = deepcopy(material)
    cloned["id"] = guid()
    cloned["recognize_text"] = new_text
    cloned["words"] = {}
    cloned["current_words"] = {}
    cloned.pop("subtitle_keywords", None)
    for key in ("content", "base_content"):
        value = cloned.get(key)
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except Exception:
                continue
            if isinstance(parsed, dict):
                parsed["text"] = new_text
                for style in parsed.get("styles") or []:
                    if isinstance(style, dict) and "range" in style:
                        style["range"] = [0, len(new_text)]
                cloned[key] = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        elif isinstance(value, dict):
            value["text"] = new_text
            for style in value.get("styles") or []:
                if isinstance(style, dict) and "range" in style:
                    style["range"] = [0, len(new_text)]
            cloned[key] = value
    return cloned


def compact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "uid": row["subtitle_uid"],
        "index": int(row["subtitle_index"]),
        "text": row.get("subtitle_text") or "",
        "start_us": int(row["start_us"]),
        "duration_us": int(row["duration_us"]),
        "end_us": int(row["end_us"]),
    }


def build_feedback_overrides(rows: list[dict[str, Any]], params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    rows_by_index = {int(row["subtitle_index"]): row for row in rows}
    overrides: dict[str, dict[str, Any]] = {}
    matches: list[dict[str, Any]] = []

    sub2 = rows_by_index.get(2)
    sub3 = rows_by_index.get(3)
    if params.get("jiahao_cleanup") and sub2 and sub3:
        sub2_text = sub2.get("subtitle_text") or ""
        sub3_text = sub3.get("subtitle_text") or ""
        keep2 = "你嘲笑嘉豪是"
        keep3 = "对自己人的规训"
        cut2_end = int(sub2["start_us"]) + int(int(sub2["duration_us"]) * (len(keep2) / max(1, len(sub2_text))))
        cut3_start = int(sub3["start_us"]) + int(int(sub3["duration_us"]) * (len("的是") / max(1, len(sub3_text))))
        overrides[sub2["subtitle_uid"]] = {
            "rule_id": "fb_001_sub2",
            "subtitle_uid": sub2["subtitle_uid"],
            "subtitle_index": 2,
            "text_override": keep2,
            "cut_start_us": int(sub2["start_us"]),
            "cut_end_us": cut2_end,
            "cleanup_type": "manual_phrase_trim",
            "semantic_risk": 1,
        }
        overrides[sub3["subtitle_uid"]] = {
            "rule_id": "fb_001_sub3",
            "subtitle_uid": sub3["subtitle_uid"],
            "subtitle_index": 3,
            "text_override": keep3,
            "cut_start_us": cut3_start,
            "cut_end_us": int(sub3["end_us"]),
            "cleanup_type": "manual_phrase_trim",
            "semantic_risk": 1,
        }
        matches.append(
            {
                "rule_id": "fb_001",
                "action": "semantic_micro_cleanup",
                "matched_subtitles": [compact_row(sub2), compact_row(sub3)],
                "target_text": "你嘲笑嘉豪是 / 对自己人的规训",
                "risk": "medium",
            }
        )
    else:
        matched = [row for row in rows if int(row["subtitle_index"]) in {2, 3}]
        matches.append(
            {
                "rule_id": "fb_001",
                "action": "keep_for_safety",
                "matched_subtitles": [compact_row(row) for row in matched],
                "target_text": "你嘲笑嘉豪是对自己人的规训",
                "risk": "manual_or_audio_word_alignment_needed",
            }
        )

    sub23 = rows_by_index.get(23)
    if sub23:
        words = ((sub23.get("material") or {}).get("words") or {})
        word_texts = [str(item) for item in (words.get("text") or [])]
        start_times = [int(item) for item in (words.get("start_time") or [])]
        second_occurrence_start = None
        for index, token in enumerate(word_texts):
            if token == "你" and index >= 3 and index < len(start_times):
                second_occurrence_start = start_times[index]
                break
        if second_occurrence_start is None:
            text = sub23.get("subtitle_text") or ""
            second_char = text.rfind("你跪在地上")
            second_occurrence_start = int(int(sub23["duration_us"]) * (second_char / max(1, len(text)))) if second_char > 0 else 1_400_000
        cut_start = int(sub23["start_us"]) + int(second_occurrence_start) * 1000 + int(params.get("kneel_start_nudge_us", 0))
        cut_start = max(int(sub23["start_us"]), cut_start - int(params.get("kneel_micro_lead_us", 0)))
        cut_end = min(int(sub23["end_us"]) + int(params.get("kneel_tail_guard_us", 0)), int(sub23["end_us"]) + 40_000)
        overrides[sub23["subtitle_uid"]] = {
            "rule_id": "fb_002",
            "subtitle_uid": sub23["subtitle_uid"],
            "subtitle_index": 23,
            "text_override": "你跪在地上叫大佬",
            "cut_start_us": cut_start,
            "cut_end_us": cut_end,
            "cleanup_type": "remove_repeated_phrase_keep_suffix",
            "semantic_risk": 0,
        }
        matches.append(
            {
                "rule_id": "fb_002",
                "action": "micro_cleanup",
                "matched_subtitles": [compact_row(sub23)],
                "target_text": "你跪在地上叫大佬",
                "cut_start_us": cut_start,
                "cut_end_us": cut_end,
                "risk": "low",
            }
        )
    extra_rules = [
        {
            "index": 47,
            "match": "评论区评论区也全是哇塞",
            "text_override": "评论区也全是哇塞",
            "word_start_index": 2,
            "rule_id": "auto_stutter_047",
        },
        {
            "index": 84,
            "match": "你是极你们是极度恐慌",
            "text_override": "你们是极度恐慌",
            "word_start_index": 3,
            "rule_id": "auto_stutter_084",
        },
        {
            "index": 100,
            "match": "给给老子从坟墓里面挖出来",
            "text_override": "给老子从坟墓里面挖出来",
            "word_start_index": 1,
            "rule_id": "auto_stutter_100",
        },
        {
            "index": 115,
            "match": "重新上重新上桌重新上桌",
            "text_override": "重新上桌",
            "word_start_index": 4,
            "rule_id": "auto_stutter_115",
        },
    ]
    for rule in extra_rules:
        row = rows_by_index.get(rule["index"])
        if not row or rule["match"] not in str(row.get("subtitle_text") or ""):
            continue
        words = ((row.get("material") or {}).get("words") or {})
        starts = [int(item) for item in (words.get("start_time") or [])]
        word_index = int(rule["word_start_index"])
        if word_index >= len(starts):
            continue
        cut_start = int(row["start_us"]) + starts[word_index] * 1000
        uid = row["subtitle_uid"]
        overrides[uid] = {
            "rule_id": rule["rule_id"],
            "subtitle_uid": uid,
            "subtitle_index": int(row["subtitle_index"]),
            "text_override": rule["text_override"],
            "cut_start_us": cut_start,
            "cut_end_us": int(row["end_us"]),
            "cleanup_type": "remove_stutter_prefix_keep_suffix",
            "semantic_risk": 0,
        }
        matches.append(
            {
                "rule_id": rule["rule_id"],
                "action": "auto_stutter_micro_cleanup",
                "matched_subtitles": [compact_row(row)],
                "target_text": rule["text_override"],
                "cut_start_us": cut_start,
                "risk": "low",
            }
        )
    return {"source": "user_feedback_and_script_reference", "matches": matches}, overrides


def strict_neighbor_drop(spans: list[dict[str, Any]]) -> set[int]:
    out: set[int] = set()
    for span in spans:
        if span.get("decision") == "drop":
            out.update(range(int(span["subtitle_start_index"]), int(span["subtitle_end_index"]) + 1))
    return out


def build_candidate_edl(
    reviewed: dict[str, Any],
    subtitles: list[dict[str, Any]],
    source_duration_us: int,
    text_overrides: dict[str, dict[str, Any]],
    params: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows_by_index = {int(row["subtitle_index"]): row for row in subtitles}
    spans = sorted(reviewed.get("spans") or [], key=lambda item: (int(item["subtitle_start_index"]), int(item["subtitle_end_index"])))
    drop_indices = strict_neighbor_drop(spans)
    lead_guard = int(params["lead_guard_us"])
    tail_guard = int(params["tail_guard_us"])
    strict_guard = int(params["strict_drop_boundary_guard_us"])
    merge_gap = int(params["merge_keep_gap_us"])
    strict_applied = 0
    regions: list[dict[str, Any]] = []

    for span in spans:
        if span.get("decision") != "keep":
            continue
        for index in range(int(span["subtitle_start_index"]), int(span["subtitle_end_index"]) + 1):
            row = rows_by_index.get(index)
            if not row:
                continue
            uid = row["subtitle_uid"]
            start_us = int(row["start_us"])
            end_us = int(row["end_us"])
            cut_start = max(0, start_us - lead_guard)
            cut_end = min(source_duration_us, end_us + tail_guard)
            override = text_overrides.get(uid)
            if override:
                cut_start = max(cut_start, int(override.get("cut_start_us", cut_start)))
                cut_end = min(cut_end, int(override.get("cut_end_us", cut_end)))
            if index - 1 in drop_indices:
                cut_start = max(cut_start, start_us - strict_guard)
                strict_applied += 1
            if index + 1 in drop_indices:
                cut_end = min(cut_end, end_us + strict_guard)
                strict_applied += 1
            if cut_end <= cut_start:
                continue
            regions.append(
                {
                    "clip_id": f"src_{len(regions) + 1:03d}",
                    "subtitle_start_uid": uid,
                    "subtitle_end_uid": uid,
                    "subtitle_start_index": index,
                    "subtitle_end_index": index,
                    "cut_start_us": cut_start,
                    "cut_end_us": cut_end,
                    "target_duration_us": cut_end - cut_start,
                    "target_start_us": 0,
                    "pause_after_us": 0,
                    "source_span_ids": [span.get("span_id")],
                    "source_subtitle_count": 1,
                    "subtitle_texts": [row.get("subtitle_text") or ""],
                    "text_overrides": {uid: override} if override else {},
                    "partial_reason": "text_override" if override else "",
                    "drop_boundary_strict": (index - 1 in drop_indices) or (index + 1 in drop_indices),
                }
            )

    merged: list[dict[str, Any]] = []
    for region in regions:
        if not merged:
            merged.append(deepcopy(region))
            continue
        current = merged[-1]
        adjacent = int(region["subtitle_start_index"]) == int(current["subtitle_end_index"]) + 1
        gap = int(region["cut_start_us"]) - int(current["cut_end_us"])
        has_override_boundary = bool(region.get("text_overrides")) or bool(current.get("text_overrides"))
        if adjacent and gap <= merge_gap and not has_override_boundary:
            current["subtitle_end_uid"] = region["subtitle_end_uid"]
            current["subtitle_end_index"] = region["subtitle_end_index"]
            current["cut_end_us"] = max(int(current["cut_end_us"]), int(region["cut_end_us"]))
            current["target_duration_us"] = int(current["cut_end_us"]) - int(current["cut_start_us"])
            current["source_span_ids"].extend(region.get("source_span_ids") or [])
            current["source_subtitle_count"] += 1
            current["subtitle_texts"].extend(region.get("subtitle_texts") or [])
            current["drop_boundary_strict"] = bool(current.get("drop_boundary_strict")) or bool(region.get("drop_boundary_strict"))
        else:
            merged.append(deepcopy(region))

    edl: list[dict[str, Any]] = []
    target_start = 0
    for index, region in enumerate(merged, start=1):
        clip = deepcopy(region)
        clip["clip_id"] = f"auto_{index:03d}"
        clip["target_start_us"] = target_start
        clip["pause_after_us"] = 0
        clip["boundary_mode"] = "auto_optimizer_tight_overlap_aware"
        edl.append(clip)
        target_start += int(clip["target_duration_us"])
    metadata = {
        "strict_drop_boundary_applied_count": strict_applied,
        "merge_keep_gap_us": merge_gap,
        "lead_guard_us": lead_guard,
        "tail_guard_us": tail_guard,
    }
    return edl, metadata


def update_material_text(material: dict[str, Any], new_text: str) -> dict[str, Any]:
    cloned = deepcopy(material)
    cloned["id"] = guid()
    cloned["recognize_text"] = new_text
    cloned["words"] = {}
    cloned["current_words"] = {}
    cloned.pop("subtitle_keywords", None)
    for key in ("content", "base_content"):
        value = cloned.get(key)
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except Exception:
                continue
            if isinstance(parsed, dict):
                parsed["text"] = new_text
                for style in parsed.get("styles") or []:
                    if isinstance(style, dict) and "range" in style:
                        style["range"] = [0, len(new_text)]
                cloned[key] = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        elif isinstance(value, dict):
            value["text"] = new_text
            for style in value.get("styles") or []:
                if isinstance(style, dict) and "range" in style:
                    style["range"] = [0, len(new_text)]
            cloned[key] = value
    return cloned


def rewrite_text_segments_overlap_aware(
    data: dict[str, Any],
    old_text_segments: list[dict[str, Any]],
    subtitles: list[dict[str, Any]],
    edl: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    text_materials = (data.get("materials") or {}).setdefault("texts", [])
    text_by_id = {str(material.get("id") or ""): material for material in text_materials}
    segment_by_id = {str(segment.get("id") or ""): segment for segment in old_text_segments if segment.get("id")}
    rewritten: list[dict[str, Any]] = []
    report_rows: list[dict[str, Any]] = []
    partial_without_override = 0
    material_clones = 0

    for clip in edl:
        clip_start = int(clip["cut_start_us"])
        clip_end = int(clip["cut_end_us"])
        target_start = int(clip["target_start_us"])
        overrides = clip.get("text_overrides") or {}
        clip_subtitle_start = int(clip["subtitle_start_index"])
        clip_subtitle_end = int(clip["subtitle_end_index"])
        for row in subtitles:
            row_index = int(row["subtitle_index"])
            if row_index < clip_subtitle_start or row_index > clip_subtitle_end:
                continue
            source_start = int(row["start_us"])
            source_end = int(row["end_us"])
            overlap_start = max(source_start, clip_start)
            overlap_end = min(source_end, clip_end)
            if overlap_end <= overlap_start:
                continue
            source_segment = segment_by_id.get(str(row["text_segment_id"]))
            if not source_segment:
                continue
            new_segment = deepcopy(source_segment)
            new_segment["id"] = guid()
            new_start = target_start + (overlap_start - clip_start)
            new_duration = overlap_end - overlap_start
            target_timerange = deepcopy(new_segment.get("target_timerange") or {})
            target_timerange["start"] = new_start
            target_timerange["duration"] = new_duration
            new_segment["target_timerange"] = target_timerange
            new_text = None
            override = overrides.get(row["subtitle_uid"])
            partial = overlap_start > source_start or overlap_end < source_end
            if override and override.get("text_override"):
                new_text = str(override["text_override"])
            elif partial:
                partial_without_override += 1
            if new_text is not None:
                old_material = text_by_id.get(str(source_segment.get("material_id") or ""))
                if old_material:
                    cloned = update_material_text(old_material, new_text)
                    text_materials.append(cloned)
                    text_by_id[cloned["id"]] = cloned
                    new_segment["material_id"] = cloned["id"]
                    material_clones += 1
            rewritten.append(new_segment)
            report_rows.append(
                {
                    "clip_id": clip["clip_id"],
                    "subtitle_uid": row["subtitle_uid"],
                    "old_text": row.get("subtitle_text") or "",
                    "new_text": new_text or row.get("subtitle_text") or "",
                    "partial_subtitle_clip": partial,
                    "has_text_override": new_text is not None,
                    "old_start_us": source_start,
                    "old_end_us": source_end,
                    "overlap_start_us": overlap_start,
                    "overlap_end_us": overlap_end,
                    "new_start_us": new_start,
                    "new_duration_us": new_duration,
                }
            )
    rewritten.sort(key=segment_start)
    return rewritten, {
        "rows": report_rows,
        "partial_subtitle_without_override": partial_without_override,
        "material_clone_count": material_clones,
    }


def validate_subtitles_inside_clips(text_segments: list[dict[str, Any]], video_segments: list[dict[str, Any]]) -> int:
    video_ranges = [(segment_start(segment), segment_end(segment)) for segment in video_segments]
    outside = 0
    for segment in text_segments:
        start = segment_start(segment)
        end = segment_end(segment)
        if not any(start >= vs and end <= ve for vs, ve in video_ranges):
            outside += 1
    return outside


def scan_residuals(edl: list[dict[str, Any]], subtitle_report: dict[str, Any]) -> dict[str, Any]:
    texts = [row["new_text"] for row in subtitle_report.get("rows") or []]
    residuals: list[dict[str, Any]] = []
    repeat_patterns = [
        "你跪在地上你跪在地上",
        "评论区评论区",
        "恨不得给恨不得给",
        "你是极你们是",
        "给给老子",
        "重新上重新上",
    ]
    for text in texts:
        for pattern in repeat_patterns:
            if pattern in text:
                residuals.append({"type": "same_subtitle_repeat", "pattern": pattern, "text": text})
    for prev, curr in zip(texts, texts[1:]):
        if prev and curr and curr.startswith(prev) and len(prev) >= 4:
            residuals.append({"type": "adjacent_prefix_repeat", "previous": prev, "current": curr})
    gaps: list[int] = []
    for prev, curr in zip(edl, edl[1:]):
        gap = int(curr["target_start_us"]) - (int(prev["target_start_us"]) + int(prev["target_duration_us"]))
        if gap > 120_000:
            gaps.append(gap)
    subtitle_rows = sorted(
        subtitle_report.get("rows") or [],
        key=lambda row: int(row.get("new_start_us") or 0),
    )
    subtitle_gaps: list[int] = []
    for prev, curr in zip(subtitle_rows, subtitle_rows[1:]):
        prev_end = int(prev.get("new_start_us") or 0) + int(prev.get("new_duration_us") or 0)
        curr_start = int(curr.get("new_start_us") or 0)
        gap = curr_start - prev_end
        if gap > 120_000:
            subtitle_gaps.append(gap)
    return {
        "residual_text_repeat_count": len(residuals),
        "residuals": residuals,
        "long_pause_count": len(gaps) + len(subtitle_gaps),
        "clip_gap_long_pause_count": len(gaps),
        "subtitle_gap_long_pause_count": len(subtitle_gaps),
        "max_pause_us": max(gaps + subtitle_gaps) if (gaps or subtitle_gaps) else 0,
        "feedback_keywords": {
            "kneel_repeat_present": any("你跪在地上你跪在地上" in text for text in texts),
            "kneel_fixed_text_present": any(text == "你跪在地上叫大佬" for text in texts),
            "jiahao_split_fixed": any(text == "你嘲笑嘉豪是" for text in texts) and any(text == "对自己人的规训" for text in texts),
        },
    }


def score_candidate(score_input: dict[str, Any]) -> dict[str, Any]:
    if score_input["fatal_reasons"]:
        score = 0
    else:
        score = 100
        score -= score_input["subtitle_outside_clip_count"] * 20
        score -= score_input["partial_subtitle_without_override"] * 8
        score -= score_input["residual_text_repeat_count"] * 10
        score -= score_input["long_pause_count"] * 5
        score -= score_input["semantic_risk_count"] * 3
        if not score_input["known_feedback_fixed"]["kneel_repeat_text_fixed"]:
            score -= 25
        if not score_input["known_feedback_fixed"]["jiahao_regulation_text_fixed"]:
            score -= 18
        if score_input["final_duration_us"] > 245_000_000:
            score -= 5
        score = max(0, score)
    score_input["score"] = score
    return score_input


def candidate_params() -> list[dict[str, Any]]:
    base = {
        "lead_guard_us": 60_000,
        "tail_guard_us": 80_000,
        "strict_drop_boundary_guard_us": 0,
        "merge_keep_gap_us": 60_000,
        "kneel_micro_lead_us": 0,
        "kneel_tail_guard_us": 20_000,
    }
    return [
        {**base, "candidate": "candidate_01", "jiahao_cleanup": True, "kneel_start_nudge_us": 0},
        {**base, "candidate": "candidate_02", "jiahao_cleanup": True, "kneel_start_nudge_us": 80_000, "lead_guard_us": 40_000, "tail_guard_us": 60_000, "merge_keep_gap_us": 40_000},
        {**base, "candidate": "candidate_03", "jiahao_cleanup": True, "kneel_start_nudge_us": 120_000, "lead_guard_us": 25_000, "tail_guard_us": 45_000, "merge_keep_gap_us": 25_000},
        {**base, "candidate": "candidate_04", "jiahao_cleanup": True, "kneel_start_nudge_us": 160_000, "lead_guard_us": 15_000, "tail_guard_us": 30_000, "merge_keep_gap_us": 15_000},
    ]


def run_candidate(
    args: argparse.Namespace,
    auto_dir: Path,
    timeline_id: str,
    params: dict[str, Any],
    script_clean: str,
) -> dict[str, Any]:
    candidate_dir = auto_dir / params["candidate"]
    candidate_dir.mkdir(parents=True, exist_ok=True)
    restore_original_backup(args.draft_dir, timeline_id, args.source_backup)

    timeline_dir = args.draft_dir / "Timelines" / timeline_id
    encrypted_path = timeline_dir / "draft_content.json"
    plain_before = candidate_dir / "draft_content.before.dec.json"
    plain_modified = candidate_dir / "draft_content.modified.dec.json"
    encrypted_out = candidate_dir / "draft_content.modified.enc.json"
    plain_after = candidate_dir / "draft_content.after.dec.json"

    decrypt(args.jy_draftc, encrypted_path, plain_before)
    data = read_json_file(plain_before)
    assert_timeline_content_id(data, timeline_id, encrypted_path)
    assert_layout_has_no_duplicate_timeline_ids(args.draft_dir)
    assert_all_project_timeline_files_match_folder_ids(args.draft_dir, args.jy_draftc, candidate_dir)
    root_required = root_mirrors_timeline_id(args.draft_dir, args.jy_draftc, candidate_dir, timeline_id)

    video_candidates, selected_main, video_fatals, video_warnings, main_speed_safe = inspect_video_tracks(data)
    subtitles, text_tracks, selected_text_track = subtitle_timeline(data)
    audio_tracks, has_independent_audio, has_complex_audio, audio_fatals = inspect_audio_tracks(data)
    main_total_duration_us = int((selected_main or {}).get("total_target_duration_us") or 0)
    filter_tracks, has_global_filter, has_complex_filter, filter_fatals = inspect_filter_tracks(data, main_total_duration_us)
    fatal_reasons = list(video_fatals)
    warnings = list(video_warnings)
    if not selected_main:
        fatal_reasons.append("MAIN_VIDEO_TRACK_NOT_FOUND")
    if not selected_text_track:
        fatal_reasons.append("TEXT_TRACK_NOT_FOUND")
    if len(subtitles) != 115:
        fatal_reasons.append(f"UNEXPECTED_SUBTITLE_COUNT:{len(subtitles)}")
    if main_total_duration_us < 300_000_000:
        fatal_reasons.append(f"RESTORE_NOT_FULL_SOURCE_DURATION:{main_total_duration_us}")
    if audio_tracks or has_independent_audio or has_complex_audio:
        fatal_reasons.append("AUDIO_TRACK_PRESENT_UNSUPPORTED")
        fatal_reasons.extend(audio_fatals)
    if filter_tracks or has_global_filter or has_complex_filter:
        fatal_reasons.append("FILTER_TRACK_PRESENT_UNSUPPORTED")
        fatal_reasons.extend(filter_fatals)
    if not main_speed_safe:
        fatal_reasons.append("MAIN_VIDEO_SPEED_UNSAFE")
    if fatal_reasons:
        raise RuntimeError(f"CANDIDATE_PREFLIGHT_BLOCKED:{params['candidate']}:{fatal_reasons}")

    (candidate_dir / "script_reference_clean.txt").write_text(script_clean, "utf-8")
    write_json(candidate_dir / "subtitle_timeline.before.json", subtitles)
    clusters = read_json(args.deepseek_run / "take_clusters.json")
    decisions = read_json(args.deepseek_run / "deepseek_aroll_decisions.json")
    review_text = (args.deepseek_run / "human_review_drops.md").read_text("utf-8")
    reviewed, conservative_summary = conservative_review(clusters, decisions, review_text)
    diagnosis, text_overrides = build_feedback_overrides(subtitles, params)
    write_json(candidate_dir / "residual_cleanup_diagnosis.json", diagnosis)
    write_json(candidate_dir / "candidate_decisions.json", reviewed)
    edl, edl_meta = build_candidate_edl(reviewed, subtitles, main_total_duration_us, text_overrides, params)
    write_json(candidate_dir / "candidate_edl.json", edl)

    backup_paths = backup_draft_files(args.draft_dir, timeline_id, candidate_dir, root_required)
    main_track = get_track(data, str(selected_main["track_id"]))
    text_track = get_track(data, str(selected_text_track["track_id"]))
    if main_track is None or text_track is None:
        raise RuntimeError("TRACK_NOT_FOUND_DURING_CANDIDATE_WRITE")
    old_video_segments = deepcopy(main_track.get("segments") or [])
    old_text_segments = deepcopy(text_track.get("segments") or [])
    new_video_segments, video_split_rows = split_video_segments_for_edl(old_video_segments, edl)
    new_text_segments, subtitle_rewrite_report = rewrite_text_segments_overlap_aware(data, old_text_segments, subtitles, edl)
    if not new_video_segments or not new_text_segments:
        raise RuntimeError("CANDIDATE_REWRITE_EMPTY")

    main_track["segments"] = new_video_segments
    text_track["segments"] = new_text_segments
    data["duration"] = total_target_duration(new_video_segments)

    write_json(candidate_dir / "subtitle_rewrite_report.json", subtitle_rewrite_report)
    write_json(plain_modified, data)
    encrypt(args.jy_draftc, plain_modified, encrypted_out)
    targets = [timeline_dir / "draft_content.json", timeline_dir / "template-2.tmp"]
    if root_required:
        targets.extend([args.draft_dir / "draft_content.json", args.draft_dir / "template-2.tmp"])
    target_writes = write_encrypted_to_targets(encrypted_out, targets)
    decrypt(args.jy_draftc, encrypted_path, plain_after)
    verify_data = read_json_file(plain_after)
    checks, check_fatals = timeline_id_checks_after(args.draft_dir, args.jy_draftc, candidate_dir, plain_after, encrypted_path, timeline_id)
    root_after = root_mirrors_timeline_id(args.draft_dir, args.jy_draftc, candidate_dir, timeline_id) if root_required else None
    verify_video = get_track(verify_data, str(selected_main["track_id"])) or {}
    verify_text = get_track(verify_data, str(selected_text_track["track_id"])) or {}
    after_video_segments = verify_video.get("segments") or []
    after_text_segments = verify_text.get("segments") or []

    outside = validate_subtitles_inside_clips(after_text_segments, after_video_segments)
    residual_scan = scan_residuals(edl, subtitle_rewrite_report)
    write_json(candidate_dir / "residual_scan_report.json", residual_scan)
    post_summary = {
        "can_decrypt_after_write": True,
        "timeline_id_checks": checks,
        "root_mirror_matches_after": root_after,
        "video_segment_count": len(after_video_segments),
        "subtitle_segment_count": len(after_text_segments),
        "final_duration_us": total_target_duration(after_video_segments),
        "fatal_reasons": check_fatals,
        "warnings": warnings,
    }
    write_json(candidate_dir / "post_inspect_summary.json", post_summary)

    semantic_risk = sum(int(item.get("semantic_risk") or 0) for item in text_overrides.values())
    score = score_candidate(
        {
            "candidate": params["candidate"],
            "can_decrypt_after_write": True,
            "timeline_root_ok": all(checks.values()) and bool(root_after if root_required else True),
            "video_segment_count": len(after_video_segments),
            "subtitle_segment_count": len(after_text_segments),
            "final_duration_us": total_target_duration(after_video_segments),
            "deleted_subtitle_count": 115 - len({row["subtitle_uid"] for row in subtitle_rewrite_report["rows"]}),
            "micro_cut_count": len(text_overrides),
            "partial_subtitle_without_override": subtitle_rewrite_report["partial_subtitle_without_override"],
            "subtitle_outside_clip_count": outside,
            "known_feedback_fixed": {
                "kneel_repeat_audio_attempted": "sub_000023" in text_overrides,
                "kneel_repeat_text_fixed": residual_scan["feedback_keywords"]["kneel_fixed_text_present"],
                "jiahao_regulation_attempted": bool(params.get("jiahao_cleanup")),
                "jiahao_regulation_text_fixed": residual_scan["feedback_keywords"]["jiahao_split_fixed"],
            },
            "residual_text_repeat_count": residual_scan["residual_text_repeat_count"],
            "long_pause_count": residual_scan["long_pause_count"],
            "max_pause_us": residual_scan["max_pause_us"],
            "semantic_risk_count": semantic_risk,
            "fatal_reasons": check_fatals,
        }
    )
    write_json(candidate_dir / "candidate_score.json", score)
    report = {
        "candidate": params["candidate"],
        "params": params,
        "runtime_dir": str(candidate_dir),
        "backup_paths": backup_paths,
        "target_writes": target_writes,
        "conservative_review_summary": conservative_summary,
        "edl_metadata": edl_meta,
        "video_track_before": {
            "segment_count": len(old_video_segments),
            "total_duration_us": total_target_duration(old_video_segments),
        },
        "video_track_after": {
            "segment_count": len(after_video_segments),
            "total_duration_us": total_target_duration(after_video_segments),
        },
        "text_track_before": {"segment_count": len(old_text_segments)},
        "text_track_after": {"segment_count": len(after_text_segments)},
        "score": score,
        "residual_scan_report": str(candidate_dir / "residual_scan_report.json"),
        "candidate_edl": str(candidate_dir / "candidate_edl.json"),
        "encrypted_output": str(encrypted_out),
        "root_mirror_required": root_required,
        "root_mirror_matches_after": root_after,
        "timeline_layout_modified": False,
        "fatal_reasons": check_fatals,
        "warnings": warnings,
    }
    write_json(candidate_dir / "candidate_report.json", report)
    return report


def write_best_candidate_to_draft(best: dict[str, Any], draft_dir: Path, timeline_id: str) -> dict[str, Any]:
    encrypted = Path(best["encrypted_output"])
    timeline_dir = draft_dir / "Timelines" / timeline_id
    targets = [timeline_dir / "draft_content.json", timeline_dir / "template-2.tmp"]
    if best.get("root_mirror_required"):
        targets.extend([draft_dir / "draft_content.json", draft_dir / "template-2.tmp"])
    return write_encrypted_to_targets(encrypted, targets)


def make_human_review_focus(best: dict[str, Any], auto_dir: Path) -> Path:
    path = auto_dir / "human_review_focus.md"
    lines = [
        "# A-Roll Auto Optimize Human Review Focus",
        "",
        f"- Best candidate: {best['candidate']}",
        f"- Final duration: {best['score']['final_duration_us'] / 1_000_000:.2f}s",
        "",
        "## 必看点",
        "",
        "1. 重点看「你跪在地上...叫大佬」：是否只剩最后一次完整表达。",
        "2. 重点看「你嘲笑嘉豪...规训」：是否变顺，且核心语义没有被误删。",
        "3. 随机看 3 个删除重复 take 的位置：是否误删正常句。",
        "4. 看整体停顿是否更紧。",
        "5. 看字幕是否跟着视频，文本是否合理。",
        "6. 看是否有切字 / 断尾音 / 黑屏 / 错位。",
        "",
        "## 风险提示",
        "",
        "- 「你嘲笑嘉豪」做了语义 micro cleanup，仍需人工听一遍。",
        "- 所有候选仍基于字幕文本和草稿时间码，没有真实音频波形级识别。",
    ]
    path.write_text("\n".join(lines) + "\n", "utf-8")
    return path


def run_auto_optimize(args: argparse.Namespace) -> tuple[Path, Path]:
    auto_dir = args.runtime / f"aroll_auto_optimize_{time.strftime('%Y%m%d_%H%M%S')}"
    auto_dir.mkdir(parents=True, exist_ok=True)
    timeline_id, timeline_name = resolve_timeline_id(args.draft_dir, args.timeline_name)
    script_text = args.script_path.read_text("utf-8")
    script_clean = clean_script_markdown(script_text)
    (auto_dir / "script_reference_clean.txt").write_text(script_clean, "utf-8")

    restore_original_backup(args.draft_dir, timeline_id, args.source_backup)
    candidates: list[dict[str, Any]] = []
    for params in candidate_params()[: args.max_iterations]:
        report = run_candidate(args, auto_dir, timeline_id, params, script_clean)
        candidates.append(report)

    scored = sorted(candidates, key=lambda row: int(row["score"]["score"]), reverse=True)
    best = scored[0]
    final_writes = write_best_candidate_to_draft(best, args.draft_dir, timeline_id)
    focus_path = make_human_review_focus(best, auto_dir)
    summary = {
        "draft_dir": str(args.draft_dir),
        "timeline_id": timeline_id,
        "timeline_name": timeline_name,
        "script_path": str(args.script_path),
        "script_read_success": True,
        "script_clean_char_count": len(script_clean),
        "script_used_for_deepseek": False,
        "deepseek_called": False,
        "deepseek_call_count": 0,
        "candidate_count": len(candidates),
        "candidates": [
            {
                "candidate": item["candidate"],
                "runtime_dir": item["runtime_dir"],
                "final_duration_us": item["score"]["final_duration_us"],
                "video_segments": item["score"]["video_segment_count"],
                "subtitle_segments": item["score"]["subtitle_segment_count"],
                "deleted_subtitles": item["score"]["deleted_subtitle_count"],
                "micro_cuts": item["score"]["micro_cut_count"],
                "residual_repeat_count": item["score"]["residual_text_repeat_count"],
                "long_pause_count": item["score"]["long_pause_count"],
                "partial_subtitle_without_override": item["score"]["partial_subtitle_without_override"],
                "score": item["score"]["score"],
                "fatal_reasons": item["score"]["fatal_reasons"],
            }
            for item in candidates
        ],
        "best_candidate": best["candidate"],
        "best_candidate_runtime": best["runtime_dir"],
        "best_candidate_report": str(Path(best["runtime_dir"]) / "candidate_report.json"),
        "final_writes": final_writes,
        "final_written_candidate": best["candidate"],
        "human_review_focus": str(focus_path),
    }
    summary_path = auto_dir / "auto_optimize_summary.json"
    best_path = auto_dir / "best_candidate_report.json"
    final_txt = auto_dir / "final_written_candidate.txt"
    write_json(summary_path, summary)
    write_json(best_path, best)
    final_txt.write_text(best["candidate"] + "\n", "utf-8")
    return auto_dir, summary_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Autonomous bounded Smart A-Roll optimizer for the 6月14日 sacrificial draft.")
    parser.add_argument("--draft-dir", type=Path, default=Path(r"D:\JianyingPro Drafts\6月14日"))
    parser.add_argument("--subtitle-timeline", type=Path, default=DEFAULT_ORIGINAL_SUBTITLES)
    parser.add_argument("--script-path", type=Path, default=DEFAULT_SCRIPT)
    parser.add_argument("--deepseek-run", type=Path, default=DEFAULT_DEEPSEEK_RUN)
    parser.add_argument("--source-backup", type=Path, default=DEFAULT_SOURCE_BACKUP)
    parser.add_argument("--timeline-name", default="")
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--max-iterations", type=int, default=4)
    args = parser.parse_args()

    auto_dir, summary_path = run_auto_optimize(args)
    summary = read_json(summary_path)
    print("status=ok")
    print(f"runtime={auto_dir}")
    print(f"summary={summary_path}")
    print(f"best_candidate={summary['best_candidate']}")
    print(f"best_candidate_report={summary['best_candidate_report']}")
    print(f"human_review_focus={summary['human_review_focus']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
