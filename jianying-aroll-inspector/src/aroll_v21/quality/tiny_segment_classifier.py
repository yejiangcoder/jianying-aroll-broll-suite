from __future__ import annotations

from dataclasses import dataclass

from aroll_text_normalize import normalize_text
from aroll_v21.ir.models import FinalTimelineSegment


MIN_VIDEO_SEGMENT_US = 500_000
PREFERRED_MIN_VIDEO_SEGMENT_US = 700_000
MIN_SEMANTIC_BRIDGE_US = 600_000
VISUAL_MIN_SEGMENT_DURATION_US = 1_200_000
WEAK_TINY_TEXT = {"啊", "呃", "嗯", "呐", "呢", "吧", "嘛", "就", "的", "是", "在", "这个", "那个", "然后"}


@dataclass(frozen=True)
class TinySegmentClassification:
    duration_us: int
    normalized_text: str
    hard_tiny_artifact: bool
    weak_filler: bool
    semantic_bridge: bool
    visual_short_segment: bool
    merge_candidate_reason: str


def classify_tiny_segment(segment: FinalTimelineSegment) -> TinySegmentClassification:
    duration = max(0, int(segment.target_end_us) - int(segment.target_start_us))
    text = normalize_text(segment.text)
    weak_filler = text in WEAK_TINY_TEXT or len(text) <= 1
    hard_tiny = duration < MIN_VIDEO_SEGMENT_US and weak_filler
    semantic_bridge = MIN_SEMANTIC_BRIDGE_US <= duration < VISUAL_MIN_SEGMENT_DURATION_US and 2 <= len(text) <= 10 and not weak_filler
    visual_short = 0 < duration < VISUAL_MIN_SEGMENT_DURATION_US
    reason = ""
    if hard_tiny:
        reason = "hard_tiny_artifact"
    elif weak_filler and duration < PREFERRED_MIN_VIDEO_SEGMENT_US:
        reason = "weak_filler"
    elif semantic_bridge:
        reason = "semantic_bridge_exception"
    elif visual_short:
        reason = "visual_short_segment"
    return TinySegmentClassification(
        duration_us=duration,
        normalized_text=text,
        hard_tiny_artifact=hard_tiny,
        weak_filler=weak_filler,
        semantic_bridge=semantic_bridge,
        visual_short_segment=visual_short,
        merge_candidate_reason=reason,
    )


def is_semantic_bridge(segment: FinalTimelineSegment) -> bool:
    return classify_tiny_segment(segment).semantic_bridge
