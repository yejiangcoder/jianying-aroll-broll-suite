from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aroll_v21.quality.final_timeline_repair_apply import recompute_final_timeline_safe_handles
from aroll_v21.quality.final_visible_repair.context import FinalVisibleRepairContext
from aroll_v21.quality.final_visible_repair.loop_state import FinalVisibleRepairLoopState
from aroll_v21.quality.final_visible_repair.pipeline import run_final_visible_repair_pipeline_once
from aroll_v21.quality.final_visible_repair.registry import FinalVisibleRepairRuleRegistry


@dataclass(frozen=True)
class FinalVisibleRepairPostLoopResult:
    loop_state: FinalVisibleRepairLoopState


def run_final_visible_repair_post_loop(
    *,
    repair_context: FinalVisibleRepairContext,
    loop_state: FinalVisibleRepairLoopState,
    rule_registry: FinalVisibleRepairRuleRegistry,
    source_graph: Any,
) -> FinalVisibleRepairPostLoopResult:
    residual_result = run_final_visible_repair_pipeline_once(
        context=repair_context,
        final_timeline=loop_state.current_timeline,
        captions=loop_state.current_captions,
        pass_index=len(loop_state.actions) + 1,
        current_signature=loop_state.current_signature,
        seen_signatures=loop_state.seen_signatures,
        rules=rule_registry.residual_transaction_rules,
    )
    loop_state.consume_pipeline_result(residual_result, pass_index=len(loop_state.actions) + 1)

    for caption_only_finalizer_rule in rule_registry.caption_only_finalizer_rules:
        caption_only_result = run_final_visible_repair_pipeline_once(
            context=repair_context,
            final_timeline=loop_state.current_timeline,
            captions=loop_state.current_captions,
            pass_index=len(loop_state.actions) + 1,
            current_signature=loop_state.current_signature,
            seen_signatures=loop_state.seen_signatures,
            rules=[caption_only_finalizer_rule],
        )
        caption_only_status = loop_state.consume_pipeline_result(
            caption_only_result,
            pass_index=len(loop_state.actions) + 1,
        )
        if caption_only_status == "stop":
            break

    final_safe_handle_result = recompute_final_timeline_safe_handles(
        final_timeline=loop_state.current_timeline,
        captions=loop_state.current_captions,
        source_graph=source_graph,
        render_captions=repair_context.render_captions,
        pass_index=len(loop_state.actions) + 1,
    )
    if final_safe_handle_result is not None:
        loop_state.current_timeline = final_safe_handle_result.final_timeline
        loop_state.current_captions = final_safe_handle_result.captions
        loop_state.actions.extend([final_safe_handle_result.action])
        loop_state.current_signature = repair_context.repair_state_signature(
            loop_state.current_timeline,
            loop_state.current_captions,
        )
        loop_state.seen_signatures.add(loop_state.current_signature)

    return FinalVisibleRepairPostLoopResult(loop_state=loop_state)
