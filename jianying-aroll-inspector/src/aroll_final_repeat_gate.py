from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aroll_adjacent_modifier_semantic_redundancy_gate import detect_adjacent_modifier_semantic_redundancy
from aroll_cjk_short_repeat_gate import detect_cjk_short_repeats
from aroll_take_clusterer import build_take_clusters


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def build_final_repeat_gate_report(
    residual_repeat_audit: dict[str, Any],
    display_subtitle_plan: list[dict[str, Any]] | None = None,
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    issues = list(residual_repeat_audit.get("issues") or [])
    text_high = 0
    text_medium = 0
    semantic_high = 0
    hidden_high = 0
    for issue in issues:
        confidence = str(issue.get("confidence") or "")
        issue_type = str(issue.get("issue_type") or "")
        if issue_type in {"word_timeline_hidden_repeat", "hidden_audio_repeat", "intra_subtitle_restart"}:
            if confidence == "high":
                hidden_high += 1
            continue
        if issue_type in {"semantic_containment_repeat", "prefix_overlap", "near_repeat", "exact_repeat"}:
            if confidence == "high":
                semantic_high += 1
            elif confidence == "medium":
                text_medium += 1
            continue
        if confidence == "high":
            text_high += 1
        elif confidence == "medium":
            text_medium += 1

    final_target_clusters: list[dict[str, Any]] = []
    short_repeat_candidates = detect_cjk_short_repeats(display_subtitle_plan or [])
    modifier_redundancy_candidates = detect_adjacent_modifier_semantic_redundancy(display_subtitle_plan or [])
    if display_subtitle_plan:
        final_rows = [
            {
                "subtitle_uid": str(row.get("fragment_id") or f"final_{index:06d}"),
                "subtitle_index": index,
                "subtitle_text": str(row.get("fragment_text") or row.get("text") or ""),
                "start_us": int(row.get("target_start_us") or 0),
                "end_us": int(row.get("target_start_us") or 0) + int(row.get("target_duration_us") or 0),
            }
            for index, row in enumerate(display_subtitle_plan, start=1)
            if str(row.get("fragment_text") or row.get("text") or "").strip()
        ]
        final_target_clusters, _cluster_report = build_take_clusters(final_rows, [], window=5)
    target_high = sum(1 for row in final_target_clusters if str(row.get("confidence") or "") == "high")
    target_medium = sum(1 for row in final_target_clusters if str(row.get("confidence") or "") == "medium")
    target_llm = sum(1 for row in final_target_clusters if row.get("requires_llm"))
    short_repeat_count = len(short_repeat_candidates)
    short_repeat_fatal = [row for row in short_repeat_candidates if str(row.get("severity") or "fatal") == "fatal"]
    short_repeat_warning = [row for row in short_repeat_candidates if str(row.get("severity") or "fatal") != "fatal"]
    modifier_redundancy_fatal = [row for row in modifier_redundancy_candidates if str(row.get("severity") or "fatal") == "fatal"]
    blocking_issue_count = text_high + text_medium + semantic_high + hidden_high + len(short_repeat_fatal) + len(modifier_redundancy_fatal)

    report = {
        "final_text_repeat_high_count": text_high,
        "final_text_repeat_medium_count": text_medium,
        "final_semantic_repeat_high_count": semantic_high,
        "final_hidden_word_repeat_high_count": hidden_high,
        "final_cjk_short_repeat_count": short_repeat_count,
        "final_cjk_short_repeat_fatal_count": len(short_repeat_fatal),
        "final_cjk_short_repeat_warning_count": len(short_repeat_warning),
        "adjacent_modifier_semantic_redundancy_count": len(modifier_redundancy_candidates),
        "adjacent_modifier_semantic_redundancy_fatal_count": len(modifier_redundancy_fatal),
        "final_target_take_cluster_count": len(final_target_clusters),
        "final_target_repeat_candidate_count": len(final_target_clusters),
        "final_target_llm_candidate_count": target_llm,
        "final_target_repeat_high_count": target_high,
        "final_target_repeat_medium_count": target_medium,
        "audio_only_repeat_supported": False,
        "audio_only_repeat_unsupported_warning": True,
        "audio_only_repeat_result_not_used_as_pass": True,
        "final_repeat_gate_passed": (blocking_issue_count + target_high + target_medium) == 0,
        "blocking_issues": (issues[:100] if (text_high + text_medium + semantic_high + hidden_high) else []) + short_repeat_fatal[:100] + modifier_redundancy_fatal[:100],
        "final_target_repeat_candidates": final_target_clusters[:100],
        "final_cjk_short_repeat_candidates": short_repeat_candidates[:100],
        "adjacent_modifier_semantic_redundancy_candidates": modifier_redundancy_candidates[:100],
    }
    if output_path:
        write_json(output_path, report)
    return report
