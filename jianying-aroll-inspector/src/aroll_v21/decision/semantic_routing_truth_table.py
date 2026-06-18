from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


SemanticRouteClass = Literal["local_only", "deepseek", "structural_gate"]


@dataclass(frozen=True)
class AutoSemanticRoutingTruthRow:
    issue_type: str
    severity: str
    local_confidence: float
    deterministic_action_available: bool
    requires_provider: bool
    provider_called_in_auto: bool
    provider_missing_behavior: str
    fail_closed: bool
    blocker_code: str
    local_only_or_deepseek_or_structural_gate: SemanticRouteClass

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


PROVIDER_REQUIRED_ISSUES = {
    "modifier_redundancy": "V21_FATAL_MODIFIER_REDUNDANCY_UNRESOLVED",
    "self_repair_aborted_phrase": "V21_SELF_REPAIR_ABORTED_PHRASE_UNRESOLVED",
    "semantic_containment": "SEMANTIC_DECISION_NOT_PROVIDED",
    "near_duplicate_take": "SEMANTIC_DECISION_NOT_PROVIDED",
    "visible_caption_repeat": "SEMANTIC_DECISION_NOT_PROVIDED",
}

LOCAL_ONLY_ISSUES = {
    "exact_duplicate": "local_exact_repeat_drop",
    "prefix_suffix_overlap": "compiler_boundary_suffix_prefix_overlap_cleanup",
}

STRUCTURAL_GATE_ISSUES = {
    "audio_coverage_gap": "SUBTITLE_COVERAGE_VALIDATOR_FAILED",
    "text_residue": "actual_text_residue_gate_failed",
    "caption_alignment": "V21_CAPTION_SPOKEN_SPAN_ALIGNMENT_VALIDATOR",
    "speed_drift": "V21_EFFECTIVE_SPEED_DRIFT",
}

V21_AUTO_SEMANTIC_ROUTING_ISSUE_TYPES = (
    "modifier_redundancy",
    "self_repair_aborted_phrase",
    "semantic_containment",
    "near_duplicate_take",
    "visible_caption_repeat",
    "exact_duplicate",
    "prefix_suffix_overlap",
    "audio_coverage_gap",
    "text_residue",
    "caption_alignment",
    "speed_drift",
)


def build_auto_semantic_routing_truth_table() -> list[dict[str, object]]:
    rows: list[AutoSemanticRoutingTruthRow] = []
    for issue_type in V21_AUTO_SEMANTIC_ROUTING_ISSUE_TYPES:
        if issue_type in PROVIDER_REQUIRED_ISSUES:
            rows.append(
                AutoSemanticRoutingTruthRow(
                    issue_type=issue_type,
                    severity="high_or_fatal",
                    local_confidence=0.0,
                    deterministic_action_available=False,
                    requires_provider=True,
                    provider_called_in_auto=True,
                    provider_missing_behavior="write_blocker_and_semantic_request_payload",
                    fail_closed=True,
                    blocker_code=PROVIDER_REQUIRED_ISSUES[issue_type],
                    local_only_or_deepseek_or_structural_gate="deepseek",
                )
            )
            continue
        if issue_type in LOCAL_ONLY_ISSUES:
            rows.append(
                AutoSemanticRoutingTruthRow(
                    issue_type=issue_type,
                    severity="high",
                    local_confidence=0.95,
                    deterministic_action_available=True,
                    requires_provider=False,
                    provider_called_in_auto=False,
                    provider_missing_behavior="provider_not_required",
                    fail_closed=True,
                    blocker_code=LOCAL_ONLY_ISSUES[issue_type],
                    local_only_or_deepseek_or_structural_gate="local_only",
                )
            )
            continue
        rows.append(
            AutoSemanticRoutingTruthRow(
                issue_type=issue_type,
                severity="structural",
                local_confidence=1.0,
                deterministic_action_available=False,
                requires_provider=False,
                provider_called_in_auto=False,
                provider_missing_behavior="provider_not_applicable_structural_gate",
                fail_closed=True,
                blocker_code=STRUCTURAL_GATE_ISSUES[issue_type],
                local_only_or_deepseek_or_structural_gate="structural_gate",
            )
        )
    return [row.to_dict() for row in rows]
