from __future__ import annotations

from aroll_v21.quality.final_caption_visible.types import (
    FinalCaptionVisibleClassification,
    FinalCaptionVisibleEvidence,
)
from aroll_v21.quality.final_visible_repeat_classification import (
    allowed_repeat_candidates,
    blocking_repeat_candidates,
    classify_final_visible_repeat_candidates,
    warning_repeat_candidates,
)


def classify_final_caption_visible_evidence(
    evidence: FinalCaptionVisibleEvidence,
) -> FinalCaptionVisibleClassification:
    classified_repeat_candidates = classify_final_visible_repeat_candidates(
        evidence.captions,
        evidence.repeat_raw_candidates(),
    )
    repeat_warning_candidates = warning_repeat_candidates(classified_repeat_candidates)
    repeat_allowed_candidates = allowed_repeat_candidates(classified_repeat_candidates)
    visible_repeat_candidates = blocking_repeat_candidates(classified_repeat_candidates)
    restart_repeat_reasons = {str(candidate.get("reason") or "") for candidate in evidence.raw_restart_repeat_candidates}
    return FinalCaptionVisibleClassification(
        classified_repeat_candidates=classified_repeat_candidates,
        repeat_warning_candidates=repeat_warning_candidates,
        repeat_allowed_candidates=repeat_allowed_candidates,
        visible_repeat_candidates=visible_repeat_candidates,
        containment_candidates=_candidates_by_reason(visible_repeat_candidates, "containment_repeat"),
        prefix_suffix_candidates=_candidates_by_reason(visible_repeat_candidates, "prefix_suffix_overlap"),
        ngram_candidates=_candidates_by_reason(visible_repeat_candidates, "ngram_repeat"),
        near_duplicate_candidates=_candidates_by_reason(visible_repeat_candidates, "near_duplicate_visible_caption"),
        cross_caption_containment_candidates=_candidates_by_reason(
            visible_repeat_candidates,
            "cross_caption_semantic_containment",
        ),
        restart_repeat_candidates=[
            candidate
            for candidate in visible_repeat_candidates
            if str(candidate.get("reason") or "") in restart_repeat_reasons
        ],
        human_review_candidates=[
            candidate
            for candidate in classified_repeat_candidates
            if str(candidate.get("severity") or "") == "human_review"
            or str(candidate.get("classification") or "") == "requires_human_review"
        ],
    )


def _candidates_by_reason(candidates: list[dict], reason: str) -> list[dict]:
    return [candidate for candidate in candidates if candidate.get("reason") == reason]
