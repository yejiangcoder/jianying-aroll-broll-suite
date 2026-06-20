from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aroll_v21.ir.models import CaptionRenderUnit, FinalTimelineSegment


@dataclass(frozen=True)
class FinalVisibleCaptionRepairResult:
    final_timeline: list[FinalTimelineSegment]
    captions: list[CaptionRenderUnit]
    report: dict[str, Any]


@dataclass(frozen=True)
class _RepairStep:
    final_timeline: list[FinalTimelineSegment]
    captions: list[CaptionRenderUnit]
    action: dict[str, Any]
    timeline_changed: bool = False


@dataclass(frozen=True)
class _SourceBoundaryPrefixCandidate:
    word: Any
    transfer_from_segment_id: str = ""


@dataclass(frozen=True)
class _SourceBoundaryCompoundCandidate:
    left_segment: FinalTimelineSegment
    right_segment: FinalTimelineSegment
    left_word: Any
    right_word: Any
