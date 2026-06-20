from __future__ import annotations

from typing import Any


def configure_rule_dependencies(dependencies: dict[str, Any]) -> None:
    globals().update(dependencies)


LEADING_FILLER_WORDS = ("咳", "嗯", "呃", "啊", "哎", "唉", "诶", "额", "呐", "喂")


MIN_LEADING_FILLER_GAP_US = 700_000


MAX_LEADING_FILLER_DURATION_US = 900_000


MIN_LEADING_FILLER_REMAINING_CHARS = 4


def _repair_leading_filler_gap(
    *,
    final_timeline: list[FinalTimelineSegment],
    source_graph: CanonicalSourceGraph,
    pass_index: int,
) -> _RepairStep | None:
    words_by_id = {word.word_id: word for word in source_graph.words}
    for segment in _ordered_segments(final_timeline):
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
        remaining_text = normalize_text(_text_from_word_ids(remaining_word_ids, source_graph))
        if len(remaining_text) < MIN_LEADING_FILLER_REMAINING_CHARS:
            continue
        repaired = _trim_word_ids_from_timeline(final_timeline, source_graph, [segment.word_ids[0]])
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
