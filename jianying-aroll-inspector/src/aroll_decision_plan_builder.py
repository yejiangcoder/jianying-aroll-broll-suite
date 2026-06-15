from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


DROP_APPROVALS = {
    "approve_drop",
    "dirty_stutter_unit",
    "duplicate_take_covered",
    "required_clean_unit_covered",
    "semantic_containment_covered",
    "not_required_filler",
}

MICRO_APPROVALS = {
    "approve_micro_cleanup",
    "micro_cleanup_covered",
}

KEEP_CLASSES = {"true_missing_required_unit", "keep_both", "codex_self_review_required"}

DELETION_LIKE_ACTIONS = {
    "drop",
    "drop_left",
    "drop_right",
    "trim",
    "micro_cleanup",
    "cleanup",
    "remove_overlap",
}

DELETION_LIKE_TYPE_PARTS = {
    "drop",
    "duplicate_take",
    "semantic_containment",
    "semantic_overlap",
    "prefix_overlap",
    "near_repeat",
    "retake",
    "dirty_stutter",
    "micro_cleanup",
    "final_semantic_containment_repeat",
    "final_prefix_overlap",
    "final_near_repeat",
}

LEXICAL_REDUPLICATION_CHARS = set(
    "好坏大小多少高低长短快慢轻重冷热新旧清净亮暗红白黑甜苦酸软硬"
    "松紧稳狠准早晚远近深浅厚薄宽窄细粗美丑乖懒急"
)

QUANTITY_RE = re.compile(
    r"(?:(?:\d+(?:\.\d+)?)|(?:[一二两三四五六七八九十百千万半几]+))"
    r"(?:多|来|几)?"
    r"(?:斤|公斤|千克|克|岁|厘米|公分|毫米|米|块|元|万|千|百|分|秒|分钟|小时|年|个月|倍|x|X|%)"
)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _candidate_id(row: dict[str, Any]) -> str:
    return str(row.get("candidate_id") or row.get("unit_id") or "")


def _compact_text(text: str) -> str:
    return re.sub(r"[\s,，。.!！?？、:：;；\"'“”‘’（）()【】\[\]《》<>-]+", "", str(text or ""))


def _proposed_final_text(candidate: dict[str, Any]) -> str:
    repeat_cluster = candidate.get("repeat_cluster") or {}
    issue = candidate.get("issue") or {}
    return str(
        candidate.get("proposed_final_text")
        or candidate.get("kept_text")
        or repeat_cluster.get("micro_cleanup_text")
        or issue.get("merged_text")
        or issue.get("new_text")
        or ""
    )


def is_deletion_like_candidate(candidate: dict[str, Any]) -> bool:
    candidate_type = str(candidate.get("candidate_type") or "")
    proposed = str(candidate.get("proposed_action") or "")
    python_guess = str(candidate.get("python_guess") or "")
    if proposed in DELETION_LIKE_ACTIONS:
        return True
    if python_guess in DELETION_LIKE_ACTIONS:
        return True
    haystack = f"{candidate_type} {python_guess} {candidate.get('python_reason') or ''} {candidate.get('candidate_reason') or ''}"
    if any(part in haystack for part in DELETION_LIKE_TYPE_PARTS):
        return True
    return False


def lexical_reduplication_guard(candidate: dict[str, Any]) -> dict[str, Any] | None:
    source = _compact_text(str(candidate.get("source_text") or ""))
    proposed = _compact_text(_proposed_final_text(candidate))
    if not source or not proposed or source == proposed:
        return None
    for char in LEXICAL_REDUPLICATION_CHARS:
        repeated = char + char
        if repeated in source and source.count(char) > proposed.count(char):
            return {
                "guard_type": "lexical_reduplication_guard",
                "repeated_unit": repeated,
                "reason": "Chinese lexical reduplication may be emphasis/state, not stutter",
            }
    return None


def semantic_quantity_guard(candidate: dict[str, Any]) -> dict[str, Any] | None:
    source = _compact_text(str(candidate.get("source_text") or ""))
    proposed = _compact_text(_proposed_final_text(candidate))
    matches = [match.group(0) for match in QUANTITY_RE.finditer(source)]
    if not matches:
        return None
    if not proposed or proposed != source:
        return {
            "guard_type": "semantic_quantity_guard",
            "quantity_phrases": matches,
            "reason": "quantity phrase is semantic core and must not enter cleanup",
        }
    return None


def _longest_suffix_prefix_overlap(left: str, right: str) -> str:
    left_n = _compact_text(left)
    right_n = _compact_text(right)
    best = ""
    for size in range(2, min(len(left_n), len(right_n)) + 1):
        if left_n[-size:] == right_n[:size]:
            best = left_n[-size:]
    return best


def suffix_prefix_overlap_merge(candidate: dict[str, Any]) -> dict[str, Any] | None:
    ranges = sorted(
        [row for row in (candidate.get("source_subtitle_ranges") or []) if str(row.get("text") or "").strip()],
        key=lambda row: int(row.get("subtitle_index") or 0),
    )
    if len(ranges) >= 2:
        left = str(ranges[0].get("text") or "")
        right = str(ranges[-1].get("text") or "")
    else:
        parts = [part for part in re.split(r"\s+", str(candidate.get("source_text") or "").strip()) if part]
        if len(parts) < 2:
            return None
        left, right = parts[0], parts[-1]

    overlap = _longest_suffix_prefix_overlap(left, right)
    if len(overlap) < 2:
        return None
    left_n = _compact_text(left)
    right_n = _compact_text(right)
    if len(left_n) <= len(overlap) or len(right_n) <= len(overlap):
        return None
    merged = left_n + right_n[len(overlap) :]
    return {
        "guard_type": "suffix_prefix_overlap_merge",
        "left_text": left,
        "right_text": right,
        "overlap_text": overlap,
        "merged_text": merged,
        "reason": "merge suffix-prefix overlap without dropping unique prefix or suffix",
    }


def _directed_drop_indices(candidate: dict[str, Any], indices: list[int], action: str) -> list[int]:
    if action == "drop_left":
        return indices[:1]
    if action == "drop_right":
        return indices[-1:] if indices else []
    return indices


def _source_range_for_indices(candidate: dict[str, Any], indices: list[int]) -> tuple[int, int]:
    wanted = set(indices)
    ranges = [
        row
        for row in (candidate.get("source_subtitle_ranges") or [])
        if int(row.get("subtitle_index") or 0) in wanted
    ]
    starts = [int(row.get("start_us") or 0) for row in ranges if int(row.get("end_us") or 0) > int(row.get("start_us") or 0)]
    ends = [int(row.get("end_us") or 0) for row in ranges if int(row.get("end_us") or 0) > int(row.get("start_us") or 0)]
    if starts and ends:
        return min(starts), max(ends)
    all_indices = [int(x) for x in candidate.get("source_subtitle_indices") or [] if int(x) > 0]
    if set(indices) == set(all_indices):
        return int(candidate.get("source_start_us") or 0), int(candidate.get("source_end_us") or 0)
    return 0, 0


def _range_rows_for_indices(candidate: dict[str, Any], indices: list[int]) -> list[dict[str, Any]]:
    wanted = set(indices)
    return [
        row
        for row in (candidate.get("source_subtitle_ranges") or [])
        if int(row.get("subtitle_index") or 0) in wanted
    ]


def build_aroll_decision_plan(
    candidates: list[dict[str, Any]],
    arbiter_results: list[dict[str, Any]],
    run_dir: Path,
) -> dict[str, Any]:
    results_by_id = {_candidate_id(row): row for row in arbiter_results}
    decisions: list[dict[str, Any]] = []
    force_keep_indices: set[int] = set()
    approved_drop_indices: set[int] = set()
    approved_micro_indices: set[int] = set()
    self_review_items: list[dict[str, Any]] = []
    approved_drop_source_ranges: list[dict[str, Any]] = []
    block_reasons: list[str] = []
    drop_left_count = 0
    drop_right_count = 0
    keep_both_count = 0
    unmapped_llm_action_count = 0
    conservative_keep_items: list[dict[str, Any]] = []
    overlap_merge_items: list[dict[str, Any]] = []
    decision_plan_conservative_keep_count = 0
    decision_plan_self_review_block_count = 0
    decision_plan_overlap_merge_count = 0

    for candidate in candidates:
        cid = _candidate_id(candidate)
        indices = [int(x) for x in candidate.get("source_subtitle_indices") or [] if int(x) > 0]
        proposed = str(candidate.get("proposed_action") or "")
        requires_llm = bool(candidate.get("requires_llm"))
        result = results_by_id.get(cid)
        classification = str((result or {}).get("classification") or ("engineering_rule" if not requires_llm else "codex_self_review_required"))
        confidence = str((result or {}).get("confidence") or ("high" if not requires_llm else "low"))
        approved_action = str((result or {}).get("approved_action") or proposed or "self_review")
        decision_type = "codex_self_review_required"
        approved = False
        should_block = False
        mapped = bool(indices)

        llm_approved_drop = classification in DROP_APPROVALS and approved_action in {"drop", "drop_left", "drop_right"}
        llm_approved_micro = (
            classification in (MICRO_APPROVALS | DROP_APPROVALS)
            and approved_action in {"trim", "micro_cleanup"}
        )
        llm_keep_both = classification == "keep_both" or approved_action in {"keep_both", "keep"}
        llm_self_review = classification == "codex_self_review_required" or approved_action == "self_review"

        if not requires_llm:
            decision_type = proposed if proposed in {"drop", "micro_cleanup", "pause_cut", "trim"} else "keep"
            approved = True
        elif llm_approved_drop:
            drop_indices = _directed_drop_indices(candidate, indices, approved_action)
            drop_start, drop_end = _source_range_for_indices(candidate, drop_indices)
            if not mapped or not drop_indices or drop_end <= drop_start:
                decision_type = "codex_self_review_required"
                should_block = True
                unmapped_llm_action_count += 1
                block_reasons.append(f"UNMAPPED_LLM_DROP_ACTION:{cid}:{approved_action}")
                self_review_items.append(candidate | {"llm_result": result or {}, "self_review_reason": "approved drop action has no subtitle/source mapping"})
            else:
                decision_type = approved_action if approved_action in {"drop_left", "drop_right"} else "drop"
                if decision_type == "drop_left":
                    drop_left_count += 1
                elif decision_type == "drop_right":
                    drop_right_count += 1
                approved = True
                approved_drop_indices.update(drop_indices)
                force_keep_indices.update(idx for idx in indices if idx not in set(drop_indices))
                approved_drop_source_ranges.append(
                    {
                        "candidate_id": cid,
                        "action": decision_type,
                        "source_subtitle_indices": drop_indices,
                        "source_subtitle_ranges": _range_rows_for_indices(candidate, drop_indices),
                        "source_text": candidate.get("source_text") or "",
                        "reason": (result or {}).get("reason") or candidate.get("python_reason") or "",
                        "candidate_type": candidate.get("candidate_type") or "",
                        "source": "decision_plan_take_cluster"
                        if (candidate.get("repeat_cluster") or {}).get("source") == "take_clusterer"
                        else "decision_plan_llm",
                        "source_start_us": drop_start,
                        "source_end_us": drop_end,
                    }
                )
        elif llm_approved_micro:
            if not mapped:
                decision_type = "codex_self_review_required"
                should_block = True
                unmapped_llm_action_count += 1
                block_reasons.append(f"UNMAPPED_LLM_MICRO_ACTION:{cid}:{approved_action}")
                self_review_items.append(candidate | {"llm_result": result or {}, "self_review_reason": "approved micro action has no subtitle/source mapping"})
            elif lexical_reduplication_guard(candidate) or semantic_quantity_guard(candidate):
                guard = lexical_reduplication_guard(candidate) or semantic_quantity_guard(candidate) or {}
                decision_type = "conservative_keep"
                approved = True
                should_block = False
                decision_plan_conservative_keep_count += 1
                force_keep_indices.update(indices)
                conservative_keep_items.append(
                    candidate
                    | {
                        "llm_result": result or {},
                        "resolved_by_conservative_keep": True,
                        "self_review_reason": guard.get("reason") or "cleanup blocked by semantic guard",
                        "guard": guard,
                    }
                )
            else:
                decision_type = "micro_cleanup"
                approved = True
                approved_micro_indices.update(indices)
        elif llm_keep_both:
            decision_type = "keep_both"
            approved = True
            keep_both_count += 1
            force_keep_indices.update(indices)
        elif llm_self_review:
            force_keep_indices.update(indices)
            overlap_merge = suffix_prefix_overlap_merge(candidate)
            lexical_guard = lexical_reduplication_guard(candidate)
            quantity_guard = semantic_quantity_guard(candidate)
            if overlap_merge:
                decision_type = "overlap_merge"
                approved = True
                should_block = False
                decision_plan_overlap_merge_count += 1
                overlap_merge_items.append(
                    candidate
                    | {
                        "llm_result": result or {},
                        "resolved_by_overlap_merge": True,
                        "overlap_merge": overlap_merge,
                        "self_review_reason": overlap_merge.get("reason"),
                    }
                )
            elif lexical_guard or quantity_guard or is_deletion_like_candidate(candidate):
                guard = lexical_guard or quantity_guard or {}
                decision_type = "conservative_keep"
                approved = True
                should_block = False
                decision_plan_conservative_keep_count += 1
                conservative_keep_items.append(
                    candidate
                    | {
                        "llm_result": result or {},
                        "resolved_by_conservative_keep": True,
                        "self_review_reason": guard.get("reason") or "deletion-like self_review resolved by conservative keep",
                        "guard": guard,
                    }
                )
            else:
                decision_type = "codex_self_review_required"
                should_block = True
                decision_plan_self_review_block_count += 1
                block_reasons.append(f"CODEX_SELF_REVIEW_REQUIRED:{cid}:{classification}:{approved_action}")
                self_review_items.append(candidate | {"llm_result": result or {}})
        else:
            decision_type = "codex_self_review_required"
            force_keep_indices.update(indices)
            should_block = True
            decision_plan_self_review_block_count += 1
            block_reasons.append(f"UNAPPROVED_HIGH_RISK:{cid}:{classification}:{proposed}")
            self_review_items.append(candidate | {"llm_result": result or {}})

        decisions.append(
            {
                "decision_id": f"dec_{len(decisions)+1:04d}",
                "candidate_id": cid,
                "type": decision_type,
                "source_subtitle_indices": indices,
                "source_text": candidate.get("source_text") or "",
                "final_text": (result or {}).get("final_equivalent_text") or candidate.get("proposed_final_text") or "",
                "llm_classification": classification,
                "llm_confidence": confidence,
                "approved_action": approved_action,
                "approved": approved,
                "should_block": should_block,
                "reason": (result or {}).get("reason") or candidate.get("python_reason") or "",
                "python_reason": candidate.get("python_reason") or "",
                "candidate_type": candidate.get("candidate_type"),
                "proposed_action": proposed,
            }
        )

    plan = {
        "source": "candidate_discovery + deepseek_semantic_arbiter",
        "decisions": decisions,
        "force_keep_subtitle_indices": sorted(force_keep_indices),
        "approved_drop_subtitle_indices": sorted(approved_drop_indices),
        "approved_drop_source_ranges": approved_drop_source_ranges,
        "approved_micro_cleanup_subtitle_indices": sorted(approved_micro_indices),
        "conservative_keep_items": conservative_keep_items,
        "overlap_merge_items": overlap_merge_items,
        "codex_self_review_items": self_review_items,
        "blocked": bool(block_reasons),
        "block_reasons": block_reasons,
        "summary": {
            "candidate_count": len(candidates),
            "decision_count": len(decisions),
            "force_keep_count": len(force_keep_indices),
            "approved_drop_count": len([d for d in decisions if d["type"] in {"drop", "drop_left", "drop_right"}]),
            "decision_plan_drop_left_count": drop_left_count,
            "decision_plan_drop_right_count": drop_right_count,
            "decision_plan_keep_both_count": keep_both_count,
            "decision_plan_unmapped_llm_action_count": unmapped_llm_action_count,
            "decision_plan_conservative_keep_count": decision_plan_conservative_keep_count,
            "decision_plan_overlap_merge_count": decision_plan_overlap_merge_count,
            "decision_plan_self_review_block_count": decision_plan_self_review_block_count,
            "decision_plan_self_review_resolved_count": decision_plan_conservative_keep_count + decision_plan_overlap_merge_count,
            "approved_micro_cleanup_count": len([d for d in decisions if d["type"] == "micro_cleanup"]),
            "codex_self_review_count": len(self_review_items),
            "blocked_count": len(block_reasons),
        },
    }
    write_json(run_dir / "aroll_decision_plan.json", plan)
    return plan


def apply_decision_plan_to_merged(merged: dict[str, Any], decision_plan: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    out = deepcopy(merged)
    force_keep = {int(x) for x in decision_plan.get("force_keep_subtitle_indices") or []}
    approved_drop = {int(x) for x in decision_plan.get("approved_drop_subtitle_indices") or []}
    approved_micro = {int(x) for x in decision_plan.get("approved_micro_cleanup_subtitle_indices") or []}

    original_drops = list(out.get("drop_decisions") or [])
    original_micros = list(out.get("micro_cleanups") or [])
    original_drop_indices = {int(row.get("subtitle_index") or 0) for row in original_drops}
    new_drops = []
    retained_original_drop_indices: set[int] = set()
    for row in original_drops:
        idx = int(row.get("subtitle_index") or 0)
        if idx in force_keep:
            continue
        if idx in approved_drop:
            new_drops.append(row | {"decision_plan_approved": True})
            retained_original_drop_indices.add(idx)
            continue
        # High-risk drops must not execute without LLM approval.
    existing_new_indices = {int(row.get("subtitle_index") or 0) for row in new_drops}
    added_decision_plan_drops: list[dict[str, Any]] = []
    added_range_drops: list[dict[str, Any]] = []
    approved_without_effect: list[dict[str, Any]] = []
    for source_range in decision_plan.get("approved_drop_source_ranges") or []:
        indices = [int(x) for x in source_range.get("source_subtitle_indices") or [] if int(x) > 0]
        range_rows = list(source_range.get("source_subtitle_ranges") or [])
        if not range_rows and indices:
            range_rows = [{"subtitle_index": idx} for idx in indices]
        if not indices and int(source_range.get("source_end_us") or 0) > int(source_range.get("source_start_us") or 0):
            added_range_drops.append(
                {
                    "decision_plan_candidate_id": source_range.get("candidate_id"),
                    "decision_plan_action": source_range.get("action"),
                    "source_start_us": source_range.get("source_start_us"),
                    "source_end_us": source_range.get("source_end_us"),
                    "reason": source_range.get("reason") or "approved source range has no subtitle index",
                }
            )
            approved_without_effect.append(source_range | {"reason": "approved range has no subtitle index"})
            continue
        for range_row in range_rows:
            idx = int(range_row.get("subtitle_index") or 0)
            if idx <= 0:
                approved_without_effect.append(source_range | {"reason": "approved range row has no subtitle index"})
                continue
            if idx in force_keep:
                approved_without_effect.append(source_range | {"reason": "approved drop conflicts with force_keep", "subtitle_index": idx})
                continue
            if idx in existing_new_indices:
                continue
            drop_row = {
                "subtitle_index": idx,
                "subtitle_uid": range_row.get("subtitle_uid") or f"sub_{idx:06d}",
                "drop_text": range_row.get("text") or source_range.get("source_text") or "",
                "keep_instead_text": "",
                "source": source_range.get("source") or "decision_plan_llm",
                "reason": source_range.get("reason") or "approved by decision plan",
                "decision_plan_approved": True,
                "decision_plan_candidate_id": source_range.get("candidate_id"),
                "decision_plan_action": source_range.get("action"),
                "source_start_us": range_row.get("start_us") or source_range.get("source_start_us"),
                "source_end_us": range_row.get("end_us") or source_range.get("source_end_us"),
            }
            new_drops.append(drop_row)
            added_decision_plan_drops.append(drop_row)
            existing_new_indices.add(idx)
    new_micros = []
    for row in original_micros:
        idx = int(row.get("subtitle_index") or 0)
        if idx in force_keep:
            continue
        if idx in approved_micro:
            new_micros.append(row | {"decision_plan_approved": True})
            continue
        # High-risk micro cleanup must not execute without LLM approval.
    out["drop_decisions"] = new_drops
    out["micro_cleanups"] = new_micros
    out["decision_plan_summary"] = decision_plan.get("summary") or {}
    out["range_drop_decisions"] = added_range_drops
    out["overlap_merge_items"] = list(decision_plan.get("overlap_merge_items") or [])
    report = {
        "original_drop_count": len(original_drops),
        "original_micro_cleanup_count": len(original_micros),
        "final_drop_count": len(new_drops),
        "final_micro_cleanup_count": len(new_micros),
        "force_keep_count": len(force_keep),
        "removed_unapproved_drop_count": len(original_drops) - len(retained_original_drop_indices),
        "removed_unapproved_micro_cleanup_count": len(original_micros) - len(new_micros),
        "added_decision_plan_drop_count": len(added_decision_plan_drops),
        "added_decision_plan_drop_indices": sorted({int(row.get("subtitle_index") or 0) for row in added_decision_plan_drops}),
        "added_decision_plan_range_drop_count": len(added_range_drops),
        "approved_drop_without_merged_effect_count": len(approved_without_effect),
        "approved_drop_without_merged_effect": approved_without_effect,
        "decision_plan_drop_existing_original_count": len(approved_drop & original_drop_indices),
        "take_cluster_applied_drop_count": sum(1 for row in new_drops if str(row.get("source") or "") == "decision_plan_take_cluster"),
        "overlap_merge_item_count": len(decision_plan.get("overlap_merge_items") or []),
    }
    return out, report
