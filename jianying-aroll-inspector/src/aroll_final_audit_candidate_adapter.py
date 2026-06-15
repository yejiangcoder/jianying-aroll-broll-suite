from __future__ import annotations

from typing import Any


LLM_REQUIRED_TYPES = {"semantic_containment_repeat", "prefix_overlap", "near_repeat"}


def _overlaps(row: dict[str, Any], start_us: int, end_us: int, *, start_key: str = "start_us", end_key: str = "end_us") -> bool:
    row_start = int(row.get(start_key) or row.get("target_start_us") or row.get("source_start_us") or 0)
    row_end = int(row.get(end_key) or row.get("target_end_us") or row.get("source_end_us") or row_start)
    return row_end >= start_us and row_start <= end_us


def _matches_text(row: dict[str, Any], *texts: str) -> bool:
    haystack = str(row.get("fragment_text") or row.get("text") or row.get("subtitle_text") or "")
    return any(text and (text in haystack or haystack in text) for text in texts)


def build_final_audit_llm_candidates(
    audit: dict[str, Any],
    display_plan: list[dict[str, Any]],
    source_subtitles: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for issue in audit.get("issues") or []:
        if not issue.get("requires_llm") and issue.get("issue_type") not in LLM_REQUIRED_TYPES:
            continue
        left_text = str(issue.get("left_text") or "")
        right_text = str(issue.get("right_text") or "")
        candidate_id = f"final_{issue.get('issue_id')}"
        src_start = int(issue.get("source_start_us") or 0)
        src_end = int(issue.get("source_end_us") or src_start)
        target_start = int(issue.get("target_start_us") or 0)
        target_end = int(issue.get("target_end_us") or target_start)
        nearby_source = [
            {
                "subtitle_index": row.get("subtitle_index"),
                "subtitle_text": row.get("subtitle_text"),
                "start_us": row.get("start_us"),
                "end_us": row.get("end_us"),
            }
            for row in source_subtitles
            if int(row.get("end_us") or 0) >= src_start - 3_000_000 and int(row.get("start_us") or 0) <= src_end + 3_000_000
        ][:12]
        nearby_final = [
            {
                "fragment_id": row.get("fragment_id"),
                "text": row.get("fragment_text") or row.get("text"),
                "target_start_us": row.get("target_start_us"),
                "target_end_us": row.get("target_end_us"),
                "source_start_us": row.get("source_start_us"),
                "source_end_us": row.get("source_end_us"),
            }
            for row in display_plan
            if _overlaps(row, target_start - 3_000_000, target_end + 3_000_000, start_key="target_start_us", end_key="target_end_us")
        ][:12]
        final_matches = [
            {
                "fragment_id": row.get("fragment_id"),
                "text": row.get("fragment_text") or row.get("text"),
                "target_start_us": row.get("target_start_us"),
                "target_end_us": row.get("target_end_us"),
            }
            for row in display_plan
            if _matches_text(row, left_text, right_text)
        ][:8]
        candidates.append(
            {
                "candidate_id": candidate_id,
                "candidate_type": f"final_{issue.get('issue_type')}",
                "source_text": f"{left_text}\n{right_text}".strip(),
                "left_text": left_text,
                "right_text": right_text,
                "proposed_action": issue.get("recommended_action"),
                "allowed_final_actions": ["drop_left", "drop_right", "keep_both", "self_review"],
                "requires_llm": True,
                "risk_level": "high",
                "source_start_us": src_start,
                "source_end_us": src_end,
                "left_source_start_us": issue.get("left_source_start_us") or issue.get("source_start_us"),
                "left_source_end_us": issue.get("left_source_end_us") or issue.get("source_end_us"),
                "right_source_start_us": issue.get("right_source_start_us"),
                "right_source_end_us": issue.get("right_source_end_us"),
                "target_start_us": target_start,
                "target_end_us": target_end,
                "nearby_source_subtitles": nearby_source,
                "nearby_final_context": nearby_final,
                "candidate_final_matches": final_matches,
                "script_reference_excerpt": "",
                "script_reference_status": "not_provided_for_final_audit",
                "issue": issue,
                "instruction": "Choose drop_left, drop_right, keep_both, or self_review. Only approve deletion if one side is a false start, repeated take, or fully covered by the other side. Keep both if either side carries independent meaning.",
            }
        )
    report = {
        "candidate_count": len(candidates),
        "semantic_containment_candidate_count": sum(1 for row in candidates if "semantic_containment" in str(row.get("candidate_type"))),
        "prefix_overlap_candidate_count": sum(1 for row in candidates if "prefix_overlap" in str(row.get("candidate_type"))),
        "near_repeat_candidate_count": sum(1 for row in candidates if "near_repeat" in str(row.get("candidate_type"))),
    }
    return candidates, report


def summarize_final_audit_llm_results(candidates: list[dict[str, Any]], results: list[dict[str, Any]], call_count: int) -> dict[str, Any]:
    result_by_id = {str(row.get("candidate_id") or row.get("unit_id") or ""): row for row in results}
    approved = 0
    keep = 0
    manual = 0
    missing = 0
    for candidate in candidates:
        result = result_by_id.get(str(candidate.get("candidate_id")))
        if not result:
            missing += 1
            continue
        action = str(result.get("approved_action") or "")
        classification = str(result.get("classification") or "")
        if action in {"drop", "drop_left", "drop_right"} and classification in {"approve_drop", "dirty_stutter_unit", "duplicate_take_covered", "not_required_filler", "required_clean_unit_covered", "semantic_containment_covered"}:
            approved += 1
        elif action == "keep_both" or classification == "keep_both":
            keep += 1
        elif action == "self_review" or classification == "codex_self_review_required":
            manual += 1
        else:
            keep += 1
    return {
        "final_audit_llm_candidate_count": len(candidates),
        "final_audit_llm_call_count": call_count,
        "final_audit_llm_approved_drop_count": approved,
        "final_audit_llm_keep_both_count": keep,
        "final_audit_llm_self_review_count": manual + missing,
        "final_audit_llm_missing_result_count": missing,
    }
