from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from aroll_v21.ir.models import CaptionRenderUnit, FinalTimelineSegment
from aroll_v21.quality.final_visible_repair.context import FinalVisibleRepairContext, RepairStateSignature
from aroll_v21.quality.final_visible_repair.result import _RepairStep


@dataclass(frozen=True)
class FinalVisibleRepairRuleOutcome:
    final_timeline: list[FinalTimelineSegment] | None = None
    captions: list[CaptionRenderUnit] | None = None
    actions: list[dict[str, Any]] | None = None
    timeline_changed: bool = False
    unresolved: dict[str, Any] | None = None


class RepairRule(Protocol):
    name: str

    def try_repair(
        self,
        *,
        context: FinalVisibleRepairContext,
        state: "FinalVisibleRepairState",
        pass_index: int,
    ) -> _RepairStep | FinalVisibleRepairRuleOutcome | None:
        no_step: _RepairStep | FinalVisibleRepairRuleOutcome | None = None
        return no_step


@dataclass(frozen=True)
class FinalVisibleRepairState:
    final_timeline: list[FinalTimelineSegment]
    captions: list[CaptionRenderUnit]
    signature: RepairStateSignature
    seen_signatures: set[RepairStateSignature]


@dataclass(frozen=True)
class FinalVisibleRepairTransaction:
    rule_name: str
    pass_index: int
    action: dict[str, Any]
    before_signature: RepairStateSignature
    after_signature: RepairStateSignature
    accepted: bool
    rejection_reason: str = ""
    actions: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class FinalVisibleRepairPipelineResult:
    final_timeline: list[FinalTimelineSegment]
    captions: list[CaptionRenderUnit]
    signature: RepairStateSignature
    transaction: FinalVisibleRepairTransaction | None
    unresolved: dict[str, Any] | None = None
    unresolved_rule_name: str = ""


@dataclass(frozen=True)
class ProposalRepairRule:
    name: str
    repair_with_proposal: Callable[..., tuple[_RepairStep | None, dict[str, Any] | None]]
    include_current_captions: bool = False

    def try_repair(
        self,
        *,
        context: FinalVisibleRepairContext,
        state: FinalVisibleRepairState,
        pass_index: int,
    ) -> FinalVisibleRepairRuleOutcome:
        base_kwargs: dict[str, Any] = {
            "final_timeline": state.final_timeline,
            "source_graph": context.source_graph,
            "render_captions": context.render_captions,
            "pass_index": pass_index,
        }
        if self.include_current_captions:
            base_kwargs["captions"] = state.captions
        step, unresolved = self.repair_with_proposal(**base_kwargs)
        if unresolved is not None:
            return FinalVisibleRepairRuleOutcome(unresolved=unresolved)
        if step is None:
            return FinalVisibleRepairRuleOutcome()
        next_captions = None if step.timeline_changed else step.captions
        return FinalVisibleRepairRuleOutcome(
            final_timeline=step.final_timeline,
            captions=next_captions,
            actions=[step.action],
            timeline_changed=step.timeline_changed,
        )


@dataclass(frozen=True)
class StepRepairRule:
    name: str
    repair_step: Callable[..., _RepairStep | None]
    include_current_captions: bool = False
    include_render_captions: bool = False

    def try_repair(
        self,
        *,
        context: FinalVisibleRepairContext,
        state: FinalVisibleRepairState,
        pass_index: int,
    ) -> _RepairStep | None:
        kwargs: dict[str, Any] = {
            "final_timeline": state.final_timeline,
            "source_graph": context.source_graph,
            "pass_index": pass_index,
        }
        if self.include_current_captions:
            kwargs["captions"] = state.captions
        if self.include_render_captions:
            kwargs["render_captions"] = context.render_captions
        return self.repair_step(**kwargs)


def _annotate_transaction_action(
    action: dict[str, Any],
    *,
    rule_name: str,
    pass_index: int,
    accepted: bool,
    rejection_reason: str,
) -> dict[str, Any]:
    return {
        **dict(action),
        "repair_transaction_rule_name": rule_name,
        "repair_transaction_pass_index": pass_index,
        "repair_transaction_accepted": accepted,
        "repair_transaction_rejection_reason": rejection_reason,
    }


def _build_transaction(
    *,
    rule_name: str,
    pass_index: int,
    actions: list[dict[str, Any]],
    before_signature: RepairStateSignature,
    after_signature: RepairStateSignature,
    seen_signatures: set[RepairStateSignature],
) -> FinalVisibleRepairTransaction:
    rejection_reason = ""
    if after_signature == before_signature or after_signature in seen_signatures:
        rejection_reason = "no_progress_detected"
    accepted = not rejection_reason
    annotated_actions = [
        _annotate_transaction_action(
            action,
            rule_name=rule_name,
            pass_index=pass_index,
            accepted=accepted,
            rejection_reason=rejection_reason,
        )
        for action in actions
    ]
    primary_action = annotated_actions[0] if annotated_actions else {}
    return FinalVisibleRepairTransaction(
        rule_name=rule_name,
        pass_index=pass_index,
        action=primary_action,
        actions=annotated_actions,
        before_signature=before_signature,
        after_signature=after_signature,
        accepted=accepted,
        rejection_reason=rejection_reason,
    )


def run_final_visible_repair_pipeline_once(
    *,
    context: FinalVisibleRepairContext,
    final_timeline: list[FinalTimelineSegment],
    captions: list[CaptionRenderUnit],
    pass_index: int,
    current_signature: RepairStateSignature,
    seen_signatures: set[RepairStateSignature],
    rules: list[RepairRule],
) -> FinalVisibleRepairPipelineResult:
    state = FinalVisibleRepairState(
        final_timeline=final_timeline,
        captions=captions,
        signature=current_signature,
        seen_signatures=seen_signatures,
    )
    for rule in rules:
        rule_result = rule.try_repair(context=context, state=state, pass_index=pass_index)
        if rule_result is None:
            continue
        if isinstance(rule_result, FinalVisibleRepairRuleOutcome):
            if rule_result.unresolved is not None:
                return FinalVisibleRepairPipelineResult(
                    final_timeline=final_timeline,
                    captions=captions,
                    signature=current_signature,
                    transaction=None,
                    unresolved=rule_result.unresolved,
                    unresolved_rule_name=rule.name,
                )
            if not rule_result.actions:
                continue
            if rule_result.final_timeline is None:
                next_timeline = context.repack_timeline(final_timeline)
            else:
                next_timeline = context.repack_timeline(rule_result.final_timeline)
            if rule_result.captions is not None:
                next_captions = rule_result.captions
            elif rule_result.timeline_changed:
                next_captions = context.render_captions_preserving_caption_only_materializations(
                    next_timeline,
                    captions,
                    context.render_captions,
                )
            else:
                next_captions = captions
            next_signature = context.repair_state_signature(next_timeline, next_captions)
            transaction = _build_transaction(
                rule_name=rule.name,
                pass_index=pass_index,
                actions=rule_result.actions,
                before_signature=current_signature,
                after_signature=next_signature,
                seen_signatures=seen_signatures,
            )
            return FinalVisibleRepairPipelineResult(
                final_timeline=next_timeline,
                captions=next_captions,
                signature=next_signature,
                transaction=transaction,
            )
        step = rule_result
        next_timeline = context.repack_timeline(step.final_timeline)
        if step.timeline_changed:
            next_captions = context.render_captions_preserving_caption_only_materializations(
                next_timeline,
                captions,
                context.render_captions,
            )
        else:
            next_captions = context.renumber_captions(step.captions)
        next_signature = context.repair_state_signature(next_timeline, next_captions)
        transaction = _build_transaction(
            rule_name=rule.name,
            pass_index=pass_index,
            actions=[step.action],
            before_signature=current_signature,
            after_signature=next_signature,
            seen_signatures=seen_signatures,
        )
        return FinalVisibleRepairPipelineResult(
            final_timeline=next_timeline,
            captions=next_captions,
            signature=next_signature,
            transaction=transaction,
        )
    no_transaction: FinalVisibleRepairTransaction | None = None
    return FinalVisibleRepairPipelineResult(
        final_timeline=final_timeline,
        captions=captions,
        signature=current_signature,
        transaction=no_transaction,
    )
