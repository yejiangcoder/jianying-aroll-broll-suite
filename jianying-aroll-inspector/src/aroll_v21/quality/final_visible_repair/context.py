from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from aroll_v21.ir.models import CanonicalSourceGraph, CaptionRenderUnit, FinalTimelineSegment


RepairStateSignature = tuple[Any, ...]


@dataclass(frozen=True)
class FinalVisibleRepairContext:
    source_graph: CanonicalSourceGraph
    render_captions: Callable[[list[FinalTimelineSegment]], list[CaptionRenderUnit]]
    repack_timeline: Callable[[list[FinalTimelineSegment]], list[FinalTimelineSegment]]
    renumber_captions: Callable[[list[CaptionRenderUnit]], list[CaptionRenderUnit]]
    render_captions_preserving_caption_only_materializations: Callable[
        [list[FinalTimelineSegment], list[CaptionRenderUnit], Callable[[list[FinalTimelineSegment]], list[CaptionRenderUnit]]],
        list[CaptionRenderUnit],
    ]
    repair_state_signature: Callable[[list[FinalTimelineSegment], list[CaptionRenderUnit]], RepairStateSignature]
