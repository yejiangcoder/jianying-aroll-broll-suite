from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal


CutPolicy = Literal["whole_unit_only", "word_boundary", "unsafe"]
EditUnitKind = Literal[
    "sentence",
    "phrase",
    "restart",
    "repeat",
    "filler",
    "semantic_take",
    "bridge",
]
RepeatType = Literal[
    "exact_repeat",
    "cjk_short_overlap",
    "restart",
    "semantic_retry",
    "hidden_audio_repeat",
    "modifier_redundancy",
]


def dataclass_to_dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [dataclass_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: dataclass_to_dict(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class Blocker:
    code: str
    message: str
    layer: str
    severity: Literal["fatal", "warning", "write_blocker"] = "fatal"
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CanonicalWord:
    word_id: str
    text: str
    normalized_text: str
    source_start_us: int
    source_end_us: int
    source_material_id: str
    source_segment_id: str | None
    subtitle_uid: str | None
    subtitle_index: int | None
    char_start: int | None
    char_end: int | None
    confidence: float | None
    is_cuttable_left: bool
    is_cuttable_right: bool
    debug_hints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EditUnit:
    unit_id: str
    word_ids: list[str]
    text: str
    normalized_text: str
    source_start_us: int
    source_end_us: int
    subtitle_uids: list[str]
    source_material_ids: list[str]
    kind: EditUnitKind
    cut_policy: CutPolicy
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateEvidence:
    evidence_id: str
    evidence_type: RepeatType
    unit_ids: list[str]
    word_ids: list[str]
    text: str
    normalized_text: str
    reason: str
    confidence: float
    requires_semantic_decision: bool
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RepeatCluster:
    cluster_id: str
    variants: list[EditUnit]
    repeat_type: RepeatType
    evidence: list[CandidateEvidence]
    local_recommendation: str | None


@dataclass(frozen=True)
class TakeDecision:
    decision_id: str
    cluster_id: str
    keep_unit_id: str
    drop_unit_ids: list[str]
    reason: str
    confidence: float
    requires_human_review: bool
    source: Literal["local_policy", "deepseek_semantic_planner", "semantic_decisions_json", "deterministic_baseline", "merged"] = "local_policy"


@dataclass(frozen=True)
class WordSpan:
    unit_id: str
    word_ids: list[str]
    source_start_us: int
    source_end_us: int


@dataclass(frozen=True)
class UnitSplitPlan:
    split_id: str
    cluster_id: str
    unit_id: str
    drop_word_ids: list[str]
    keep_word_ids: list[str]
    reason: str
    source: Literal[
        "local_policy",
        "deepseek_semantic_planner",
        "semantic_decisions_json",
        "deterministic_baseline",
        "semantic_unconfigured_self_review",
    ] = "local_policy"
    requires_human_review: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionPlan:
    decisions: list[TakeDecision]
    split_decisions: list[UnitSplitPlan] = field(default_factory=list)
    blocked: bool = False
    blockers: list[Blocker] = field(default_factory=list)
    semantic_request_payloads: list[dict[str, Any]] = field(default_factory=list)
    decision_trace: list[dict[str, Any]] = field(default_factory=list)
    semantic_decision_rows: list[dict[str, Any]] = field(default_factory=list)
    semantic_adjudication_report: dict[str, Any] = field(default_factory=dict)
    final_target_repeat_accepted_cluster_ids: list[str] = field(default_factory=list)
    final_target_repeat_unresolved_cluster_ids: list[str] = field(default_factory=list)
    modifier_redundancy_accepted_cluster_ids: list[str] = field(default_factory=list)
    modifier_redundancy_unresolved_cluster_ids: list[str] = field(default_factory=list)
    semantic_unresolved_count: int = 0
    requires_human_review: bool = False
    write_allowed: bool = True
    dry_run_continued_for_discovery: bool = False


@dataclass(frozen=True)
class FinalTimelineSegment:
    segment_id: str
    source_material_id: str
    source_segment_id: str | None
    source_start_us: int
    source_end_us: int
    target_start_us: int
    target_end_us: int
    word_ids: list[str]
    text: str
    decision_ids: list[str]
    spoken_source_start_us: int | None = None
    spoken_source_end_us: int | None = None
    clip_source_start_us: int | None = None
    clip_source_end_us: int | None = None
    lead_handle_us: int = 0
    tail_handle_us: int = 0
    debug_hints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VideoTimelineSegment:
    segment_id: str
    source_start_us: int
    source_end_us: int
    target_start_us: int
    target_end_us: int
    primary_source_window_id: str
    word_ids: list[str]
    caption_ids: list[str]
    expected_speed: float | None = None


@dataclass(frozen=True)
class CaptionTimelineSegment:
    caption_id: str
    text: str
    word_ids: list[str]
    spoken_source_start_us: int
    spoken_source_end_us: int
    target_start_us: int
    target_end_us: int
    containing_video_segment_id: str


@dataclass(frozen=True)
class ResolvedSourceBinding:
    final_segment_id: str
    current_source_segment_id: str
    current_source_material_id: str
    current_video_track_id: str
    current_video_segment_template: dict[str, Any]
    current_material_template: dict[str, Any]
    source_start_us: int
    source_end_us: int
    match_strategy: str
    match_confidence: float


@dataclass(frozen=True)
class CaptionRenderUnit:
    caption_id: str
    timeline_segment_ids: list[str]
    word_ids: list[str]
    text: str
    target_start_us: int
    target_end_us: int
    source_subtitle_uids: list[str]
    style_template_id: str
    spoken_source_start_us: int | None = None
    spoken_source_end_us: int | None = None
    containing_video_segment_id: str | None = None


@dataclass(frozen=True)
class SourceGraphInvariantReport:
    single_source_graph_ok: bool
    all_words_have_source_time: bool
    all_edit_units_have_word_ids: bool
    unbound_word_count: int
    unbound_subtitle_count: int
    blocker_count: int
    blockers: list[Blocker] = field(default_factory=list)


@dataclass(frozen=True)
class CanonicalSourceGraph:
    words: list[CanonicalWord]
    edit_units: list[EditUnit]
    subtitle_rows: list[dict[str, Any]]
    source_materials: list[dict[str, Any]]
    source_segments: list[dict[str, Any]]
    text_materials: list[dict[str, Any]]
    text_segments: list[dict[str, Any]]
    invariant_report: SourceGraphInvariantReport


@dataclass(frozen=True)
class BlockerReport:
    blocked: bool
    blockers: list[Blocker]
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunReport:
    status: Literal["ok", "blocked"]
    source_graph: CanonicalSourceGraph | None
    repeat_clusters: list[RepeatCluster]
    decision_plan: DecisionPlan | None
    final_timeline: list[FinalTimelineSegment]
    captions: list[CaptionRenderUnit]
    material_write_plan: dict[str, Any]
    validator_report: dict[str, Any]
    postwrite_report: dict[str, Any]
    blocker_report: BlockerReport
    decision_trace: list[dict[str, Any]] = field(default_factory=list)
    resolved_template_map: dict[str, Any] = field(default_factory=dict)
    source_binding_report: dict[str, Any] = field(default_factory=dict)
