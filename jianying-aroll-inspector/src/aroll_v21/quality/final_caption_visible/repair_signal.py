from __future__ import annotations

from aroll_v21.quality.final_caption_visible.types import (
    FinalCaptionVisiblePolicyDecision,
    FinalCaptionVisiblePolicyVerdict,
    FinalCaptionVisibleRepairSignal,
)


def build_final_caption_visible_repair_signal(
    decisions: list[FinalCaptionVisiblePolicyDecision],
) -> FinalCaptionVisibleRepairSignal:
    repairable_candidates: list[dict] = []
    repairable_issue_types: list[str] = []
    for decision in decisions:
        if decision.verdict != FinalCaptionVisiblePolicyVerdict.REPAIRABLE_FATAL or not decision.repairable:
            continue
        repairable_issue_types.append(decision.issue_type)
        for candidate in decision.candidates:
            row = dict(candidate)
            row["repair_signal_issue_type"] = decision.issue_type
            row["repair_signal_blocker_code"] = decision.blocker_code
            repairable_candidates.append(row)
    return FinalCaptionVisibleRepairSignal(
        repairable_candidates=repairable_candidates,
        repairable_issue_types=sorted(set(repairable_issue_types)),
    )
