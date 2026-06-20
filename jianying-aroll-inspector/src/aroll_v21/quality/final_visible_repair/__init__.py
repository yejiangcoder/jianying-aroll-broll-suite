from __future__ import annotations

from aroll_v21.quality.final_visible_repair.proposal import (
    TimelineRepairProposal,
    TimelineRepairProposalValidation,
    validate_timeline_repair_proposal,
)
from aroll_v21.quality.final_visible_repair.result import FinalVisibleCaptionRepairResult
from aroll_v21.quality.final_visible_repair.timeline_materializer import (
    TimelineRepairMaterializationResult,
    apply_timeline_repair_proposal,
)

__all__ = [
    "FinalVisibleCaptionRepairResult",
    "TimelineRepairMaterializationResult",
    "TimelineRepairProposal",
    "TimelineRepairProposalValidation",
    "apply_timeline_repair_proposal",
    "validate_timeline_repair_proposal",
]
