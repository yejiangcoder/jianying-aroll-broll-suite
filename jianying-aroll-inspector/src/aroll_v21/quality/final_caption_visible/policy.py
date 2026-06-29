from __future__ import annotations

from collections import Counter

from aroll_v21.quality.final_caption_visible.types import (
    FinalCaptionVisibleClassification,
    FinalCaptionVisibleEvidence,
    FinalCaptionVisiblePolicyDecision,
    FinalCaptionVisiblePolicyVerdict,
)


BLOCKING_POLICY_VERDICTS = {
    FinalCaptionVisiblePolicyVerdict.BLOCKER_FATAL,
    FinalCaptionVisiblePolicyVerdict.REPAIRABLE_FATAL,
    FinalCaptionVisiblePolicyVerdict.HUMAN_REVIEW,
}


def build_final_caption_visible_policy(
    evidence: FinalCaptionVisibleEvidence,
    classification: FinalCaptionVisibleClassification,
) -> list[FinalCaptionVisiblePolicyDecision]:
    decisions: list[FinalCaptionVisiblePolicyDecision] = []
    _append_if_candidates(
        decisions,
        issue_type="visible_repeat",
        verdict=FinalCaptionVisiblePolicyVerdict.REPAIRABLE_FATAL,
        candidates=classification.visible_repeat_candidates,
        blocker_code="V21_FINAL_CAPTION_VISIBLE_REPEAT_GATE_FAILED",
        repairable=True,
        reason="classified blocking visible repeat remains in final captions",
    )
    _append_if_candidates(
        decisions,
        issue_type="dangling_prefix_suffix",
        verdict=FinalCaptionVisiblePolicyVerdict.REPAIRABLE_FATAL,
        candidates=evidence.dangling_candidates,
        blocker_code="V21_FINAL_VISIBLE_DANGLING_PREFIX_SUFFIX",
        repairable=True,
        reason="dangling prefix or suffix is unsafe in visible final captions",
    )
    _append_if_candidates(
        decisions,
        issue_type="semantic_garbage_or_asr_suspect",
        verdict=FinalCaptionVisiblePolicyVerdict.REPAIRABLE_FATAL,
        candidates=evidence.semantic_suspect_candidates,
        blocker_code="V21_FINAL_VISIBLE_SEMANTIC_GARBAGE_OR_ASR_SUSPECT",
        repairable=True,
        reason="visible caption contains semantic garbage or ASR restart suspect",
    )
    _append_if_candidates(
        decisions,
        issue_type="semantic_integrity",
        verdict=FinalCaptionVisiblePolicyVerdict.BLOCKER_FATAL,
        candidates=evidence.semantic_integrity_candidates,
        blocker_code="V21_FINAL_SEMANTIC_INTEGRITY_GATE_FAILED",
        reason="final caption semantic integrity failed",
    )
    _append_if_candidates(
        decisions,
        issue_type="cross_caption_semantic_containment",
        verdict=FinalCaptionVisiblePolicyVerdict.REPAIRABLE_FATAL,
        candidates=classification.cross_caption_containment_candidates,
        blocker_code="V21_FINAL_VISIBLE_CROSS_CAPTION_SEMANTIC_CONTAINMENT",
        repairable=True,
        reason="classified cross-caption containment remains blocking",
    )
    _append_if_candidates(
        decisions,
        issue_type="restart_repeat_visible",
        verdict=FinalCaptionVisiblePolicyVerdict.REPAIRABLE_FATAL,
        candidates=classification.restart_repeat_candidates,
        blocker_code="V21_FINAL_VISIBLE_RESTART_REPEAT",
        repairable=True,
        reason="classified visible restart repeat remains blocking",
    )
    _append_if_candidates(
        decisions,
        issue_type="modifier_redundancy",
        verdict=FinalCaptionVisiblePolicyVerdict.BLOCKER_FATAL,
        candidates=evidence.modifier_redundancy_candidates,
        blocker_code="V21_FATAL_MODIFIER_REDUNDANCY_UNRESOLVED",
        reason="modifier redundancy reached final visible captions",
    )
    _append_if_candidates(
        decisions,
        issue_type="self_repair_aborted_phrase",
        verdict=FinalCaptionVisiblePolicyVerdict.BLOCKER_FATAL,
        candidates=evidence.self_repair_candidates,
        blocker_code="V21_SELF_REPAIR_ABORTED_PHRASE_UNRESOLVED",
        reason="self-repair aborted phrase reached final visible captions",
    )
    _append_if_candidates(
        decisions,
        issue_type="visible_repeat_human_review",
        verdict=FinalCaptionVisiblePolicyVerdict.HUMAN_REVIEW,
        candidates=classification.human_review_candidates,
        blocker_code="V21_FINAL_VISIBLE_HUMAN_REVIEW_REQUIRED",
        reason="classified repeat requires human review before final write",
    )
    _append_if_candidates(
        decisions,
        issue_type="visible_repeat_warning",
        verdict=FinalCaptionVisiblePolicyVerdict.WARNING,
        candidates=classification.repeat_warning_candidates,
        reason="classified repeat is reported as non-blocking warning",
    )
    _append_if_candidates(
        decisions,
        issue_type="visible_repeat_allow",
        verdict=FinalCaptionVisiblePolicyVerdict.ALLOW,
        candidates=classification.repeat_allowed_candidates,
        reason="classified repeat is allowed by policy",
    )
    return decisions


def blocking_policy_blocker_codes(decisions: list[FinalCaptionVisiblePolicyDecision]) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()
    for decision in decisions:
        if decision.verdict not in BLOCKING_POLICY_VERDICTS or not decision.blocker_code:
            continue
        if decision.blocker_code in seen:
            continue
        seen.add(decision.blocker_code)
        codes.append(decision.blocker_code)
    return codes


def policy_decision_counts(decisions: list[FinalCaptionVisiblePolicyDecision]) -> dict[str, int]:
    counts = Counter(decision.verdict.value for decision in decisions)
    return dict(sorted(counts.items()))


def _append_if_candidates(
    decisions: list[FinalCaptionVisiblePolicyDecision],
    *,
    issue_type: str,
    verdict: FinalCaptionVisiblePolicyVerdict,
    candidates: list[dict],
    blocker_code: str = "",
    repairable: bool = False,
    reason: str = "",
) -> None:
    if not candidates:
        return
    decisions.append(
        FinalCaptionVisiblePolicyDecision(
            issue_type=issue_type,
            verdict=verdict,
            candidates=list(candidates),
            blocker_code=blocker_code,
            repairable=repairable,
            reason=reason,
        )
    )
