from __future__ import annotations

from typing import Any


def configure_rule_dependencies(dependencies: dict[str, Any]) -> None:
    globals().update(dependencies)


def _drop_or_trim_caption_words(
    final_timeline: list[FinalTimelineSegment],
    captions: list[CaptionRenderUnit],
    source_graph: CanonicalSourceGraph,
    caption: CaptionRenderUnit,
) -> tuple[list[FinalTimelineSegment], list[str], list[str]] | None:
    segment_ids = _caption_segment_ids(caption)
    if segment_ids and _caption_segments_exclusive(caption, captions, segment_ids):
        segment_id_set = set(segment_ids)
        kept = [segment for segment in final_timeline if segment.segment_id not in segment_id_set]
        if len(kept) < len(final_timeline):
            return kept, segment_ids, []
    repaired = _trim_word_ids_from_timeline(final_timeline, source_graph, list(caption.word_ids))
    if repaired is None:
        no_drop: tuple[list[FinalTimelineSegment], list[str], list[str]] | None = None
        return no_drop
    trimmed_ids = [
        before.segment_id
        for before, after in zip(final_timeline, repaired)
        if before.segment_id == after.segment_id and list(before.word_ids) != list(after.word_ids)
    ]
    return repaired, [], trimmed_ids


def _trim_word_ids_from_timeline(
    final_timeline: list[FinalTimelineSegment],
    source_graph: CanonicalSourceGraph,
    drop_word_ids: list[str],
) -> list[FinalTimelineSegment] | None:
    if not drop_word_ids:
        no_trim: list[FinalTimelineSegment] | None = None
        return no_trim
    drop_set = set(drop_word_ids)
    repaired: list[FinalTimelineSegment] = []
    changed = False
    for segment in final_timeline:
        word_ids = list(segment.word_ids)
        if not drop_set.intersection(word_ids):
            repaired.append(segment)
            continue
        if _is_prefix(word_ids, drop_word_ids):
            remaining = word_ids[len(drop_word_ids) :]
        elif _is_suffix(word_ids, drop_word_ids):
            remaining = word_ids[: len(word_ids) - len(drop_word_ids)]
        elif set(word_ids) == drop_set:
            remaining = []
        else:
            no_trim: list[FinalTimelineSegment] | None = None
            return no_trim
        changed = True
        if not remaining:
            continue
        adjusted = _segment_with_word_ids(segment, remaining, source_graph)
        if adjusted is None:
            no_trim: list[FinalTimelineSegment] | None = None
            return no_trim
        repaired.append(adjusted)
    if not changed:
        no_trim: list[FinalTimelineSegment] | None = None
        return no_trim
    return repaired


def _drop_contiguous_word_ids_from_timeline(
    final_timeline: list[FinalTimelineSegment],
    source_graph: CanonicalSourceGraph,
    drop_word_ids: list[str],
    repair_reason: str,
) -> list[FinalTimelineSegment] | None:
    if not drop_word_ids:
        no_trim: list[FinalTimelineSegment] | None = None
        return no_trim
    flattened_word_ids = [word_id for segment in final_timeline for word_id in segment.word_ids]
    if not _contains_contiguous_subsequence(flattened_word_ids, drop_word_ids):
        no_trim: list[FinalTimelineSegment] | None = None
        return no_trim
    drop_set = set(drop_word_ids)
    repaired: list[FinalTimelineSegment] = []
    changed = False
    existing_segment_ids = {segment.segment_id for segment in final_timeline}
    for segment in final_timeline:
        word_ids = list(segment.word_ids)
        positions = [index for index, word_id in enumerate(word_ids) if word_id in drop_set]
        if not positions:
            repaired.append(segment)
            continue
        start = positions[0]
        end = positions[-1] + 1
        if positions != list(range(start, end)):
            no_trim: list[FinalTimelineSegment] | None = None
            return no_trim
        prefix_word_ids = word_ids[:start]
        suffix_word_ids = word_ids[end:]
        if not prefix_word_ids and not suffix_word_ids:
            changed = True
            continue
        cursor = int(segment.target_start_us)
        if prefix_word_ids:
            prefix_segment = _segment_with_word_ids_preserving_effective_speed(
                replace(segment, target_start_us=cursor),
                prefix_word_ids,
                source_graph,
                repair_reason,
            )
            if prefix_segment is None:
                no_trim: list[FinalTimelineSegment] | None = None
                return no_trim
            repaired.append(prefix_segment)
            cursor = int(prefix_segment.target_end_us)
        if suffix_word_ids:
            suffix_id = segment.segment_id if not prefix_word_ids else _unique_split_segment_id(segment.segment_id, existing_segment_ids)
            existing_segment_ids.add(suffix_id)
            suffix_segment = _segment_with_word_ids_preserving_effective_speed(
                replace(segment, segment_id=suffix_id, target_start_us=cursor),
                suffix_word_ids,
                source_graph,
                repair_reason,
            )
            if suffix_segment is None:
                no_trim: list[FinalTimelineSegment] | None = None
                return no_trim
            repaired.append(suffix_segment)
        changed = True
    if not changed:
        no_trim: list[FinalTimelineSegment] | None = None
        return no_trim
    return _merge_short_repaired_segments(repaired, source_graph, repair_reason)


def _contains_contiguous_subsequence(values: list[str], subsequence: list[str]) -> bool:
    if not subsequence or len(subsequence) > len(values):
        return False
    width = len(subsequence)
    return any(values[index : index + width] == subsequence for index in range(0, len(values) - width + 1))


def _leading_word_ids_for_text(
    word_ids: list[str],
    source_graph: CanonicalSourceGraph,
    text: str,
) -> list[str]:
    target = normalize_text(text)
    if not target:
        empty: list[str] = []
        return empty
    words_by_id = {word.word_id: word for word in source_graph.words}
    selected: list[str] = []
    joined = ""
    for word_id in word_ids:
        word = words_by_id.get(word_id)
        if word is None:
            empty: list[str] = []
            return empty
        selected.append(word_id)
        joined += normalize_text(word.text)
        if joined == target:
            return selected
        if not target.startswith(joined):
            empty: list[str] = []
            return empty
    empty: list[str] = []
    return empty


def _trailing_word_ids_for_text(
    word_ids: list[str],
    source_graph: CanonicalSourceGraph,
    text: str,
) -> list[str]:
    target = normalize_text(text)
    if not target:
        empty: list[str] = []
        return empty
    words_by_id = {word.word_id: word for word in source_graph.words}
    selected: list[str] = []
    joined = ""
    for word_id in reversed(word_ids):
        word = words_by_id.get(word_id)
        if word is None:
            empty: list[str] = []
            return empty
        selected.append(word_id)
        joined = normalize_text(word.text) + joined
        if joined == target:
            return list(reversed(selected))
        if not target.endswith(joined):
            empty: list[str] = []
            return empty
    empty: list[str] = []
    return empty


def _contiguous_word_ids_for_text(
    word_ids: list[str],
    source_graph: CanonicalSourceGraph,
    text: str,
) -> list[str]:
    target = normalize_text(text)
    if not target:
        empty: list[str] = []
        return empty
    words_by_id = {word.word_id: word for word in source_graph.words}
    for start in range(0, len(word_ids)):
        selected: list[str] = []
        joined = ""
        for word_id in word_ids[start:]:
            word = words_by_id.get(word_id)
            if word is None:
                break
            selected.append(word_id)
            joined += normalize_text(word.text)
            if joined == target:
                return selected
            if not target.startswith(joined):
                break
    empty: list[str] = []
    return empty
