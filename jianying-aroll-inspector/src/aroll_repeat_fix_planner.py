from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


SOURCE_MAP_TOLERANCE_US = 180_000


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _llm_drop_action(issue: dict[str, Any], llm_results: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    issue_id = str(issue.get("issue_id") or "")
    result = llm_results.get(f"final_{issue_id}") or llm_results.get(issue_id)
    if not result:
        return "", None
    classification = str(result.get("classification") or "")
    action = str(result.get("approved_action") or "")
    confidence = str(result.get("confidence") or "")
    approved_classes = {
        "approve_drop",
        "dirty_stutter_unit",
        "duplicate_take_covered",
        "not_required_filler",
        "required_clean_unit_covered",
        "semantic_containment_covered",
    }
    if confidence not in {"high", "medium"} or classification not in approved_classes:
        return "", result
    if action in {"drop_left", "drop_right", "drop"}:
        return action, result
    return "", result


def build_final_repeat_fix_plan(
    audit: dict[str, Any],
    tiny_report: dict[str, Any],
    final_audit_llm_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    drop_segments: list[dict[str, Any]] = []
    hidden_audio_cuts: list[dict[str, Any]] = []
    trim_segments: list[dict[str, Any]] = []
    merge_segments: list[dict[str, Any]] = []
    codex_self_review: list[dict[str, Any]] = []
    subtitle_replacements: list[dict[str, Any]] = []
    subtitle_drops: list[str] = []
    tiny_artifact_removals: list[dict[str, Any]] = []

    llm_result_by_id = {
        str(row.get("candidate_id") or row.get("unit_id") or ""): row
        for row in (final_audit_llm_results or [])
    }
    deterministic_safe_issue_count = 0
    requires_llm_issue_count = 0
    llm_approved_drop_count = 0
    llm_keep_both_count = 0
    llm_self_review_count = 0
    final_audit_llm_action_applied_count = 0
    final_audit_python_recommended_overridden_count = 0
    final_audit_llm_action_missing_count = 0

    for issue in audit.get("issues") or []:
        action = issue.get("recommended_action")
        confidence = issue.get("confidence")
        deterministic_safe = bool(issue.get("deterministic_safe"))
        requires_llm = bool(issue.get("requires_llm"))
        llm_drop_approved = False
        if deterministic_safe:
            deterministic_safe_issue_count += 1
        if requires_llm:
            requires_llm_issue_count += 1
        if requires_llm and not deterministic_safe:
            llm_action, llm_result = _llm_drop_action(issue, llm_result_by_id)
            approved_action = str((llm_result or {}).get("approved_action") or "")
            if approved_action == "keep_both":
                llm_keep_both_count += 1
                continue
            if not llm_action:
                if not llm_result:
                    final_audit_llm_action_missing_count += 1
                if llm_result and approved_action == "self_review":
                    llm_self_review_count += 1
                else:
                    llm_self_review_count += 1
                codex_self_review.append(
                    issue
                    | {
                        "self_review_reason": "semantic repeat candidate was not approved for deletion by LLM",
                        "llm_result": llm_result,
                    }
                )
                continue
            if str(issue.get("recommended_action") or "") != llm_action:
                final_audit_python_recommended_overridden_count += 1
            final_audit_llm_action_applied_count += 1
            if llm_action == "drop_left":
                left_start = int(issue.get("left_source_start_us") or issue.get("source_start_us") or 0)
                left_end = int(issue.get("left_source_end_us") or issue.get("source_end_us") or 0)
                left_ids = (issue.get("left_subtitle_ids") or (issue.get("involved_subtitle_ids") or [])[:1])
                if left_end > left_start:
                    issue = issue | {
                        "recommended_action": "drop_left",
                        "source_start_us": left_start,
                        "source_end_us": left_end,
                        "involved_subtitle_ids": left_ids,
                        "selected_subtitle_ids": left_ids,
                        "selected_source_start_us": left_start,
                        "selected_source_end_us": left_end,
                    }
                else:
                    llm_self_review_count += 1
                    codex_self_review.append(
                        issue
                        | {
                            "self_review_reason": "LLM approved drop_left but left source range is unavailable",
                            "llm_result": llm_result,
                        }
                    )
                    continue
            if llm_action == "drop_right":
                right_start = int(issue.get("right_source_start_us") or 0)
                right_end = int(issue.get("right_source_end_us") or 0)
                right_ids = (issue.get("right_subtitle_ids") or (issue.get("involved_subtitle_ids") or [])[1:2])
                if right_end > right_start:
                    issue = issue | {
                        "recommended_action": "drop_right",
                        "source_start_us": right_start,
                        "source_end_us": right_end,
                        "involved_subtitle_ids": right_ids,
                        "selected_subtitle_ids": right_ids,
                        "selected_source_start_us": right_start,
                        "selected_source_end_us": right_end,
                    }
                else:
                    llm_self_review_count += 1
                    codex_self_review.append(
                        issue
                        | {
                            "self_review_reason": "LLM approved drop_right but right source range is unavailable",
                            "llm_result": llm_result,
                        }
                    )
                    continue
            llm_approved_drop_count += 1
            llm_drop_approved = True
            action = llm_action
        if confidence != "high" and not llm_drop_approved:
            codex_self_review.append(issue | {"self_review_reason": "non-high-confidence repeat fix"})
            continue
        if action == "remove_hidden_first_audio_island":
            hidden_audio_cuts.append(
                {
                    "issue_id": issue.get("issue_id"),
                    "source_cut_start_us": issue.get("source_start_us"),
                    "source_cut_end_us": issue.get("source_end_us"),
                    "reason": issue.get("reason"),
                }
            )
            if issue.get("replacement_subtitle"):
                subtitle_replacements.append(issue["replacement_subtitle"])
        elif action in {"drop_left", "drop_right"}:
            selected_ids = issue.get("selected_subtitle_ids") or (issue.get("involved_subtitle_ids") or [])[:1]
            selected_start = issue.get("selected_source_start_us") or issue.get("source_start_us")
            selected_end = issue.get("selected_source_end_us") or issue.get("source_end_us")
            drop_segments.append(
                {
                    "issue_id": issue.get("issue_id"),
                    "source_start_us": selected_start,
                    "source_end_us": selected_end,
                    "subtitle_ids": selected_ids,
                    "selected_subtitle_ids": selected_ids,
                    "selected_source_start_us": selected_start,
                    "selected_source_end_us": selected_end,
                    "drop_side": "right" if action == "drop_right" else "left",
                    "reason": issue.get("reason"),
                }
            )
            subtitle_drops.extend(str(item) for item in selected_ids if item)
        elif action in {"trim_left_phrase", "trim_right_phrase"}:
            codex_self_review.append(issue | {"self_review_reason": "medium-risk phrase trim is not executed automatically"})
        else:
            codex_self_review.append(issue | {"self_review_reason": "unsupported repeat fix action"})

    for issue in tiny_report.get("tiny_artifact_issues") or []:
        tiny_artifact_removals.append(
            {
                "issue_id": issue.get("issue_id"),
                "clip_id": issue.get("clip_id"),
                "source_start_us": issue.get("source_start_us"),
                "source_end_us": issue.get("source_end_us"),
                "reason": issue.get("reason"),
            }
        )

    return {
        "drop_segments": drop_segments,
        "trim_segments": trim_segments,
        "merge_segments": merge_segments,
        "hidden_audio_cuts": hidden_audio_cuts,
        "tiny_artifact_removals": tiny_artifact_removals,
        "subtitle_replacements": subtitle_replacements,
        "subtitle_drops": sorted(set(subtitle_drops)),
        "codex_self_review": codex_self_review,
        "summary": {
            "drop_count": len(drop_segments),
            "trim_count": len(trim_segments),
            "hidden_audio_cut_count": len(hidden_audio_cuts),
            "tiny_artifact_removed_count": len(tiny_artifact_removals),
            "codex_self_review_count": len(codex_self_review),
            "deterministic_safe_issue_count": deterministic_safe_issue_count,
            "requires_llm_issue_count": requires_llm_issue_count,
            "llm_approved_drop_count": llm_approved_drop_count,
            "llm_keep_both_count": llm_keep_both_count,
            "llm_self_review_count": llm_self_review_count,
            "final_audit_llm_action_applied_count": final_audit_llm_action_applied_count,
            "final_audit_python_recommended_overridden_count": final_audit_python_recommended_overridden_count,
            "final_audit_llm_action_missing_count": final_audit_llm_action_missing_count,
        },
    }


def _intervals_from_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    intervals: list[dict[str, Any]] = []
    for key in ("hidden_audio_cuts", "drop_segments", "tiny_artifact_removals"):
        for row in plan.get(key) or []:
            start = int(row.get("source_cut_start_us") or row.get("source_start_us") or 0)
            end = int(row.get("source_cut_end_us") or row.get("source_end_us") or 0)
            if end > start:
                intervals.append({"start": start, "end": end, "source": key, "row": row})
    intervals.sort(key=lambda row: (row["start"], row["end"]))
    return intervals


def apply_fix_plan_to_edl(final_edl: list[dict[str, Any]], plan: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    intervals = _intervals_from_plan(plan)
    output: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    removed_clip_ids: list[str] = []
    for clip in sorted(final_edl, key=lambda row: int(row.get("target_start_us") or 0)):
        pieces = [(int(clip["source_start_us"]), int(clip["source_end_us"]))]
        affected_sources: set[str] = set()
        for interval in intervals:
            next_pieces: list[tuple[int, int]] = []
            for start, end in pieces:
                overlap_start = max(start, interval["start"])
                overlap_end = min(end, interval["end"])
                if overlap_end <= overlap_start:
                    next_pieces.append((start, end))
                    continue
                affected_sources.add(str(interval["source"]))
                if overlap_start > start:
                    next_pieces.append((start, overlap_start))
                if overlap_end < end:
                    next_pieces.append((overlap_end, end))
                applied.append(
                    {
                        "clip_id": clip.get("clip_id"),
                        "interval_source": interval["source"],
                        "removed_source_start_us": overlap_start,
                        "removed_source_end_us": overlap_end,
                        "removed_duration_us": overlap_end - overlap_start,
                    }
                )
            pieces = [(start, end) for start, end in next_pieces if end > start]
        pieces = [
            (start, end) for start, end in pieces
            if end > start and not (end - start < 500_000 and affected_sources)
        ]
        if not pieces:
            removed_clip_ids.append(str(clip.get("clip_id") or ""))
            continue
        for piece_index, (start, end) in enumerate(pieces, start=1):
            cloned = deepcopy(clip)
            cloned["source_start_us"] = start
            cloned["source_end_us"] = end
            cloned["source_timeline_start_us"] = start
            cloned["source_timeline_end_us"] = end
            cloned["cut_start_us"] = start
            cloned["cut_end_us"] = end
            cloned["target_duration_us"] = end - start
            cloned["final_target_duration_us"] = end - start
            cloned["material_start_us"] = None
            cloned["material_end_us"] = None
            if len(pieces) > 1:
                cloned["clip_id"] = f"{clip.get('clip_id')}_fx{piece_index:02d}"
                cloned["parent_clip_id"] = clip.get("clip_id")
            output.append(cloned)

    target_start = 0
    for clip in sorted(output, key=lambda row: (int(row.get("source_start_us") or 0), int(row.get("source_end_us") or 0))):
        duration = int(clip["source_end_us"]) - int(clip["source_start_us"])
        if duration <= 0:
            continue
        clip["target_start_us"] = target_start
        clip["target_duration_us"] = duration
        clip["final_target_start_us"] = target_start
        clip["final_target_duration_us"] = duration
        clip["final_target_end_us"] = target_start + duration
        clip["source_timeline_start_us"] = int(clip.get("source_start_us") or 0)
        clip["source_timeline_end_us"] = int(clip.get("source_end_us") or 0)
        clip["source_reason"] = "phase4d3_final_repeat_fix"
        target_start += duration
    return output, {
        "removed_clip_ids": removed_clip_ids,
        "applied_intervals": applied,
        "removed_duration_us": sum(int(row["removed_duration_us"]) for row in applied),
        "final_clip_count": len(output),
    }


def source_range_to_target_range(
    source_start_us: int,
    source_end_us: int,
    edl: list[dict[str, Any]],
    tolerance_us: int = SOURCE_MAP_TOLERANCE_US,
) -> tuple[int, int] | None:
    mapped: list[tuple[int, int]] = []
    for clip in sorted(edl, key=lambda row: int(row.get("target_start_us") or 0)):
        clip_start = int(clip.get("source_timeline_start_us") or clip["source_start_us"])
        clip_end = int(clip.get("source_timeline_end_us") or clip["source_end_us"])
        if clip_end < source_start_us - tolerance_us or clip_start > source_end_us + tolerance_us:
            continue
        overlap_start = max(source_start_us, clip_start)
        overlap_end = min(source_end_us, clip_end)
        if overlap_end <= overlap_start:
            if abs(source_start_us - clip_end) <= tolerance_us:
                overlap_start = clip_end
                overlap_end = clip_end
            elif abs(source_end_us - clip_start) <= tolerance_us:
                overlap_start = clip_start
                overlap_end = clip_start
            else:
                continue
        target_start = int(clip["target_start_us"]) + max(0, overlap_start - clip_start)
        target_end = int(clip["target_start_us"]) + max(0, overlap_end - clip_start)
        if target_end == target_start:
            continue
        mapped.append((target_start, target_end))
    if not mapped:
        return None
    return min(start for start, _ in mapped), max(end for _, end in mapped)


def source_to_target(source_us: int, edl: list[dict[str, Any]], tolerance_us: int = SOURCE_MAP_TOLERANCE_US) -> int | None:
    target_range = source_range_to_target_range(source_us, source_us + 1, edl, tolerance_us)
    if target_range:
        return target_range[0]
    return None


def apply_fix_plan_to_subtitles(
    display_plan: list[dict[str, Any]],
    plan: dict[str, Any],
    fixed_edl: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    replacements = {str(row.get("fragment_id") or ""): row for row in plan.get("subtitle_replacements") or []}
    drops = {str(item) for item in plan.get("subtitle_drops") or []}
    output: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for row in display_plan:
        fragment_id = str(row.get("fragment_id") or "")
        if fragment_id in drops:
            dropped.append({"fragment_id": fragment_id, "text": row.get("fragment_text"), "reason": "drop_left_repeat"})
            continue
        base = deepcopy(replacements.get(fragment_id, row))
        source_start = int(base.get("source_start_us") or 0)
        source_end = int(base.get("source_end_us") or source_start)
        target_range = source_range_to_target_range(source_start, source_end, fixed_edl)
        if target_range is None:
            dropped.append({"fragment_id": fragment_id, "text": base.get("fragment_text"), "reason": "source_not_in_fixed_edl"})
            continue
        target_start, target_end = target_range
        if target_end <= target_start:
            dropped.append({"fragment_id": fragment_id, "text": base.get("fragment_text"), "reason": "non_positive_target_range_after_mapping"})
            continue
        base["target_start_us"] = target_start
        base["target_duration_us"] = target_end - target_start
        base["reason"] = "phase4d3_repeat_fixed_subtitle"
        output.append(base)
    output.sort(key=lambda row: int(row.get("target_start_us") or 0))
    for index, row in enumerate(output, start=1):
        row["fragment_id"] = f"dsub_{index:04d}"
    return output, {"dropped_subtitles": dropped, "subtitle_count": len(output)}
