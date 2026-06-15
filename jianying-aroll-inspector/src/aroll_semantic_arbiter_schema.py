from __future__ import annotations

from typing import Any


VALID_CLASSIFICATIONS = {
    "approve_drop",
    "approve_micro_cleanup",
    "required_clean_unit_covered",
    "semantic_containment_covered",
    "dirty_stutter_unit",
    "duplicate_take_covered",
    "keep_both",
    "micro_cleanup_covered",
    "true_missing_required_unit",
    "not_required_filler",
    "codex_self_review_required",
}

NON_BLOCKING_CLASSIFICATIONS = {
    "approve_drop",
    "approve_micro_cleanup",
    "required_clean_unit_covered",
    "semantic_containment_covered",
    "dirty_stutter_unit",
    "duplicate_take_covered",
    "keep_both",
    "micro_cleanup_covered",
    "not_required_filler",
}


def normalize_arbiter_result(raw: dict[str, Any]) -> dict[str, Any]:
    unsafe_manual_review_upgrade = False
    inconsistent = False
    normalized_to_self_review = False
    raw_classification = str(raw.get("classification") or "codex_self_review_required").strip()
    if raw_classification in {"manual_review", "ambiguous", "unsure", "unknown"}:
        raw_classification = "codex_self_review_required"
        normalized_to_self_review = True
    classification = raw_classification
    if classification not in VALID_CLASSIFICATIONS:
        classification = "codex_self_review_required"
        normalized_to_self_review = True
    confidence = str(raw.get("confidence") or "low").strip().lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    should_block = bool(raw.get("should_block_write"))
    if classification == "true_missing_required_unit" and confidence in {"high", "medium"}:
        should_block = True
    if classification == "codex_self_review_required":
        should_block = True
    if classification in NON_BLOCKING_CLASSIFICATIONS:
        should_block = False
    approved_action = str(raw.get("approved_action") or "").strip()
    valid_actions = {"drop", "trim", "keep", "drop_left", "drop_right", "keep_both", "self_review"}
    if approved_action not in valid_actions:
        if classification in {
            "approve_drop",
            "dirty_stutter_unit",
            "duplicate_take_covered",
            "not_required_filler",
            "required_clean_unit_covered",
            "semantic_containment_covered",
        }:
            approved_action = "drop"
        elif classification in {"approve_micro_cleanup", "micro_cleanup_covered"}:
            approved_action = "trim"
        elif classification == "keep_both":
            approved_action = "keep_both"
        elif classification == "codex_self_review_required":
            approved_action = "self_review"
        else:
            approved_action = "keep"
    if classification == "codex_self_review_required":
        if approved_action != "self_review":
            inconsistent = True
            unsafe_manual_review_upgrade = False
            approved_action = "self_review"
            normalized_to_self_review = True
        should_block = True
    elif approved_action in {"drop", "drop_left", "drop_right"} and classification not in {
        "approve_drop",
        "dirty_stutter_unit",
        "duplicate_take_covered",
        "not_required_filler",
        "required_clean_unit_covered",
        "semantic_containment_covered",
    }:
        inconsistent = True
        classification = "codex_self_review_required"
        approved_action = "self_review"
        should_block = True
        normalized_to_self_review = True
    return {
        "candidate_id": str(raw.get("candidate_id") or raw.get("unit_id") or ""),
        "unit_id": str(raw.get("unit_id") or raw.get("candidate_id") or ""),
        "classification": classification,
        "approved_action": approved_action,
        "covered_by_final": bool(raw.get("covered_by_final")),
        "final_equivalent_text": str(raw.get("final_equivalent_text") or ""),
        "should_block_write": should_block,
        "confidence": confidence,
        "reason": str(raw.get("reason") or ""),
        "inconsistent_llm_result": inconsistent,
        "normalized_to_self_review": normalized_to_self_review,
        "unsafe_manual_review_upgrade": unsafe_manual_review_upgrade,
    }


def summarize_arbiter_results(results: list[dict[str, Any]], *, llm_used: bool, model: str, call_count: int) -> dict[str, Any]:
    counts: dict[str, int] = {key: 0 for key in VALID_CLASSIFICATIONS}
    for row in results:
        cls = str(row.get("classification") or "codex_self_review_required")
        counts[cls] = counts.get(cls, 0) + 1
    return {
        "llm_used": llm_used,
        "model": model,
        "call_count": call_count,
        "unit_count": len(results),
        "suspicious_unit_count": len(results),
        "true_missing_required_count": counts.get("true_missing_required_unit", 0),
        "self_review_required_count": counts.get("codex_self_review_required", 0),
        "manual_review_count": 0,
        "inconsistent_llm_result_count": sum(1 for row in results if row.get("inconsistent_llm_result")),
        "normalized_to_self_review_count": sum(1 for row in results if row.get("normalized_to_self_review")),
        "unsafe_manual_review_upgrade_count": sum(1 for row in results if row.get("unsafe_manual_review_upgrade")),
        "approve_drop_count": counts.get("approve_drop", 0),
        "approve_micro_cleanup_count": counts.get("approve_micro_cleanup", 0),
        "dirty_stutter_count": counts.get("dirty_stutter_unit", 0),
        "duplicate_take_covered_count": counts.get("duplicate_take_covered", 0),
        "micro_cleanup_covered_count": counts.get("micro_cleanup_covered", 0),
        "required_clean_unit_covered_count": counts.get("required_clean_unit_covered", 0),
        "not_required_filler_count": counts.get("not_required_filler", 0),
        "api_key_leaked": False,
    }
