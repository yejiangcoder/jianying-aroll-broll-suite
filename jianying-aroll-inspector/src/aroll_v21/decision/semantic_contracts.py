from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any, Protocol, Sequence


class _JsonEnum(str, Enum):
    def __str__(self) -> str:
        return str(self.value)


class SemanticIssueType(_JsonEnum):
    MODIFIER_REDUNDANCY = "modifier_redundancy"
    SELF_REPAIR_ABORTED_PHRASE = "self_repair_aborted_phrase"
    NEAR_DUPLICATE_TAKE = "near_duplicate_take"
    SEMANTIC_CONTAINMENT = "semantic_containment"
    VISIBLE_CAPTION_REPEAT = "visible_caption_repeat"
    PREFIX_SUFFIX_OVERLAP = "prefix_suffix_overlap"
    AMBIGUOUS_REPEAT = "ambiguous_repeat"


class SemanticIssueSeverity(_JsonEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    FATAL = "fatal"


class SemanticAdjudicationDecisionType(_JsonEnum):
    KEEP_ALL = "keep_all"
    DROP_LEFT = "drop_left"
    DROP_RIGHT = "drop_right"
    KEEP_LONGEST_DROP_OTHERS = "keep_longest_drop_others"
    DROP_RECOMMENDED = "drop_recommended"
    DROP_ABORTED = "drop_aborted"
    REPAIR_TEXT = "repair_text"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"
    NO_DECISION = "no_decision"


class SemanticAdjudicationMode(_JsonEnum):
    AUTO = "auto"
    DETERMINISTIC_BASELINE = "deterministic-baseline"
    SEMANTIC_REQUESTS_ONLY = "semantic-requests-only"
    DEEPSEEK = "deepseek"
    FAIL_CLOSED = "fail-closed"


@dataclass(frozen=True)
class SemanticAdjudicationRequest:
    issue_id: str
    issue_type: SemanticIssueType
    severity: SemanticIssueSeverity
    candidate_segment_ids: list[str] = field(default_factory=list)
    candidate_caption_ids: list[str] = field(default_factory=list)
    word_ids: list[str] = field(default_factory=list)
    source_start_us: int = 0
    source_end_us: int = 0
    target_start_us: int = 0
    target_end_us: int = 0
    text_before: str = ""
    text_after: str = ""
    local_context: dict[str, Any] = field(default_factory=dict)
    recommended_action: str = ""
    why_local_policy_cannot_decide: str = ""
    allowed_decisions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SemanticAdjudicationDecision:
    issue_id: str
    decision: SemanticAdjudicationDecisionType
    reason: str
    confidence: float = 0.0
    provider_name: str = ""
    keep_unit_id: str = ""
    drop_unit_ids: list[str] = field(default_factory=list)
    unit_id: str = ""
    drop_word_ids: list[str] = field(default_factory=list)
    keep_word_ids: list[str] = field(default_factory=list)
    repair_text: str = ""
    requires_human_review: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SemanticAdjudicationResult:
    request: SemanticAdjudicationRequest
    decision: SemanticAdjudicationDecision | None = None
    resolved: bool = False
    provider_configured: bool = False
    provider_called: bool = False
    deterministic_baseline_refused: bool = False
    blocker_code: str = ""
    message: str = ""


@dataclass(frozen=True)
class SemanticRoutingDecision:
    issue_id: str
    issue_type: SemanticIssueType
    severity: SemanticIssueSeverity
    local_confidence: float = 0.0
    deterministic_action_available: bool = False
    local_action: str = ""
    ambiguity_score: float = 0.0
    requires_provider: bool = False
    provider_reason: str = ""
    fallback_policy: str = ""


class SemanticAdjudicationProvider(Protocol):
    provider_name: str

    def decide(self, requests: Sequence[SemanticAdjudicationRequest]) -> list[SemanticAdjudicationDecision]:
        """Return structured semantic decisions for the supplied requests."""


def semantic_contract_to_dict(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: semantic_contract_to_dict(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [semantic_contract_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: semantic_contract_to_dict(item) for key, item in value.items()}
    return value
