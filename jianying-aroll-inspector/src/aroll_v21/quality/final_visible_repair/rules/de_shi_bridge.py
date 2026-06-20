from __future__ import annotations

from typing import Any


def configure_rule_dependencies(dependencies: dict[str, Any]) -> None:
    globals().update(dependencies)


def _repair_de_shi_duplicate_bridge(
    final_timeline: list[FinalTimelineSegment],
    previous: CaptionRenderUnit,
    current: CaptionRenderUnit,
    source_graph: CanonicalSourceGraph,
    candidate: dict[str, Any],
    pass_index: int,
) -> _RepairStep | None:
    if normalize_text(str(candidate.get("reason") or "")) != "dangling_de_shi_prefix":
        no_step: _RepairStep | None = None
        return no_step
    previous_ids = _caption_segment_ids(previous)
    current_ids = _caption_segment_ids(current)
    if len(previous_ids) != 1 or len(current_ids) != 1:
        no_step: _RepairStep | None = None
        return no_step
    index_by_id = {segment.segment_id: index for index, segment in enumerate(final_timeline)}
    previous_index = index_by_id.get(previous_ids[0])
    current_index = index_by_id.get(current_ids[0])
    if previous_index is None or current_index is None or current_index != previous_index + 1:
        no_step: _RepairStep | None = None
        return no_step
    left = final_timeline[previous_index]
    right = final_timeline[current_index]
    if not left.word_ids or not right.word_ids:
        no_step: _RepairStep | None = None
        return no_step
    words_by_id = {word.word_id: word for word in source_graph.words}
    ordered_words = list(source_graph.words)
    index_by_word_id = {word.word_id: index for index, word in enumerate(ordered_words)}
    left_last_index = index_by_word_id.get(left.word_ids[-1])
    right_first_index = index_by_word_id.get(right.word_ids[0])
    if left_last_index is None or right_first_index is None or right_first_index <= left_last_index + 1:
        no_step: _RepairStep | None = None
        return no_step
    bridge_words = ordered_words[left_last_index + 1 : right_first_index]
    selected_word_ids = {word_id for segment in final_timeline for word_id in segment.word_ids}
    bridge_word_ids = [str(getattr(word, "word_id", "") or "") for word in bridge_words]
    if not bridge_word_ids or any(word_id in selected_word_ids for word_id in bridge_word_ids):
        no_step: _RepairStep | None = None
        return no_step
    bridge_text = "".join(str(getattr(word, "text", "") or "") for word in bridge_words)
    if not normalize_text(bridge_text):
        no_step: _RepairStep | None = None
        return no_step
    first_right_word = words_by_id.get(right.word_ids[0])
    if normalize_text(str(getattr(first_right_word, "text", "") or "")) != "的":
        no_step: _RepairStep | None = None
        return no_step
    duplicate_bridge_ids = _leading_word_ids_for_text(list(right.word_ids[1:]), source_graph, bridge_text)
    if not duplicate_bridge_ids:
        no_step: _RepairStep | None = None
        return no_step
    drop_count = 1 + len(duplicate_bridge_ids)
    remaining_right_word_ids = list(right.word_ids[drop_count:])
    if not remaining_right_word_ids:
        no_step: _RepairStep | None = None
        return no_step
    complete_right_word_ids = [*duplicate_bridge_ids, *remaining_right_word_ids]
    completed_right = _segment_with_word_ids_preserving_effective_speed(
        right,
        complete_right_word_ids,
        source_graph,
        "de_shi_duplicate_keep_later_complete_take",
    )
    if completed_right is None:
        no_step: _RepairStep | None = None
        return no_step
    repaired = list(final_timeline)
    repaired[current_index] = completed_right
    return _RepairStep(
        final_timeline=repaired,
        captions=[],
        timeline_changed=True,
        action=_action(
            "dangling_prefix_suffix",
            "keep_later_complete_take_for_de_shi_duplicate",
            pass_index,
            candidate,
            affected_caption_ids=[previous.caption_id, current.caption_id],
            preserved_segment_id=left.segment_id,
            completed_segment_id=right.segment_id,
            bridge_word_ids=bridge_word_ids,
            bridge_text=bridge_text,
            dropped_word_ids=[right.word_ids[0]],
            completed_right_word_ids=complete_right_word_ids,
            duplicate_bridge_word_ids=duplicate_bridge_ids,
        ),
    )


def _drop_repeated_caption_span(
    final_timeline: list[FinalTimelineSegment],
    captions: list[CaptionRenderUnit],
    source_graph: CanonicalSourceGraph,
    candidate: dict[str, Any],
    issue_type: str,
    pass_index: int,
) -> _RepairStep | None:
    caption = _caption_by_id(captions, str(candidate.get("caption_id") or ""))
    if caption is None:
        no_step: _RepairStep | None = None
        return no_step
    dropped = _drop_or_trim_caption_words(final_timeline, captions, source_graph, caption)
    if dropped is None:
        no_step: _RepairStep | None = None
        return no_step
    repaired_timeline, dropped_segment_ids, trimmed_segment_ids = dropped
    decision = "drop_shorter_repeated_segment" if dropped_segment_ids else "trim_shorter_repeated_words"
    return _RepairStep(
        final_timeline=repaired_timeline,
        captions=captions,
        timeline_changed=True,
        action=_action(
            issue_type,
            decision,
            pass_index,
            candidate,
            affected_caption_ids=[caption.caption_id],
            dropped_segment_ids=dropped_segment_ids,
            trimmed_segment_ids=trimmed_segment_ids,
        ),
    )
