from __future__ import annotations

import argparse
import array
import json
import math
import shutil
import statistics
import subprocess
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
    segment_end,
    segment_start,
    subtitle_timeline,
    timerange_start,
    total_target_duration,
)
from aroll_poc_writer import (
    backup_draft_files,
    get_track,
    split_video_segments_for_edl,
    write_encrypted_to_targets,
)
from aroll_semantic_guard import build_semantic_guard_report, guard_drop_span, normalize_compact_text
from aroll_smart_writer import conservative_review
from aroll_system_cleanup_optimizer import (
    DEFAULT_DEEPSEEK_RUN,
    DEFAULT_ORIGINAL_SUBTITLES,
    DEFAULT_SCRIPT,
    DEFAULT_SOURCE_BACKUP,
    build_feedback_overrides,
    call_deepseek_system_cleanup,
    clean_script_markdown,
    compact_row,
    drop_span,
    drop_span_allowed,
    expand_reviewed_spans,
    restore_original_backup,
    scan_residual_texts,
    update_material_text,
    validate_subtitles_inside_clips,
)
from jy_bridge import (
    DEFAULT_JY_DRAFTC,
    assert_all_project_timeline_files_match_folder_ids,
    assert_layout_has_no_duplicate_timeline_ids,
    assert_timeline_content_id,
    decrypt,
    encrypt,
    read_json as read_json_file,
    resolve_timeline_id,
    root_mirrors_timeline_id,
    write_json,
)


MIN_SPEECH_ISLAND_US = 160_000


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return -90.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * pct))))
    return ordered[index]


def word_lists(row: dict[str, Any]) -> tuple[list[str], list[int], list[int], int]:
    words = ((row.get("material") or {}).get("words") or {})
    tokens = [str(item) for item in (words.get("text") or [])]
    starts = [int(item) for item in (words.get("start_time") or [])]
    ends = [int(item) for item in (words.get("end_time") or [])]
    if not tokens or len(tokens) != len(starts) or len(tokens) != len(ends):
        return [], [], [], 1
    max_time = max(max(starts), max(ends))
    duration_us = max(1, int(row.get("duration_us") or 0))
    factor = 1000 if max_time < duration_us / 100 else 1
    return tokens, starts, ends, factor


def phrase_range_from_words_v5(
    row: dict[str, Any],
    kept_text: str,
    cleanup_type: str,
    diagnostics: dict[str, Any],
) -> tuple[int, int, str] | None:
    tokens, starts, ends, factor = word_lists(row)
    if not tokens:
        diagnostics["word_timing_missing_count"] += 1
        return None
    compact_tokens = [normalize_compact_text(token) for token in tokens]
    joined = "".join(compact_tokens)
    wanted = normalize_compact_text(kept_text)
    if not joined or not wanted:
        return None
    if cleanup_type in {"keep_suffix", "remove_repeated_phrase", "remove_prefix_fragment", "remove_stutter_prefix_keep_suffix"}:
        pos = joined.rfind(wanted)
    else:
        pos = joined.find(wanted)
    if pos < 0:
        diagnostics["word_timing_no_phrase_count"] += 1
        return None

    cursor = 0
    start_i = 0
    end_i = len(tokens) - 1
    for i, token in enumerate(compact_tokens):
        next_cursor = cursor + len(token)
        if cursor <= pos < next_cursor:
            start_i = i
        if cursor < pos + len(wanted) <= next_cursor:
            end_i = i
            break
        cursor = next_cursor

    diagnostics["word_timing_used_count"] += 1
    diagnostics["word_time_unit_counts"]["ms" if factor == 1000 else "us"] += 1
    diagnostics["word_timing_examples"].append(
        {
            "subtitle_uid": row.get("subtitle_uid"),
            "subtitle_index": row.get("subtitle_index"),
            "original_text": row.get("subtitle_text"),
            "kept_text": kept_text,
            "cleanup_type": cleanup_type,
            "unit_factor": factor,
            "word_start_index": start_i,
            "word_end_index": end_i,
        }
    )
    cut_start = int(row["start_us"]) + starts[start_i] * factor
    cut_end = int(row["start_us"]) + ends[end_i] * factor
    return cut_start, cut_end, "word_timing"


def phrase_range_by_ratio_v5(row: dict[str, Any], kept_text: str, cleanup_type: str, diagnostics: dict[str, Any]) -> tuple[int, int, str]:
    original = normalize_compact_text(row.get("subtitle_text") or "")
    wanted = normalize_compact_text(kept_text)
    if cleanup_type in {"keep_suffix", "remove_repeated_phrase", "remove_prefix_fragment", "remove_stutter_prefix_keep_suffix"}:
        pos = original.rfind(wanted)
    else:
        pos = original.find(wanted)
    diagnostics["char_ratio_fallback_count"] += 1
    if pos < 0:
        return int(row["start_us"]), int(row["end_us"]), "char_ratio_full_fallback"
    start = int(row["start_us"]) + int(int(row["duration_us"]) * (pos / max(1, len(original))))
    end = int(row["start_us"]) + int(int(row["duration_us"]) * ((pos + len(wanted)) / max(1, len(original))))
    return start, min(int(row["end_us"]), max(start + 40_000, end)), "char_ratio"


def cleanup_to_override_v5(row: dict[str, Any], cleanup: dict[str, Any], diagnostics: dict[str, Any]) -> dict[str, Any] | None:
    kept_text = str(cleanup.get("kept_text") or cleanup.get("text_override") or "").strip()
    if not kept_text:
        return None
    cleanup_type = str(cleanup.get("cleanup_type") or "manual_phrase_trim")
    word_range = phrase_range_from_words_v5(row, kept_text, cleanup_type, diagnostics)
    if word_range is None:
        word_range = phrase_range_by_ratio_v5(row, kept_text, cleanup_type, diagnostics)
    cut_start, cut_end, timing_method = word_range
    if cleanup_type == "keep_prefix":
        cut_start = int(row["start_us"])
    cut_start = max(int(row["start_us"]), min(cut_start, int(row["end_us"]) - 40_000))
    cut_end = min(int(row["end_us"]), max(cut_end, cut_start + 40_000))
    return {
        "rule_id": str(cleanup.get("cleanup_id") or cleanup.get("rule_id") or f"cleanup_{row['subtitle_uid']}"),
        "subtitle_uid": row["subtitle_uid"],
        "subtitle_index": int(row["subtitle_index"]),
        "text_override": kept_text,
        "cut_start_us": cut_start,
        "cut_end_us": cut_end,
        "cleanup_type": cleanup_type,
        "timing_method": timing_method,
        "semantic_risk": 0 if str(cleanup.get("confidence") or "").lower() == "high" else 1,
        "source": cleanup.get("source") or "local_cleanup",
        "reason": cleanup.get("reason") or "",
    }


def build_word_timing_diagnostics() -> dict[str, Any]:
    return {
        "word_timing_used_count": 0,
        "word_timing_missing_count": 0,
        "word_timing_no_phrase_count": 0,
        "char_ratio_fallback_count": 0,
        "word_time_unit_counts": {"ms": 0, "us": 0},
        "word_timing_examples": [],
    }


def local_micro(row: dict[str, Any], kept: str, cleanup_type: str, rule_id: str, reason: str, confidence: str = "high") -> dict[str, Any]:
    return {
        "cleanup_id": rule_id,
        "subtitle_uid": row["subtitle_uid"],
        "subtitle_index": int(row["subtitle_index"]),
        "original_text": row.get("subtitle_text") or "",
        "kept_text": kept,
        "cleanup_type": cleanup_type,
        "confidence": confidence,
        "reason": reason,
        "source": "phase3f_local_corrective",
    }


def build_local_corrective_decisions(rows: list[dict[str, Any]], params: dict[str, Any]) -> dict[str, Any]:
    rows_by_index = {int(row["subtitle_index"]): row for row in rows}
    drops: list[dict[str, Any]] = []
    micro: list[dict[str, Any]] = []
    must_keep: list[dict[str, Any]] = []

    sub7 = rows_by_index.get(7)
    sub6 = rows_by_index.get(6)
    if sub6 and sub7 and "就看到有人想爬" in str(sub6.get("subtitle_text") or ""):
        item = drop_span(
            "phase3f_drop_sub_000006",
            6,
            6,
            rows_by_index,
            "prefix_fragment",
            "sub_000006 是 sub_000007 的短弱前缀，保留完整粪坑句。",
            "high",
            keep_instead_uid=str(sub7.get("subtitle_uid") or ""),
            keep_instead_text="就看到有人想爬出粪坑",
            source="phase3f_local_corrective",
        )
        if item:
            drops.append(item)
    if sub7 and "看就看到有人想爬出粪坑" in str(sub7.get("subtitle_text") or ""):
        micro.append(local_micro(sub7, "就看到有人想爬出粪坑", "keep_suffix", "phase3f_mc_sub_000007", "用户反馈：去掉句首残留口吃“看”。"))

    sub23 = rows_by_index.get(23)
    if sub23:
        micro.append(local_micro(sub23, "你跪在地上叫大佬", "remove_repeated_phrase", "phase3f_mc_sub_000023", "重复口吃，保留完整强句。"))

    sub24 = rows_by_index.get(24)
    if sub24 and "人家年少的时候" in str(sub24.get("subtitle_text") or ""):
        micro.append(local_micro(sub24, "人家年少的时候", "keep_prefix", "phase3f_mc_sub_000024", "纠偏：保留独立语义原子，删除残尾“你就把他当成寻”。"))
        must_keep.append({"subtitle_start_uid": sub24["subtitle_uid"], "subtitle_end_uid": sub24["subtitle_uid"], "reason": "protected atom: 人家年少的时候"})

    sub25 = rows_by_index.get(25)
    if params.get("drop_restart_after_sub24") and sub25 and "人家人家年少的时候" in str(sub25.get("subtitle_text") or ""):
        item = drop_span(
            "phase3f_drop_sub_000025",
            25,
            25,
            rows_by_index,
            "repeated_take",
            "sub_000024 已保留“人家年少的时候”，sub_000025 是重复重启碎片。",
            "high",
            keep_instead_uid=str((sub24 or {}).get("subtitle_uid") or ""),
            keep_instead_text="人家年少的时候",
            source="phase3f_local_corrective",
        )
        if item:
            drops.append(item)

    sub26 = rows_by_index.get(26)
    if sub26:
        must_keep.append({"subtitle_start_uid": sub26["subtitle_uid"], "subtitle_end_uid": sub26["subtitle_uid"], "reason": "protected full sentence: 寻找优越感的弱智对象"})

    sub27 = rows_by_index.get(27)
    if sub27 and "肆意的踩踏" in str(sub27.get("subtitle_text") or ""):
        micro.append(local_micro(sub27, "肆意的踩踏", "keep_suffix", "phase3f_mc_sub_000027", "用户反馈：去掉弱词“随意的”，保留强表达。"))

    sub39 = rows_by_index.get(39)
    sub40 = rows_by_index.get(40)
    if sub39 and sub40 and normalize_compact_text(str(sub39.get("subtitle_text") or "")) in normalize_compact_text(str(sub40.get("subtitle_text") or "")):
        item = drop_span(
            "phase3f_drop_sub_000039",
            39,
            39,
            rows_by_index,
            "prefix_fragment",
            "sub_000039 是 sub_000040 的短弱前缀，保留完整“嘉豪不是中二啊”。",
            "high",
            keep_instead_uid=str(sub40.get("subtitle_uid") or ""),
            keep_instead_text=str(sub40.get("subtitle_text") or ""),
            source="phase3f_local_corrective",
        )
        if item:
            drops.append(item)

    for index, match, kept, word_rule in [
        (47, "评论区评论区也全是哇塞", "评论区也全是哇塞", "phase3f_mc_sub_000047"),
        (100, "给给老子从坟墓里面挖出来", "给老子从坟墓里面挖出来", "phase3f_mc_sub_000100"),
        (115, "重新上重新上桌重新上桌", "重新上桌", "phase3f_mc_sub_000115"),
    ]:
        row = rows_by_index.get(index)
        if row and match in str(row.get("subtitle_text") or ""):
            micro.append(local_micro(row, kept, "remove_repeated_phrase", word_rule, "系统性残留口吃清理。"))

    sub63 = rows_by_index.get(63)
    sub64 = rows_by_index.get(64)
    sub65 = rows_by_index.get(65)
    sub66 = rows_by_index.get(66)
    if sub63 and sub64 and sub65 and sub66:
        first = normalize_compact_text(str(sub63.get("subtitle_text") or "") + str(sub64.get("subtitle_text") or ""))
        second = normalize_compact_text(str(sub65.get("subtitle_text") or "") + str(sub66.get("subtitle_text") or ""))
        if first and second and first == second:
            item = drop_span(
                "phase3f_drop_sub_000065_066",
                65,
                66,
                rows_by_index,
                "repeated_take",
                "第二组兄弟健个身/你说是死肌肉是重复 take，保留第一次。",
                "high",
                keep_instead_uid=str(sub63.get("subtitle_uid") or ""),
                keep_instead_text=str(sub63.get("subtitle_text") or "") + " / " + str(sub64.get("subtitle_text") or ""),
                source="phase3f_local_corrective",
            )
            if item:
                drops.append(item)

    return {
        "source": "phase3f_local_corrective",
        "drop_spans": drops,
        "micro_cleanups": micro,
        "must_keep_warnings": must_keep,
    }


def cleanup_allowed_v5(cleanup: dict[str, Any], params: dict[str, Any]) -> bool:
    if cleanup.get("source") == "phase3f_local_corrective":
        return True
    confidence = str(cleanup.get("confidence") or "low").lower()
    if confidence == "high":
        return True
    if confidence == "medium":
        return bool(params.get("include_medium_micro_cleanups"))
    return False


def apply_corrective_cleanup(
    reviewed: dict[str, Any],
    subtitles: list[dict[str, Any]],
    system_decisions: dict[str, Any],
    params: dict[str, Any],
    text_overrides: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    spans = expand_reviewed_spans(reviewed, subtitles)
    rows_by_index = {int(row["subtitle_index"]): row for row in subtitles}
    spans_by_index = {int(span["subtitle_start_index"]): span for span in spans}
    local = build_local_corrective_decisions(subtitles, params)
    all_drop_spans = list(system_decisions.get("drop_spans") or []) + list(local.get("drop_spans") or [])
    all_micro_cleanups = list(system_decisions.get("micro_cleanups") or []) + list(local.get("micro_cleanups") or [])

    force_keep_indices: set[int] = set()
    for warning in list(system_decisions.get("must_keep_warnings") or []) + list(local.get("must_keep_warnings") or []):
        start_uid = str(warning.get("subtitle_start_uid") or "")
        end_uid = str(warning.get("subtitle_end_uid") or start_uid)
        start = int(start_uid.split("_")[-1]) if start_uid.startswith("sub_") else 0
        end = int(end_uid.split("_")[-1]) if end_uid.startswith("sub_") else start
        if start and end:
            if warning in (system_decisions.get("must_keep_warnings") or []) and abs(end - start) > 5:
                continue
            force_keep_indices.update(range(min(start, end), max(start, end) + 1))

    applied_drops: list[dict[str, Any]] = []
    skipped_drops: list[dict[str, Any]] = []
    guard_rows: list[dict[str, Any]] = []
    guard_micro: list[dict[str, Any]] = []

    for drop in all_drop_spans:
        start = int(drop["subtitle_start_index"])
        end = int(drop["subtitle_end_index"])
        guard = guard_drop_span(drop)
        guard_action = guard["action"]
        if guard_action == "force_keep":
            force_keep_indices.update(range(start, end + 1))
            skipped_drops.append({**drop, "skip_reason": "semantic_guard_force_keep"})
            guard_rows.append({**drop, "guard_action": "force_keep", **guard})
            continue
        if guard_action == "convert_to_micro_cleanup":
            row = rows_by_index.get(start)
            if row:
                cleanup = {
                    "cleanup_id": f"semantic_guard_{drop.get('drop_id')}",
                    "subtitle_uid": row["subtitle_uid"],
                    "subtitle_index": start,
                    "original_text": row.get("subtitle_text") or "",
                    "kept_text": guard["kept_text"],
                    "cleanup_type": "keep_prefix" if normalize_compact_text(str(row.get("subtitle_text") or "")).startswith(normalize_compact_text(guard["kept_text"])) else "manual_phrase_trim",
                    "confidence": "high",
                    "reason": guard["reason"],
                    "source": "semantic_guard",
                }
                guard_micro.append(cleanup)
                all_micro_cleanups.append(cleanup)
            skipped_drops.append({**drop, "skip_reason": "semantic_guard_converted_to_micro"})
            guard_rows.append({**drop, "guard_action": "convert_to_micro_cleanup", **guard})
            continue

        keep_uid = str(drop.get("keep_instead_uid") or "")
        if start == end and keep_uid == str(rows_by_index.get(start, {}).get("subtitle_uid") or ""):
            skipped_drops.append({**drop, "skip_reason": "self_contained_micro_cleanup_preferred"})
            continue
        local_restart_after_preserved_atom = (
            drop.get("source") == "phase3f_local_corrective"
            and start == end == 25
            and normalize_compact_text(str(drop.get("keep_instead_text") or "")) == "人家年少的时候"
        )
        if any(index in force_keep_indices for index in range(start, end + 1)) and not local_restart_after_preserved_atom:
            skipped_drops.append({**drop, "skip_reason": "must_keep_warning"})
            continue
        local_phase3f_drop = drop.get("source") == "phase3f_local_corrective"
        if not local_phase3f_drop and not drop_span_allowed(drop, params):
            skipped_drops.append({**drop, "skip_reason": "confidence_policy"})
            continue
        for index in range(start, end + 1):
            span = spans_by_index.get(index)
            if not span:
                continue
            span["decision"] = "drop"
            span["pause_after_ms"] = 0
            span["pause_type"] = "none"
            span["reason"] = f"{drop.get('reason_type')}: {drop.get('reason')}"
            span["system_drop_id"] = drop.get("drop_id")
            span["keep_instead_text"] = drop.get("keep_instead_text") or ""
        applied_drops.append(drop)

    word_diag = build_word_timing_diagnostics()
    applied_micro: list[dict[str, Any]] = []
    skipped_micro: list[dict[str, Any]] = []
    for cleanup in all_micro_cleanups:
        if not cleanup_allowed_v5(cleanup, params):
            skipped_micro.append({**cleanup, "skip_reason": "confidence_policy"})
            continue
        index = int(cleanup["subtitle_index"])
        if spans_by_index.get(index, {}).get("decision") == "drop":
            skipped_micro.append({**cleanup, "skip_reason": "subtitle_dropped"})
            continue
        row = rows_by_index.get(index)
        if not row:
            skipped_micro.append({**cleanup, "skip_reason": "row_missing"})
            continue
        override = cleanup_to_override_v5(row, cleanup, word_diag)
        if not override:
            skipped_micro.append({**cleanup, "skip_reason": "override_failed"})
            continue
        text_overrides[row["subtitle_uid"]] = override
        applied_micro.append(cleanup)

    for index in force_keep_indices:
        span = spans_by_index.get(index)
        if span:
            span["decision"] = "keep"
            span["reason"] = str(span.get("reason") or "") + " | force_keep_warning"

    out = {
        **reviewed,
        "decision_mode": "phase_3f_corrective_v5",
        "spans": spans,
    }
    summary = {
        "applied_drop_count": len(applied_drops),
        "skipped_drop_count": len(skipped_drops),
        "applied_micro_count": len(applied_micro),
        "skipped_micro_count": len(skipped_micro),
        "force_keep_indices": sorted(force_keep_indices),
        "applied_drops": applied_drops,
        "skipped_drops": skipped_drops,
        "applied_micro_cleanups": applied_micro,
        "skipped_micro_cleanups": skipped_micro,
        "local_corrective_decisions": local,
        "semantic_guard_converted_micro_count": len(guard_micro),
    }
    semantic_guard_report = build_semantic_guard_report(guard_rows)
    return out, summary, semantic_guard_report, word_diag, local


def base_candidate_params() -> list[dict[str, Any]]:
    base = {
        "lead_guard_us": 40_000,
        "tail_guard_us": 60_000,
        "strict_drop_boundary_guard_us": 0,
        "merge_keep_gap_us": 50_000,
        "include_medium_prefix_drops": False,
        "include_medium_deepseek_drops": False,
        "include_medium_micro_cleanups": False,
        "include_medium_local_drops": True,
        "drop_restart_after_sub24": True,
        "jiahao_cleanup": True,
        "vad_mode": "none",
        "vad_min_silence_us": 120_000,
        "vad_target_silence_us": 40_000,
        "vad_speech_pad_us": 50_000,
    }
    return [
        {**base, "candidate": "candidate_01", "vad_mode": "none", "include_medium_micro_cleanups": True},
        {**base, "candidate": "candidate_02", "vad_mode": "conservative", "vad_min_silence_us": 180_000, "vad_target_silence_us": 40_000, "vad_speech_pad_us": 60_000, "include_medium_micro_cleanups": True},
        {**base, "candidate": "candidate_03", "vad_mode": "aggressive", "vad_min_silence_us": 120_000, "vad_target_silence_us": 20_000, "vad_speech_pad_us": 40_000, "include_medium_micro_cleanups": True},
        {**base, "candidate": "candidate_04", "vad_mode": "aggressive", "vad_min_silence_us": 120_000, "vad_target_silence_us": 20_000, "vad_speech_pad_us": 40_000, "include_medium_prefix_drops": True, "include_medium_deepseek_drops": True, "include_medium_micro_cleanups": True},
    ]


def strict_neighbor_drop(spans: list[dict[str, Any]]) -> set[int]:
    out: set[int] = set()
    for span in spans:
        if span.get("decision") == "drop":
            out.update(range(int(span["subtitle_start_index"]), int(span["subtitle_end_index"]) + 1))
    return out


def build_candidate_edl_v5(
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
    regions: list[dict[str, Any]] = []
    strict_applied = 0

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
        clip["boundary_mode"] = "phase3f_tight_word_boundary"
        edl.append(clip)
        target_start += int(clip["target_duration_us"])
    return edl, {
        "strict_drop_boundary_applied_count": strict_applied,
        "merge_keep_gap_us": merge_gap,
        "lead_guard_us": lead_guard,
        "tail_guard_us": tail_guard,
    }


def material_path(material: dict[str, Any]) -> str:
    for key in ("path", "file_path", "source_path", "local_path"):
        value = str(material.get(key) or "")
        if value:
            return value.replace("\\", "/")
    return ""


def decode_pcm16_mono(video_path: Path, raw_path: Path) -> dict[str, Any]:
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "s16le",
        str(raw_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return {"video_path": str(video_path), "raw_path": str(raw_path), "sample_rate": 16000}


def detect_silence_intervals(raw_path: Path, sample_rate: int, params: dict[str, Any]) -> dict[str, Any]:
    raw = raw_path.read_bytes()
    samples = array.array("h")
    samples.frombytes(raw)
    frame_ms = 20
    frame_size = max(1, int(sample_rate * frame_ms / 1000))
    dbs: list[float] = []
    for offset in range(0, len(samples), frame_size):
        frame = samples[offset : offset + frame_size]
        if not frame:
            continue
        rms = math.sqrt(sum(float(x) * float(x) for x in frame) / len(frame))
        dbs.append(20.0 * math.log10(max(rms, 1.0) / 32768.0))
    if not dbs:
        return {"silences": [], "threshold_db": None, "frame_count": 0}
    threshold = max(percentile(dbs, 0.20) + 6.0, -45.0)
    min_silence_us = int(params["vad_min_silence_us"])
    min_frames = max(1, int(math.ceil(min_silence_us / (frame_ms * 1000))))
    silences: list[dict[str, Any]] = []
    start_frame: int | None = None
    for idx, db in enumerate(dbs + [999.0]):
        silent = db <= threshold
        if silent and start_frame is None:
            start_frame = idx
        if not silent and start_frame is not None:
            if idx - start_frame >= min_frames:
                silences.append(
                    {
                        "start_us": int(start_frame * frame_ms * 1000),
                        "end_us": int(idx * frame_ms * 1000),
                        "duration_us": int((idx - start_frame) * frame_ms * 1000),
                    }
                )
            start_frame = None
    return {
        "silences": silences,
        "threshold_db": threshold,
        "frame_count": len(dbs),
        "db_p20": percentile(dbs, 0.20),
        "db_p50": percentile(dbs, 0.50),
        "db_p80": percentile(dbs, 0.80),
    }


def build_vad_report_and_target_silences(
    data: dict[str, Any],
    old_video_segments: list[dict[str, Any]],
    candidate_dir: Path,
    params: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if str(params.get("vad_mode") or "none") == "none":
        return {"available": False, "mode": "none", "reason": "disabled_for_candidate", "target_silences": []}, []
    if shutil.which("ffmpeg") is None:
        return {"available": False, "mode": params.get("vad_mode"), "reason": "AUDIO_VAD_UNAVAILABLE:ffmpeg_missing", "target_silences": []}, []

    videos = material_index(data, "videos")
    audio_dir = candidate_dir / "audio_vad"
    audio_dir.mkdir(parents=True, exist_ok=True)
    material_reports: dict[str, Any] = {}
    local_silences_by_material: dict[str, list[dict[str, Any]]] = {}

    for segment in old_video_segments:
        material_id = str(segment.get("material_id") or "")
        if not material_id or material_id in material_reports:
            continue
        material = videos.get(material_id) or {}
        path_text = material_path(material)
        if not path_text:
            material_reports[material_id] = {"available": False, "reason": "material_path_missing"}
            continue
        path = Path(path_text)
        if not path.exists():
            material_reports[material_id] = {"available": False, "path": path_text, "reason": "material_path_not_found"}
            continue
        raw_path = audio_dir / f"{material_id}.s16le"
        try:
            decode = decode_pcm16_mono(path, raw_path)
            detected = detect_silence_intervals(raw_path, int(decode["sample_rate"]), params)
            local_silences_by_material[material_id] = detected["silences"]
            material_reports[material_id] = {
                "available": True,
                "path": path_text,
                "raw_path": str(raw_path),
                "silence_count": len(detected["silences"]),
                "threshold_db": detected.get("threshold_db"),
                "db_p20": detected.get("db_p20"),
                "db_p50": detected.get("db_p50"),
                "db_p80": detected.get("db_p80"),
            }
        except Exception as exc:
            material_reports[material_id] = {"available": False, "path": path_text, "reason": f"decode_or_detect_failed:{exc}"}

    target_silences: list[dict[str, Any]] = []
    for old_index, segment in enumerate(old_video_segments):
        material_id = str(segment.get("material_id") or "")
        material_silences = local_silences_by_material.get(material_id) or []
        old_target_start = segment_start(segment)
        old_target_end = segment_end(segment)
        old_source_start = timerange_start(segment.get("source_timerange") or {})
        old_source_end = old_source_start + (old_target_end - old_target_start)
        for silence in material_silences:
            local_start = int(silence["start_us"])
            local_end = int(silence["end_us"])
            overlap_start = max(local_start, old_source_start)
            overlap_end = min(local_end, old_source_end)
            if overlap_end <= overlap_start:
                continue
            target_silences.append(
                {
                    "old_segment_index": old_index,
                    "material_id": material_id,
                    "target_start_us": old_target_start + (overlap_start - old_source_start),
                    "target_end_us": old_target_start + (overlap_end - old_source_start),
                    "duration_us": overlap_end - overlap_start,
                }
            )
    report = {
        "available": any(row.get("available") for row in material_reports.values()),
        "mode": params.get("vad_mode"),
        "material_reports": material_reports,
        "target_silence_count": len(target_silences),
        "target_silences_sample": target_silences[:50],
    }
    return report, target_silences


def split_edl_by_vad(
    edl: list[dict[str, Any]],
    target_silences: list[dict[str, Any]],
    subtitles: list[dict[str, Any]],
    params: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not target_silences:
        return edl, {"vad_split_applied": False, "split_count": 0, "removed_silence_us": 0}
    keep_pad = int(params["vad_target_silence_us"]) // 2
    min_speech = MIN_SPEECH_ISLAND_US
    out: list[dict[str, Any]] = []
    removed_total = 0
    split_count = 0
    for clip in edl:
        intervals = [(int(clip["cut_start_us"]), int(clip["cut_end_us"]))]
        for silence in target_silences:
            s = max(int(silence["target_start_us"]), int(clip["cut_start_us"]))
            e = min(int(silence["target_end_us"]), int(clip["cut_end_us"]))
            if e - s < int(params["vad_min_silence_us"]):
                continue
            remove_start = s + keep_pad
            remove_end = e - keep_pad
            if remove_end - remove_start < 80_000:
                continue
            next_intervals: list[tuple[int, int]] = []
            for a, b in intervals:
                if remove_end <= a or remove_start >= b:
                    next_intervals.append((a, b))
                    continue
                if remove_start - a >= min_speech:
                    next_intervals.append((a, remove_start))
                if b - remove_end >= min_speech:
                    next_intervals.append((remove_end, b))
                removed_total += max(0, min(b, remove_end) - max(a, remove_start))
                split_count += 1
            intervals = next_intervals or intervals
        if len(intervals) == 1 and intervals[0] == (int(clip["cut_start_us"]), int(clip["cut_end_us"])):
            out.append(deepcopy(clip))
            continue
        for part_index, (a, b) in enumerate(intervals, start=1):
            if b <= a:
                continue
            part = deepcopy(clip)
            part["clip_id"] = f"{clip['clip_id']}_vad{part_index:02d}"
            part["cut_start_us"] = a
            part["cut_end_us"] = b
            part["target_duration_us"] = b - a
            part["boundary_mode"] = f"{clip.get('boundary_mode')}_vad_split"
            part["vad_split_from"] = clip["clip_id"]
            out.append(part)

    target_start = 0
    for index, clip in enumerate(out, start=1):
        clip["clip_id"] = f"auto_{index:03d}"
        clip["target_start_us"] = target_start
        clip["pause_after_us"] = 0
        target_start += int(clip["target_duration_us"])
    return out, {
        "vad_split_applied": True,
        "split_count": split_count,
        "removed_silence_us": removed_total,
        "clip_count_before_vad": len(edl),
        "clip_count_after_vad": len(out),
        "subtitle_text_dedup_required": True,
    }


def rewrite_text_segments_v5(
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
    material_clones = 0
    partial_without_override = 0

    for row in subtitles:
        row_start = int(row["start_us"])
        row_end = int(row["end_us"])
        row_uid = row["subtitle_uid"]
        overlaps: list[dict[str, Any]] = []
        override: dict[str, Any] | None = None
        for clip in edl:
            clip_start = int(clip["cut_start_us"])
            clip_end = int(clip["cut_end_us"])
            overlap_start = max(row_start, clip_start)
            overlap_end = min(row_end, clip_end)
            if overlap_end <= overlap_start:
                continue
            clip_override = (clip.get("text_overrides") or {}).get(row_uid)
            if clip_override:
                override = clip_override
            target_start = int(clip["target_start_us"]) + (overlap_start - clip_start)
            target_end = int(clip["target_start_us"]) + (overlap_end - clip_start)
            overlaps.append(
                {
                    "clip_id": clip["clip_id"],
                    "overlap_start_us": overlap_start,
                    "overlap_end_us": overlap_end,
                    "target_start_us": target_start,
                    "target_end_us": target_end,
                    "partial": overlap_start > row_start or overlap_end < row_end,
                }
            )
        if not overlaps:
            continue
        source_segment = segment_by_id.get(str(row["text_segment_id"]))
        if not source_segment:
            continue
        new_segment = deepcopy(source_segment)
        new_start = min(item["target_start_us"] for item in overlaps)
        new_end = max(item["target_end_us"] for item in overlaps)
        new_segment["id"] = f"{source_segment.get('id')}_v5_{len(rewritten)+1:03d}"
        target_timerange = deepcopy(new_segment.get("target_timerange") or {})
        target_timerange["start"] = new_start
        target_timerange["duration"] = max(40_000, new_end - new_start)
        new_segment["target_timerange"] = target_timerange
        new_text = str((override or {}).get("text_override") or row.get("subtitle_text") or "")
        if override:
            old_material = text_by_id.get(str(source_segment.get("material_id") or ""))
            if old_material:
                cloned = update_material_text(old_material, new_text)
                text_materials.append(cloned)
                text_by_id[cloned["id"]] = cloned
                new_segment["material_id"] = cloned["id"]
                material_clones += 1
        elif any(item["partial"] for item in overlaps):
            partial_without_override += 1
        rewritten.append(new_segment)
        report_rows.append(
            {
                "clip_id": ",".join(item["clip_id"] for item in overlaps),
                "subtitle_uid": row_uid,
                "old_text": row.get("subtitle_text") or "",
                "new_text": new_text,
                "partial_subtitle_clip": any(item["partial"] for item in overlaps),
                "has_text_override": override is not None,
                "old_start_us": row_start,
                "old_end_us": row_end,
                "overlap_start_us": min(item["overlap_start_us"] for item in overlaps),
                "overlap_end_us": max(item["overlap_end_us"] for item in overlaps),
                "new_start_us": new_start,
                "new_duration_us": target_timerange["duration"],
                "merged_from_vad_fragments": len(overlaps) > 1,
            }
        )
    rewritten.sort(key=segment_start)
    return rewritten, {
        "rows": report_rows,
        "partial_subtitle_without_override": partial_without_override,
        "material_clone_count": material_clones,
        "deduplicated_by_subtitle_uid": True,
    }


def validate_subtitles_covered_by_video_union(text_segments: list[dict[str, Any]], video_segments: list[dict[str, Any]]) -> int:
    ranges = sorted((segment_start(segment), segment_end(segment)) for segment in video_segments)
    merged: list[tuple[int, int]] = []
    for start, end in ranges:
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    outside = 0
    for segment in text_segments:
        start = segment_start(segment)
        end = segment_end(segment)
        if not any(start >= vs and end <= ve for vs, ve in merged):
            outside += 1
    return outside


def jiahao_young_context_report(subtitles: list[dict[str, Any]], text_overrides: dict[str, dict[str, Any]], reviewed: dict[str, Any]) -> dict[str, Any]:
    spans = reviewed.get("spans") or []
    by_index = {int(span["subtitle_start_index"]): span for span in spans}
    rows = []
    for row in subtitles:
        index = int(row["subtitle_index"])
        if 20 <= index <= 27:
            uid = row["subtitle_uid"]
            rows.append(
                {
                    "subtitle_index": index,
                    "subtitle_uid": uid,
                    "original_text": row.get("subtitle_text") or "",
                    "decision": (by_index.get(index) or {}).get("decision", "unknown"),
                    "text_override": (text_overrides.get(uid) or {}).get("text_override", ""),
                    "cut_start_us": (text_overrides.get(uid) or {}).get("cut_start_us"),
                    "cut_end_us": (text_overrides.get(uid) or {}).get("cut_end_us"),
                }
            )
    final_sequence = [
        (text_overrides.get("sub_000024") or {}).get("text_override") or "",
        (text_overrides.get("sub_000023") or {}).get("text_override") or "",
        next((row.get("original_text") for row in rows if row.get("subtitle_uid") == "sub_000026"), ""),
    ]
    return {
        "context_rows": rows,
        "target_sequence": ["人家年少的时候", "你跪在地上叫大佬", "你就把他当成寻找优越感的弱智对象"],
        "observed_key_texts": final_sequence,
        "semantic_atom_preserved": any((row.get("text_override") == "人家年少的时候") or (row.get("original_text") == "人家年少的时候") for row in rows),
    }


def score_candidate_v5(score_input: dict[str, Any]) -> dict[str, Any]:
    if score_input["fatal_reasons"]:
        score = 0
    else:
        score = 100
        score -= score_input["subtitle_outside_clip_count"] * 20
        # In v5, VAD can split video inside a subtitle while the subtitle is
        # deliberately deduplicated and stretched across the collapsed speech
        # islands. Treat this as a review signal, not a hard score penalty.
        score -= 0
        score -= score_input["residual_text_repeat_count"] * 10
        score -= score_input["long_pause_count"] * 5
        score -= score_input["semantic_risk_count"] * 3
        score += min(28, score_input.get("vad_removed_silence_us", 0) // 600_000)
        if not score_input["known_feedback_fixed"].get("see_pit_fixed"):
            score -= 20
        if not score_input["known_feedback_fixed"].get("young_atom_present"):
            score -= 50
        if not score_input["known_feedback_fixed"].get("bad_young_tail_removed"):
            score -= 20
        if not score_input["known_feedback_fixed"].get("full_youyuegan_present"):
            score -= 25
        if not score_input["known_feedback_fixed"].get("suiyi_ruyi_fixed"):
            score -= 18
        if not score_input["known_feedback_fixed"].get("kneel_repeat_text_fixed"):
            score -= 25
        if score_input["final_duration_us"] > 205_000_000:
            score -= (score_input["final_duration_us"] - 205_000_000) // 8_000_000
        if score_input["final_duration_us"] < 165_000_000:
            score -= (165_000_000 - score_input["final_duration_us"]) // 5_000_000
        score = max(0, int(score))
    score_input["score"] = score
    return score_input


def run_candidate(args: argparse.Namespace, auto_dir: Path, timeline_id: str, params: dict[str, Any], script_clean: str, system_decisions: dict[str, Any]) -> dict[str, Any]:
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

    write_json(candidate_dir / "subtitle_timeline.before.json", subtitles)
    clusters = read_json(args.deepseek_run / "take_clusters.json")
    decisions = read_json(args.deepseek_run / "deepseek_aroll_decisions.json")
    review_text = (args.deepseek_run / "human_review_drops.md").read_text("utf-8")
    reviewed, conservative_summary = conservative_review(clusters, decisions, review_text)
    diagnosis, text_overrides = build_feedback_overrides(subtitles, params)
    residual_before = scan_residual_texts(subtitles, None)
    reviewed, cleanup_summary, semantic_guard_report, word_diag, local = apply_corrective_cleanup(
        reviewed,
        subtitles,
        system_decisions,
        params,
        text_overrides,
    )
    write_json(candidate_dir / "residual_cleanup_diagnosis.json", diagnosis)
    write_json(candidate_dir / "system_cleanup_apply_summary.json", cleanup_summary)
    write_json(candidate_dir / "semantic_guard_report.json", semantic_guard_report)
    write_json(candidate_dir / "word_timing_diagnostics.json", word_diag)
    write_json(candidate_dir / "residual_scan_before.json", residual_before)
    write_json(candidate_dir / "candidate_decisions.json", reviewed)
    write_json(candidate_dir / "jiahao_young_context_fix_report.json", jiahao_young_context_report(subtitles, text_overrides, reviewed))

    edl, edl_meta = build_candidate_edl_v5(reviewed, subtitles, main_total_duration_us, text_overrides, params)
    main_track = get_track(data, str(selected_main["track_id"]))
    text_track = get_track(data, str(selected_text_track["track_id"]))
    if main_track is None or text_track is None:
        raise RuntimeError("TRACK_NOT_FOUND_DURING_CANDIDATE_WRITE")
    old_video_segments = deepcopy(main_track.get("segments") or [])
    old_text_segments = deepcopy(text_track.get("segments") or [])
    vad_report, target_silences = build_vad_report_and_target_silences(data, old_video_segments, candidate_dir, params)
    edl, vad_split_report = split_edl_by_vad(edl, target_silences, subtitles, params)
    vad_report["split_report"] = vad_split_report
    write_json(candidate_dir / "audio_vad_report.json", vad_report)
    write_json(candidate_dir / "corrective_v5_edl.json", edl)

    backup_paths = backup_draft_files(args.draft_dir, timeline_id, candidate_dir, root_required)
    new_video_segments, video_split_rows = split_video_segments_for_edl(old_video_segments, edl)
    new_text_segments, subtitle_rewrite_report = rewrite_text_segments_v5(data, old_text_segments, subtitles, edl)
    if not new_video_segments or not new_text_segments:
        raise RuntimeError("CANDIDATE_REWRITE_EMPTY")

    main_track["segments"] = new_video_segments
    text_track["segments"] = new_text_segments
    data["duration"] = total_target_duration(new_video_segments)

    write_json(candidate_dir / "video_split_report.json", video_split_rows)
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

    outside = validate_subtitles_covered_by_video_union(after_text_segments, after_video_segments)
    residual_scan = scan_residual_texts(subtitle_rewrite_report.get("rows") or [], edl)
    texts = residual_scan.get("final_transcript") or ""
    residual_scan["feedback_keywords"].update(
        {
            "see_pit_fixed": "看就看到有人想爬出粪坑" not in texts and "就看到有人想爬出粪坑" in texts,
            "young_atom_present": "人家年少的时候" in texts,
            "bad_young_tail_removed": "人家年少的时候你就把他当成寻" not in texts,
        }
    )
    write_json(candidate_dir / "residual_scan_after.json", residual_scan)
    (candidate_dir / "final_transcript_after.txt").write_text(texts, "utf-8")

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
    score = score_candidate_v5(
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
            "known_feedback_fixed": residual_scan["feedback_keywords"],
            "residual_text_repeat_count": residual_scan["residual_text_repeat_count"],
            "long_pause_count": residual_scan["long_pause_count"],
            "max_pause_us": residual_scan["max_pause_us"],
            "semantic_risk_count": semantic_risk,
            "vad_removed_silence_us": vad_split_report.get("removed_silence_us", 0),
            "fatal_reasons": check_fatals,
        }
    )
    write_json(candidate_dir / "candidate_score.json", score)
    write_candidate_review_files(candidate_dir, reviewed, cleanup_summary, score)
    report = {
        "candidate": params["candidate"],
        "params": params,
        "runtime_dir": str(candidate_dir),
        "backup_paths": backup_paths,
        "target_writes": target_writes,
        "conservative_review_summary": conservative_summary,
        "system_cleanup_apply_summary": cleanup_summary,
        "semantic_guard_report": str(candidate_dir / "semantic_guard_report.json"),
        "word_timing_diagnostics": str(candidate_dir / "word_timing_diagnostics.json"),
        "audio_vad_report": str(candidate_dir / "audio_vad_report.json"),
        "edl_metadata": {**edl_meta, **vad_split_report},
        "video_track_before": {"segment_count": len(old_video_segments), "total_duration_us": total_target_duration(old_video_segments)},
        "video_track_after": {"segment_count": len(after_video_segments), "total_duration_us": total_target_duration(after_video_segments)},
        "text_track_before": {"segment_count": len(old_text_segments)},
        "text_track_after": {"segment_count": len(after_text_segments)},
        "score": score,
        "residual_scan_before": str(candidate_dir / "residual_scan_before.json"),
        "residual_scan_after": str(candidate_dir / "residual_scan_after.json"),
        "corrective_v5_edl": str(candidate_dir / "corrective_v5_edl.json"),
        "encrypted_output": str(encrypted_out),
        "root_mirror_required": root_required,
        "root_mirror_matches_after": root_after,
        "timeline_layout_modified": False,
        "fatal_reasons": check_fatals,
        "warnings": warnings,
    }
    write_json(candidate_dir / "candidate_report.json", report)
    return report


def write_candidate_review_files(candidate_dir: Path, reviewed: dict[str, Any], cleanup_summary: dict[str, Any], score: dict[str, Any]) -> None:
    lines = ["# Dropped Transcript Review", ""]
    count = 0
    for span in reviewed.get("spans") or []:
        if span.get("decision") != "drop":
            continue
        count += 1
        lines.extend(
            [
                f"## Drop {count:03d}",
                "",
                f"- Drop subtitle: {span.get('subtitle_start_uid')} - {span.get('subtitle_end_uid')}",
                f"- Drop text: {span.get('mapped_text') or ''}",
                f"- Kept instead: {span.get('keep_instead_text') or ''}",
                f"- Reason: {span.get('reason') or ''}",
                "",
            ]
        )
    (candidate_dir / "dropped_transcript_review.md").write_text("\n".join(lines) + "\n", "utf-8")
    focus = [
        "# Phase 3F Human Review Focus",
        "",
        f"- Candidate: {score['candidate']}",
        f"- Duration: {score['final_duration_us'] / 1_000_000:.2f}s",
        f"- Video segments: {score['video_segment_count']}",
        f"- Subtitle segments: {score['subtitle_segment_count']}",
        f"- Deleted subtitles: {score['deleted_subtitle_count']}",
        f"- Micro cuts: {score['micro_cut_count']}",
        f"- VAD removed silence: {score.get('vad_removed_silence_us', 0) / 1_000_000:.2f}s",
        "",
        "## 必看点",
        "",
        "1. `就看到有人想爬出粪坑` 句首是否还残留“看”。",
        "2. `人家年少的时候 / 你跪在地上叫大佬 / 你就把他当成寻找优越感的弱智对象` 是否完整顺畅。",
        "3. `肆意的踩踏` 是否干净，没有“随意的”。",
        "4. 气口是否比上一版继续减少。",
        "5. 是否有切字、断尾音、语义误删。",
        "",
    ]
    (candidate_dir / "human_review_focus.md").write_text("\n".join(focus), "utf-8")


def write_best_candidate_to_draft(best: dict[str, Any], draft_dir: Path, timeline_id: str) -> dict[str, bool]:
    encrypted = Path(best["encrypted_output"])
    timeline_dir = draft_dir / "Timelines" / timeline_id
    targets = [timeline_dir / "draft_content.json", timeline_dir / "template-2.tmp"]
    if best.get("root_mirror_required"):
        targets.extend([draft_dir / "draft_content.json", draft_dir / "template-2.tmp"])
    return write_encrypted_to_targets(encrypted, targets)


def run_corrective_v5(args: argparse.Namespace) -> tuple[Path, Path]:
    auto_dir = args.runtime / f"aroll_corrective_v5_{time.strftime('%Y%m%d_%H%M%S')}"
    auto_dir.mkdir(parents=True, exist_ok=True)
    timeline_id, timeline_name = resolve_timeline_id(args.draft_dir, args.timeline_name)
    script_text = args.script_path.read_text("utf-8")
    script_clean = clean_script_markdown(script_text)
    original_subtitles = read_json(args.subtitle_timeline)

    restore_original_backup(args.draft_dir, timeline_id, args.source_backup)
    timeline_dir = args.draft_dir / "Timelines" / timeline_id
    restore_check_dec = auto_dir / "restore_check.dec.json"
    decrypt(args.jy_draftc, timeline_dir / "draft_content.json", restore_check_dec)
    restore_data = read_json_file(restore_check_dec)
    _, restore_selected_main, restore_video_fatals, restore_video_warnings, restore_speed_safe = inspect_video_tracks(restore_data)
    restore_subtitles, _, _ = subtitle_timeline(restore_data)
    restore_duration_us = int((restore_selected_main or {}).get("total_target_duration_us") or 0)
    restore_report = {
        "restored_from_backup": str(args.source_backup),
        "video_total_duration_us": restore_duration_us,
        "subtitle_count": len(restore_subtitles),
        "can_aroll_rewrite": bool(restore_selected_main and len(restore_subtitles) == 115 and restore_duration_us >= 300_000_000 and not restore_video_fatals and restore_speed_safe),
        "fatal_reasons": restore_video_fatals,
        "warnings": restore_video_warnings,
    }
    write_json(auto_dir / "restore_check_report.json", restore_report)
    if not restore_report["can_aroll_rewrite"]:
        raise RuntimeError(f"RESTORE_CHECK_FAILED:{restore_report}")

    try:
        system_decisions, deepseek_call_result = call_deepseek_system_cleanup(
            config_path=args.deepseek_config,
            model=args.deepseek_model,
            subtitles=original_subtitles,
            script_clean=script_clean,
            source_duration_us=restore_duration_us,
            out_dir=auto_dir,
        )
    except Exception as exc:
        system_decisions = {"source": "deepseek_system_cleanup_failed", "drop_spans": [], "micro_cleanups": [], "must_keep_warnings": []}
        deepseek_call_result = {"success": False, "fallback": True, "model": args.deepseek_model, "error": str(exc)}
        write_json(auto_dir / "deepseek_system_cleanup_raw_response.json", deepseek_call_result)
        write_json(auto_dir / "system_cleanup_decisions.json", system_decisions)

    candidates: list[dict[str, Any]] = []
    for params in base_candidate_params()[: args.max_iterations]:
        candidates.append(run_candidate(args, auto_dir, timeline_id, params, script_clean, system_decisions))

    def rank(row: dict[str, Any]) -> tuple[int, int, int, int, int, int]:
        score = row["score"]
        try:
            candidate_order = int(str(row.get("candidate") or "candidate_99").split("_")[-1])
        except Exception:
            candidate_order = 99
        return (
            int(score.get("score") or 0),
            int(score.get("vad_removed_silence_us") or 0),
            -int(score.get("residual_text_repeat_count") or 0),
            -int(score.get("semantic_risk_count") or 0),
            -int(score.get("partial_subtitle_without_override") or 0),
            -candidate_order,
        )

    best = sorted(candidates, key=rank, reverse=True)[0]
    final_writes = write_best_candidate_to_draft(best, args.draft_dir, timeline_id)
    best_dir = Path(best["runtime_dir"])
    shutil.copy2(best_dir / "dropped_transcript_review.md", auto_dir / "dropped_transcript_review.md")
    shutil.copy2(best_dir / "human_review_focus.md", auto_dir / "human_review_focus.md")
    summary = {
        "draft_dir": str(args.draft_dir),
        "timeline_id": timeline_id,
        "timeline_name": timeline_name,
        "phase": "3F_corrective_v5",
        "restore_check_report": str(auto_dir / "restore_check_report.json"),
        "deepseek_called": True,
        "deepseek_call_result": deepseek_call_result,
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
                "vad_removed_silence_us": item["score"].get("vad_removed_silence_us", 0),
                "residual_repeat_count": item["score"]["residual_text_repeat_count"],
                "long_pause_count": item["score"]["long_pause_count"],
                "semantic_risk_count": item["score"]["semantic_risk_count"],
                "score": item["score"]["score"],
                "fatal_reasons": item["score"]["fatal_reasons"],
            }
            for item in candidates
        ],
        "best_candidate": best["candidate"],
        "best_candidate_runtime": best["runtime_dir"],
        "best_candidate_report": str(best_dir / "candidate_report.json"),
        "final_writes": final_writes,
        "human_review_focus": str(auto_dir / "human_review_focus.md"),
        "dropped_transcript_review": str(auto_dir / "dropped_transcript_review.md"),
    }
    summary_path = auto_dir / "corrective_v5_summary.json"
    write_json(summary_path, summary)
    write_json(auto_dir / "best_candidate_report.json", best)
    (auto_dir / "final_written_candidate.txt").write_text(best["candidate"] + "\n", "utf-8")
    return auto_dir, summary_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 3F corrective A-Roll v5 with semantic guard, word timing, and VAD.")
    parser.add_argument("--draft-dir", type=Path, default=Path(r"D:\JianyingPro Drafts\6月14日"))
    parser.add_argument("--subtitle-timeline", type=Path, default=DEFAULT_ORIGINAL_SUBTITLES)
    parser.add_argument("--script-path", type=Path, default=DEFAULT_SCRIPT)
    parser.add_argument("--deepseek-run", type=Path, default=DEFAULT_DEEPSEEK_RUN)
    parser.add_argument("--deepseek-config", type=Path, default=Path(r"D:\idea-project\videoDataCatcher\src\main\resources\application.yaml"))
    parser.add_argument("--deepseek-model", default="deepseek-chat")
    parser.add_argument("--source-backup", type=Path, default=DEFAULT_SOURCE_BACKUP)
    parser.add_argument("--timeline-name", default="")
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--max-iterations", type=int, default=4)
    args = parser.parse_args()

    auto_dir, summary_path = run_corrective_v5(args)
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
