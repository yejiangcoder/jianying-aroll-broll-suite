from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from aroll_text_normalize import normalize_text
from aroll_v21.ir.models import CanonicalSourceGraph, FinalTimelineSegment
from aroll_v21.quality.final_visible_repair.context import FinalVisibleRepairContext
from aroll_v21.quality.final_visible_repair.pipeline import FinalVisibleRepairState
from aroll_v21.quality.final_visible_repair.report import _action
from aroll_v21.quality.final_visible_repair.result import _RepairStep
from aroll_v21.quality.final_visible_repair.timeline_utils import ordered_segments, text_from_word_ids


LEADING_FILLER_WORDS = ("咳", "嗯", "呃", "啊", "哎", "唉", "诶", "额", "呐", "喂")


MIN_LEADING_FILLER_GAP_US = 700_000


MAX_LEADING_FILLER_DURATION_US = 900_000


MIN_LEADING_FILLER_REMAINING_CHARS = 4


@dataclass(frozen=True)
class LeadingFillerGapRule:
    repair_leading_filler_gap: Callable[..., _RepairStep | None]
    name: str = "leading_filler_gap"

    def try_repair(
        self,
        *,
        context: FinalVisibleRepairContext,
        state: FinalVisibleRepairState,
        pass_index: int,
    ) -> _RepairStep | None:
        return self.repair_leading_filler_gap(
            final_timeline=state.final_timeline,
            source_graph=context.source_graph,
            pass_index=pass_index,
        )


def _repair_leading_filler_gap(
    *,
    final_timeline: list[FinalTimelineSegment],
    source_graph: CanonicalSourceGraph,
    pass_index: int,
) -> _RepairStep | None:
    words_by_id = {word.word_id: word for word in source_graph.words}
    for segment in ordered_segments(final_timeline):
        if len(segment.word_ids) < 2:
            continue
        first = words_by_id.get(segment.word_ids[0])
        second = words_by_id.get(segment.word_ids[1])
        if first is None or second is None:
            continue
        first_text = normalize_text(str(getattr(first, "text", "") or ""))
        if first_text not in LEADING_FILLER_WORDS:
            continue
        first_duration_us = int(getattr(first, "source_end_us", 0) or 0) - int(getattr(first, "source_start_us", 0) or 0)
        if first_duration_us <= 0 or first_duration_us > MAX_LEADING_FILLER_DURATION_US:
            continue
        source_gap_us = int(getattr(second, "source_start_us", 0) or 0) - int(getattr(first, "source_end_us", 0) or 0)
        if source_gap_us < MIN_LEADING_FILLER_GAP_US:
            continue
        remaining_word_ids = list(segment.word_ids[1:])
        remaining_text = normalize_text(text_from_word_ids(remaining_word_ids, source_graph))
        if len(remaining_text) < MIN_LEADING_FILLER_REMAINING_CHARS:
            continue
        repaired = _drop_leading_word_from_segment(final_timeline, segment, remaining_word_ids, source_graph)
        if repaired is None:
            continue
        return _RepairStep(
            final_timeline=repaired,
            captions=[],
            timeline_changed=True,
            action=_action(
                "leading_filler_gap",
                "trim_leading_filler_gap",
                pass_index,
                {
                    "caption_id": "",
                    "related_caption_id": "",
                    "reason": "isolated leading filler before a long source gap",
                    "overlap_text": first_text,
                },
                affected_segment_id=segment.segment_id,
                dropped_word_ids=[segment.word_ids[0]],
                filler_text=str(getattr(first, "text", "") or ""),
                source_gap_us=source_gap_us,
            ),
        )
    no_step: _RepairStep | None = None
    return no_step


def _drop_leading_word_from_segment(
    final_timeline: list[FinalTimelineSegment],
    target_segment: FinalTimelineSegment,
    remaining_word_ids: list[str],
    source_graph: CanonicalSourceGraph,
) -> list[FinalTimelineSegment] | None:
    words_by_id = {word.word_id: word for word in source_graph.words}
    remaining_words = [words_by_id[word_id] for word_id in remaining_word_ids if word_id in words_by_id]
    if len(remaining_words) != len(remaining_word_ids):
        no_timeline: list[FinalTimelineSegment] | None = None
        return no_timeline
    source_start_us = min(int(word.source_start_us) for word in remaining_words)
    source_end_us = max(int(word.source_end_us) for word in remaining_words)
    duration_us = max(0, source_end_us - source_start_us)
    if duration_us <= 0:
        no_timeline: list[FinalTimelineSegment] | None = None
        return no_timeline
    adjusted = replace(
        target_segment,
        source_start_us=source_start_us,
        source_end_us=source_end_us,
        target_end_us=int(target_segment.target_start_us) + duration_us,
        word_ids=list(remaining_word_ids),
        text="".join(word.text for word in remaining_words),
        spoken_source_start_us=source_start_us,
        spoken_source_end_us=source_end_us,
        clip_source_start_us=source_start_us
        if target_segment.clip_source_start_us is not None
        else target_segment.clip_source_start_us,
        clip_source_end_us=source_end_us
        if target_segment.clip_source_end_us is not None
        else target_segment.clip_source_end_us,
        debug_hints={**dict(target_segment.debug_hints or {}), "final_visible_repair": "trim_repeated_caption_words"},
    )
    return [
        adjusted if segment.segment_id == target_segment.segment_id else segment
        for segment in final_timeline
    ]
