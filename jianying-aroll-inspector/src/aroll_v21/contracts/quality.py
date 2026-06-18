from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any


class _JsonEnum(str, Enum):
    def __str__(self) -> str:
        return str(self.value)


class SemanticMode(_JsonEnum):
    DEFAULT = "default"
    DETERMINISTIC_BASELINE = "deterministic_baseline"
    SEMANTIC_REQUESTS_ONLY = "semantic-requests-only"
    DEEPSEEK = "deepseek"
    FAIL_CLOSED = "fail-closed"


class DecisionSource(_JsonEnum):
    LOCAL_POLICY = "local_policy"
    SEMANTIC_DECISIONS_JSON = "semantic_decisions_json"
    DETERMINISTIC_BASELINE = "deterministic_baseline"
    DEEPSEEK_SEMANTIC_PLANNER = "deepseek_semantic_planner"


class BaselineDecisionKind(_JsonEnum):
    KEEP_ALL = "keep_all"
    DROP_RECOMMENDED = "drop_recommended"


class QualityGateStatus(_JsonEnum):
    PASSED = "passed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class FinalRepeatDecision:
    decision: str
    v21_resolution: str
    drop_index: int | None = None
    decision_source: str = DecisionSource.DETERMINISTIC_BASELINE.value
    semantic_mode: str = SemanticMode.DETERMINISTIC_BASELINE.value
    requires_human_review: bool = False
    reason: str = ""


@dataclass(frozen=True)
class FinalRepeatCandidateView:
    cluster_id: str
    cluster_type: str
    confidence: str
    similarity: float
    recommended_drop_index: int | None = None
    requires_llm: bool = False


@dataclass(frozen=True)
class FinalRepeatConvergenceReport:
    enabled: bool = False
    iterations: int = 0
    dropped_cluster_ids: list[str] = field(default_factory=list)
    dropped_segment_indices: list[int] = field(default_factory=list)
    final_repeat_high_count_before: int = 0
    final_repeat_high_count_after: int = 0
    unresolved_high_cluster_ids: list[str] = field(default_factory=list)
    gate_passed: bool = True
    blocker_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EffectiveSpeedSegmentReport:
    segment_id: str
    expected_speed: float | None
    effective_speed: float | None
    source_duration_us: int
    target_duration_us: int
    drift_ratio: float | None
    gate_passed: bool


@dataclass(frozen=True)
class EffectiveSpeedGateReport:
    gate_passed: bool = True
    expected_speeds: list[float] = field(default_factory=list)
    effective_speed_min: float | None = None
    effective_speed_max: float | None = None
    effective_speed_drift_count: int = 0
    segment_reports: list[EffectiveSpeedSegmentReport] = field(default_factory=list)
    blocker_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VisualPacingReport:
    gate_passed: bool = True
    final_video_segment_count: int = 0
    caption_count: int = 0
    visual_short_segment_count_lt_1200ms: int = 0
    median_segment_duration_us: int = 0
    p10_segment_duration_us: int = 0
    caption_per_video_segment_ratio: float = 0.0
    blocker_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VisualMergeGroup:
    video_segment_id: str
    child_segment_ids: list[str] = field(default_factory=list)
    child_caption_ids: list[str] = field(default_factory=list)
    source_window_id: str = ""
    target_start_us: int = 0
    target_end_us: int = 0
    source_start_us: int = 0
    source_end_us: int = 0
    child_spoken_source_ranges: list[dict[str, Any]] = field(default_factory=list)
    child_spoken_target_ranges: list[dict[str, Any]] = field(default_factory=list)
    bridged_gaps: list[dict[str, Any]] = field(default_factory=list)
    dropped_segment_ids_crossed: list[str] = field(default_factory=list)
    dropped_word_ids_crossed: list[str] = field(default_factory=list)
    dropped_repeat_cluster_ids_crossed: list[str] = field(default_factory=list)
    hidden_repeat_spans_crossed: list[dict[str, Any]] = field(default_factory=list)
    max_bridged_gap_us: int = 0
    total_bridged_gap_us: int = 0
    unspoken_bridge_duration_us: int = 0
    unspoken_bridge_ratio: float = 0.0
    merge_safe: bool = True
    unsafe_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VisualMergeSafetyReport:
    gate_passed: bool = True
    merge_groups: list[VisualMergeGroup] = field(default_factory=list)
    unsafe_merge_group_count: int = 0
    dropped_content_reintroduced_count: int = 0
    max_bridged_gap_us: int = 0
    total_bridged_gap_us: int = 0
    unspoken_bridge_ratio: float = 0.0
    blocker_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CaptionAlignmentReport:
    gate_passed: bool = True
    caption_count: int = 0
    caption_outside_video_count: int = 0
    caption_overlap_count: int = 0
    caption_too_short_count: int = 0
    one_char_caption_count: int = 0
    caption_without_video_container_count: int = 0
    caption_cross_primary_window_count: int = 0
    blocker_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class QualityGateReport:
    gate_passed: bool
    effective_speed_gate: EffectiveSpeedGateReport = field(default_factory=EffectiveSpeedGateReport)
    final_repeat_convergence_gate: FinalRepeatConvergenceReport = field(default_factory=FinalRepeatConvergenceReport)
    visual_pacing_gate: VisualPacingReport = field(default_factory=VisualPacingReport)
    caption_alignment_gate: CaptionAlignmentReport = field(default_factory=CaptionAlignmentReport)
    ready_for_user_manual_qc_preconditions_passed: bool = False
    blocker_codes: list[str] = field(default_factory=list)


def contract_to_dict(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: contract_to_dict(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [contract_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: contract_to_dict(item) for key, item in value.items()}
    return value
