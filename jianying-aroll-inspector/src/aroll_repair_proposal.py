from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


RepairType = Literal[
    "remove_duplicate_word_island",
    "drop_contained_final_repeat",
    "overlap_merge_final_repeat",
    "snap_boundary_to_word",
    "conservative_keep",
    "block",
]

RepairConfidence = Literal["high", "medium", "low"]


@dataclass
class RepairProposal:
    proposal_id: str
    repair_type: RepairType
    source_gate: str
    confidence: RepairConfidence
    reason: str

    left_text: str = ""
    right_text: str = ""
    merged_text: str = ""
    duplicate_text: str = ""

    keep_word_ids: list[str] = field(default_factory=list)
    remove_word_ids: list[str] = field(default_factory=list)

    remove_source_start_us: int | None = None
    remove_source_end_us: int | None = None

    target_start_us: int | None = None
    target_end_us: int | None = None

    preserve_prefix: bool = True
    preserve_suffix: bool = True
    requires_boundary_resolver: bool = True
    requires_regate: bool = True

    source_issue_id: str = ""
    candidate_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def proposal_to_dict(proposal: RepairProposal | dict[str, Any]) -> dict[str, Any]:
    if isinstance(proposal, RepairProposal):
        return proposal.to_dict()
    return dict(proposal)

