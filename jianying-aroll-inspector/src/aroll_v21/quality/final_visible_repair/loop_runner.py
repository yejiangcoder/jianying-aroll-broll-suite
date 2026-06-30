from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from aroll_v21.quality.final_caption_visible_repeat import build_final_caption_visible_repeat_gate
from aroll_v21.quality.final_visible_repair.context import FinalVisibleRepairContext
from aroll_v21.quality.final_visible_repair.loop_state import FinalVisibleRepairLoopState
from aroll_v21.quality.final_visible_repair.pipeline import run_final_visible_repair_pipeline_once
from aroll_v21.quality.final_visible_repair.registry import (
    FinalVisibleRepairRuleRegistry,
    build_gate_candidate_repair_rules,
)
from aroll_v21.quality.final_visible_repair.report import _repair_counts


@dataclass(frozen=True)
class FinalVisibleRepairLoopRunResult:
    loop_state: FinalVisibleRepairLoopState
    passes_executed: int


def run_final_visible_repair_loop(
    *,
    repair_context: FinalVisibleRepairContext,
    loop_state: FinalVisibleRepairLoopState,
    rule_registry: FinalVisibleRepairRuleRegistry,
    source_graph: Any,
    max_pass_limit: int,
    timeline_caption_units: Callable[[list[Any], Any], list[Any]],
    effective_timeline_caption_units: Callable[[list[Any], list[Any]], tuple[list[Any], list[dict[str, Any]]]],
    timeline_gate: Callable[[list[Any], list[dict[str, Any]]], dict[str, Any]],
    repair_next_issue: Callable[..., Any],
) -> FinalVisibleRepairLoopRunResult:
    passes_executed = 0
    for pass_index in range(max_pass_limit):
        passes_executed = pass_index + 1
        transaction_result = run_final_visible_repair_pipeline_once(
            context=repair_context,
            final_timeline=loop_state.current_timeline,
            captions=loop_state.current_captions,
            pass_index=pass_index + 1,
            current_signature=loop_state.current_signature,
            seen_signatures=loop_state.seen_signatures,
            rules=rule_registry.transaction_rules,
        )
        transaction_status = loop_state.consume_pipeline_result(transaction_result, pass_index=pass_index + 1)
        if transaction_status == "stop":
            break
        if transaction_status == "accepted":
            continue

        proposal_result = run_final_visible_repair_pipeline_once(
            context=repair_context,
            final_timeline=loop_state.current_timeline,
            captions=loop_state.current_captions,
            pass_index=pass_index + 1,
            current_signature=loop_state.current_signature,
            seen_signatures=loop_state.seen_signatures,
            rules=rule_registry.proposal_transaction_rules,
        )
        proposal_status = loop_state.consume_pipeline_result(proposal_result, pass_index=pass_index + 1)
        if proposal_status == "stop":
            break
        if proposal_status == "accepted":
            continue

        open_tail_result = run_final_visible_repair_pipeline_once(
            context=repair_context,
            final_timeline=loop_state.current_timeline,
            captions=loop_state.current_captions,
            pass_index=pass_index + 1,
            current_signature=loop_state.current_signature,
            seen_signatures=loop_state.seen_signatures,
            rules=rule_registry.open_tail_transaction_rules,
        )
        open_tail_status = loop_state.consume_pipeline_result(open_tail_result, pass_index=pass_index + 1)
        if open_tail_status == "stop":
            break
        if open_tail_status == "accepted":
            continue

        tail_proposal_result = run_final_visible_repair_pipeline_once(
            context=repair_context,
            final_timeline=loop_state.current_timeline,
            captions=loop_state.current_captions,
            pass_index=pass_index + 1,
            current_signature=loop_state.current_signature,
            seen_signatures=loop_state.seen_signatures,
            rules=rule_registry.tail_proposal_transaction_rules,
        )
        tail_proposal_status = loop_state.consume_pipeline_result(tail_proposal_result, pass_index=pass_index + 1)
        if tail_proposal_status == "stop":
            break
        if tail_proposal_status == "accepted":
            continue

        rendered_gate = build_final_caption_visible_repeat_gate(loop_state.current_captions)
        timeline_captions = timeline_caption_units(loop_state.current_timeline, source_graph)
        effective_timeline_captions, timeline_materializations = effective_timeline_caption_units(
            timeline_captions,
            loop_state.current_captions,
        )
        current_timeline_gate = timeline_gate(effective_timeline_captions, timeline_materializations)
        rendered_counts = _repair_counts(rendered_gate)
        timeline_counts = _repair_counts(current_timeline_gate)
        if not any(rendered_counts.values()) and not any(timeline_counts.values()):
            loop_state.stop_reason = "converged"
            break
        gate_candidate_result = run_final_visible_repair_pipeline_once(
            context=repair_context,
            final_timeline=loop_state.current_timeline,
            captions=loop_state.current_captions,
            pass_index=pass_index + 1,
            current_signature=loop_state.current_signature,
            seen_signatures=loop_state.seen_signatures,
            rules=build_gate_candidate_repair_rules(
                repair_next_issue=repair_next_issue,
                rendered_gate=rendered_gate,
                timeline_gate=current_timeline_gate,
                current_captions=loop_state.current_captions,
                effective_timeline_captions=effective_timeline_captions,
            ),
        )
        if gate_candidate_result.transaction is None:
            loop_state.unresolved.append(
                {
                    "pass_index": pass_index + 1,
                    "counts": rendered_counts,
                    "timeline_counts": timeline_counts,
                    "blocker_codes": list(rendered_gate.get("blocker_codes") or []),
                    "timeline_blocker_codes": list(current_timeline_gate.get("blocker_codes") or []),
                    "reason": "no_safe_deterministic_repair_available",
                }
            )
            loop_state.stop_reason = "no_safe_deterministic_repair_available"
            break
        gate_candidate_status = loop_state.consume_pipeline_result(gate_candidate_result, pass_index=pass_index + 1)
        if gate_candidate_status == "stop":
            break
        continue
    return FinalVisibleRepairLoopRunResult(loop_state=loop_state, passes_executed=passes_executed)
