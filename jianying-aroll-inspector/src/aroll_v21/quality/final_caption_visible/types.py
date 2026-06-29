from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from aroll_v21.ir.models import CaptionRenderUnit


class FinalCaptionVisiblePolicyVerdict(str, Enum):
    BLOCKER_FATAL = "BLOCKER_FATAL"
    REPAIRABLE_FATAL = "REPAIRABLE_FATAL"
    WARNING = "WARNING"
    ALLOW = "ALLOW"
    HUMAN_REVIEW = "HUMAN_REVIEW"


@dataclass(frozen=True)
class FinalCaptionVisibleEvidence:
    captions: list[CaptionRenderUnit]
    raw_containment_candidates: list[dict[str, Any]] = field(default_factory=list)
    raw_prefix_suffix_candidates: list[dict[str, Any]] = field(default_factory=list)
    raw_ngram_candidates: list[dict[str, Any]] = field(default_factory=list)
    raw_near_duplicate_candidates: list[dict[str, Any]] = field(default_factory=list)
    modifier_redundancy_candidates: list[dict[str, Any]] = field(default_factory=list)
    self_repair_candidates: list[dict[str, Any]] = field(default_factory=list)
    dangling_candidates: list[dict[str, Any]] = field(default_factory=list)
    semantic_suspect_candidates: list[dict[str, Any]] = field(default_factory=list)
    semantic_integrity_candidates: list[dict[str, Any]] = field(default_factory=list)
    raw_cross_caption_containment_candidates: list[dict[str, Any]] = field(default_factory=list)
    raw_restart_repeat_candidates: list[dict[str, Any]] = field(default_factory=list)

    def repeat_raw_candidates(self) -> list[dict[str, Any]]:
        return [
            *self.raw_containment_candidates,
            *self.raw_prefix_suffix_candidates,
            *self.raw_ngram_candidates,
            *self.raw_near_duplicate_candidates,
            *self.raw_cross_caption_containment_candidates,
            *self.raw_restart_repeat_candidates,
        ]


@dataclass(frozen=True)
class FinalCaptionVisibleClassification:
    classified_repeat_candidates: list[dict[str, Any]]
    repeat_warning_candidates: list[dict[str, Any]]
    repeat_allowed_candidates: list[dict[str, Any]]
    visible_repeat_candidates: list[dict[str, Any]]
    containment_candidates: list[dict[str, Any]]
    prefix_suffix_candidates: list[dict[str, Any]]
    ngram_candidates: list[dict[str, Any]]
    near_duplicate_candidates: list[dict[str, Any]]
    cross_caption_containment_candidates: list[dict[str, Any]]
    restart_repeat_candidates: list[dict[str, Any]]
    human_review_candidates: list[dict[str, Any]]


@dataclass(frozen=True)
class FinalCaptionVisiblePolicyDecision:
    issue_type: str
    verdict: FinalCaptionVisiblePolicyVerdict
    candidates: list[dict[str, Any]] = field(default_factory=list)
    blocker_code: str = ""
    repairable: bool = False
    reason: str = ""

    def to_report(self) -> dict[str, Any]:
        return {
            "issue_type": self.issue_type,
            "verdict": self.verdict.value,
            "candidate_count": len(self.candidates),
            "blocker_code": self.blocker_code,
            "repairable": bool(self.repairable),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FinalCaptionVisibleRepairSignal:
    repairable_candidates: list[dict[str, Any]]
    repairable_issue_types: list[str]

    def to_report(self) -> dict[str, Any]:
        return {
            "repairable_candidate_count": len(self.repairable_candidates),
            "repairable_issue_types": list(self.repairable_issue_types),
            "repairable_candidates": list(self.repairable_candidates),
        }
