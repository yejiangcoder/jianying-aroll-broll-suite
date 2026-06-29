from __future__ import annotations

from typing import Any, Callable

from aroll_text_normalize import normalize_text
from aroll_v21.ir.models import CaptionRenderUnit, FinalTimelineSegment


def _repair_state_signature(
    final_timeline: list[FinalTimelineSegment],
    captions: list[CaptionRenderUnit],
    *,
    ordered_segments: Callable[[list[FinalTimelineSegment]], list[FinalTimelineSegment]],
    ordered_captions: Callable[[list[CaptionRenderUnit]], list[CaptionRenderUnit]],
    caption_segment_ids: Callable[[CaptionRenderUnit], list[str]],
) -> tuple[Any, ...]:
    timeline_state = tuple(
        (
            segment.segment_id,
            tuple(segment.word_ids),
            normalize_text(segment.text),
            int(segment.source_start_us),
            int(segment.source_end_us),
            int(segment.target_start_us),
            int(segment.target_end_us),
            segment.spoken_source_start_us,
            segment.spoken_source_end_us,
            segment.clip_source_start_us,
            segment.clip_source_end_us,
            int(segment.lead_handle_us or 0),
            int(segment.tail_handle_us or 0),
        )
        for segment in ordered_segments(final_timeline)
    )
    caption_state = tuple(
        (
            caption.caption_id,
            tuple(caption_segment_ids(caption)),
            tuple(caption.word_ids),
            normalize_text(caption.text),
            int(caption.target_start_us),
            int(caption.target_end_us),
        )
        for caption in ordered_captions(captions)
    )
    return timeline_state, caption_state


def _caption_only_state_signature(
    captions: list[CaptionRenderUnit],
    *,
    ordered_captions: Callable[[list[CaptionRenderUnit]], list[CaptionRenderUnit]],
    caption_segment_ids: Callable[[CaptionRenderUnit], list[str]],
) -> tuple[Any, ...]:
    return tuple(
        (
            tuple(caption_segment_ids(caption)),
            tuple(caption.word_ids),
            normalize_text(caption.text),
            int(caption.target_start_us),
            int(caption.target_end_us),
        )
        for caption in ordered_captions(captions)
    )
