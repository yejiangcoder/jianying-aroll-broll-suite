from __future__ import annotations

from typing import Any

from aroll_v21.quality.final_visible_repair.loop_state import FinalVisibleRepairLoopState
from aroll_v21.quality.final_visible_repair.report import _repair_counts, _unique


def build_final_visible_caption_repair_report(
    *,
    loop_state: FinalVisibleRepairLoopState,
    rule_registry: Any,
    initial_gate: dict[str, Any],
    initial_timeline_gate: dict[str, Any],
    final_gate: dict[str, Any],
    final_timeline_gate: dict[str, Any],
    initial_semantic_junk_report: dict[str, Any],
    final_semantic_junk_report: dict[str, Any],
    pre_visible_semantic_junk_min_confidence: float,
    initial_repeated_island_candidates: list[dict[str, Any]],
    final_repeated_island_candidates: list[dict[str, Any]],
    final_effective_timeline_captions: list[Any],
    final_materializations: list[dict[str, Any]],
    final_counts: dict[str, int],
    final_timeline_counts: dict[str, int],
    repair_success: bool,
    max_pass_limit: int,
    passes_executed: int,
    final_visible_recheck_decisions: list[str],
) -> dict[str, Any]:
    semantic_junk_actions = [
        action
        for action in loop_state.actions
        if str(action.get("issue_type") or "") == "pre_visible_semantic_junk_candidate"
    ]
    enriched_semantic_junk_report = {
        **final_semantic_junk_report,
        "pre_visible_semantic_junk_audit_only": False,
        "pre_visible_semantic_junk_candidate_detector_audit_only": True,
        "pre_visible_semantic_junk_timeline_mutation_allowed": True,
        "pre_visible_semantic_junk_deterministic_apply_enabled": True,
        "pre_visible_semantic_junk_deterministic_apply_policy": "local_high_confidence_drop_fragment_only",
        "pre_visible_semantic_junk_deterministic_apply_min_confidence": pre_visible_semantic_junk_min_confidence,
        "pre_visible_semantic_junk_repair_action_count": len(semantic_junk_actions),
        "pre_visible_semantic_junk_repair_actions": semantic_junk_actions,
    }
    boundary_restart_actions = [
        action
        for action in loop_state.actions
        if str(action.get("issue_type") or "") == "boundary_restart"
    ]
    repeated_island_actions = [
        action
        for action in loop_state.actions
        if str(action.get("issue_type") or "") == "repeated_island"
    ]
    timeline_repair_proposal_actions = [
        action
        for action in loop_state.actions
        if str(action.get("proposal_id") or "")
    ]
    final_timeline_intent_actions = [
        action
        for action in loop_state.actions
        if str(action.get("issue_type") or "") == "final_timeline_repair_intent"
    ]
    transaction_actions = [
        action
        for action in loop_state.actions
        if str(action.get("repair_transaction_rule_name") or "")
    ]
    return {
        "final_visible_repair_enabled": True,
        "final_visible_repair_attempted": (
            bool(loop_state.actions)
            or any(_repair_counts(initial_gate).values())
            or any(_repair_counts(initial_timeline_gate).values())
        ),
        "final_visible_repair_success": repair_success,
        "final_visible_repair_max_passes": max_pass_limit,
        "final_visible_repair_passes_executed": passes_executed,
        "final_visible_repair_stop_reason": loop_state.stop_reason,
        "final_visible_repair_no_progress_detected": loop_state.stop_reason == "no_progress_detected",
        "final_visible_repair_max_pass_exhausted": any(
            str(row.get("reason") or "") == "max_repair_passes_exhausted"
            for row in loop_state.unresolved
        ),
        "final_visible_repair_progress_state_count": len(loop_state.seen_signatures),
        "final_visible_repair_action_count": len(loop_state.actions),
        "final_visible_repair_actions": loop_state.actions,
        "final_visible_repair_transaction_count": len(transaction_actions),
        "final_visible_repair_transaction_rule_names": _unique(
            [str(action.get("repair_transaction_rule_name") or "") for action in transaction_actions]
        ),
        "final_visible_repair_pipeline_rule_names": [rule.name for rule in rule_registry.transaction_rules],
        "final_visible_repair_unresolved": loop_state.unresolved,
        "final_visible_repair_initial_counts": _repair_counts(initial_gate),
        "final_visible_repair_initial_timeline_counts": _repair_counts(initial_timeline_gate),
        "final_visible_repair_final_counts": final_counts,
        "final_visible_repair_final_timeline_counts": final_timeline_counts,
        "pre_visible_semantic_junk_initial_report": initial_semantic_junk_report,
        "pre_visible_semantic_junk_report": enriched_semantic_junk_report,
        "pre_visible_semantic_junk_initial_candidate_count": int(
            initial_semantic_junk_report.get("pre_visible_semantic_junk_candidate_count") or 0
        ),
        "pre_visible_semantic_junk_final_candidate_count": int(
            enriched_semantic_junk_report.get("pre_visible_semantic_junk_candidate_count") or 0
        ),
        "pre_visible_semantic_junk_repair_action_count": len(semantic_junk_actions),
        "pre_visible_semantic_junk_repair_actions": semantic_junk_actions,
        "pre_visible_semantic_junk_audit_only": False,
        "pre_visible_semantic_junk_candidate_detector_audit_only": True,
        "pre_visible_semantic_junk_timeline_mutation_allowed": True,
        "pre_visible_semantic_junk_deterministic_apply_enabled": True,
        "pre_visible_semantic_junk_deterministic_apply_policy": "local_high_confidence_drop_fragment_only",
        "repeated_island_initial_candidate_count": len(initial_repeated_island_candidates),
        "repeated_island_initial_candidates": initial_repeated_island_candidates,
        "repeated_island_candidate_count": len(final_repeated_island_candidates),
        "repeated_island_high_confidence_count": _repeated_island_confidence_count(
            final_repeated_island_candidates,
            "high",
        ),
        "repeated_island_medium_confidence_count": _repeated_island_confidence_count(
            final_repeated_island_candidates,
            "medium",
        ),
        "repeated_island_low_confidence_count": _repeated_island_confidence_count(
            final_repeated_island_candidates,
            "low",
        ),
        "repeated_island_warning_count": _repeated_island_confidence_count(
            final_repeated_island_candidates,
            "medium",
        ),
        "repeated_island_candidates": final_repeated_island_candidates,
        "repeated_island_repair_action_count": len(repeated_island_actions),
        "repeated_island_repair_actions": repeated_island_actions,
        "boundary_restart_repair_action_count": len(boundary_restart_actions),
        "boundary_restart_repair_actions": boundary_restart_actions,
        "timeline_repair_proposal_action_count": len(timeline_repair_proposal_actions),
        "timeline_repair_proposal_actions": timeline_repair_proposal_actions,
        "final_timeline_repair_intent_action_count": len(final_timeline_intent_actions),
        "final_timeline_repair_intent_actions": final_timeline_intent_actions,
        "final_visible_effective_caption_count": len(final_effective_timeline_captions),
        "caption_only_materialized_merge_count": len(final_materializations),
        "caption_only_materialized_merges": final_materializations,
        "caption_only_consumed_caption_ids": [
            caption_id
            for row in final_materializations
            for caption_id in list(row.get("consumed_caption_ids") or [])
        ],
        "source_boundary_prefix_repair_count": sum(
            1
            for action in loop_state.actions
            if str(action.get("decision") or "") == "prepend_source_boundary_prefix"
        ),
        "final_visible_repair_initial_blocker_codes": list(initial_gate.get("blocker_codes") or []),
        "final_visible_repair_initial_timeline_blocker_codes": list(initial_timeline_gate.get("blocker_codes") or []),
        "final_visible_repair_final_blocker_codes": list(final_gate.get("blocker_codes") or []),
        "final_visible_repair_final_timeline_blocker_codes": list(final_timeline_gate.get("blocker_codes") or []),
        "final_visible_recheck_allowed_decisions": list(final_visible_recheck_decisions),
        "final_visible_recheck_required_count": max(
            int(final_counts.get("semantic_garbage_or_asr_suspect_count") or 0),
            int(final_timeline_counts.get("semantic_garbage_or_asr_suspect_count") or 0),
        ),
    }


def _repeated_island_confidence_count(
    candidates: list[dict[str, Any]],
    confidence: str,
) -> int:
    return sum(1 for candidate in candidates if str(candidate.get("confidence") or "") == confidence)
