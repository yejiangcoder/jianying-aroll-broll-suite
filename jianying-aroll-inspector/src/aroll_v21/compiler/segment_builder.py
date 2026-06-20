from __future__ import annotations

from typing import Any, Iterable

from aroll_v21.ir.models import Blocker


def groups(words: Iterable[Any], word_to_unit_id: dict[str, str]):
    current = []
    last_end = None
    last_unit = None
    for word in words:
        unit_id = word_to_unit_id.get(word.word_id)
        if (
            current
            and (
                unit_id != last_unit
                or (last_end is not None and word.source_start_us > last_end + 80_000)
            )
        ):
            yield current
            current = []
        current.append(word)
        last_end = word.source_end_us
        last_unit = unit_id
    if current:
        yield current


def source_order_blockers(words: Iterable[Any]) -> list[Blocker]:
    blockers: list[Blocker] = []
    ordered = [word for word in words if word.subtitle_index is not None]
    ordered.sort(key=lambda word: (int(word.subtitle_index or 0), word.source_start_us, word.word_id))
    previous: tuple[int, str] | None = None
    for word in ordered:
        if previous is not None and word.source_start_us < previous[0]:
            blockers.append(
                Blocker(
                    "FINAL_TIMELINE_SEGMENT_UNSAFE_WORD_ORDER",
                    "word source times are not monotonic in subtitle order",
                    "compiler",
                    context={
                        "word_id": word.word_id,
                        "prev_word_id": previous[1],
                        "subtitle_index": word.subtitle_index,
                        "source_start_us": word.source_start_us,
                        "previous_source_start_us": previous[0],
                    },
                )
            )
            break
        previous = (word.source_start_us, word.word_id)
    return blockers


def group_blockers(group: list[Any]) -> list[Blocker]:
    blockers: list[Blocker] = []
    subtitle_indices = [int(word.subtitle_index) for word in group if word.subtitle_index is not None]
    unique_indices = sorted(set(subtitle_indices))
    text = "".join(word.text for word in group)
    if len(group) > 20:
        blockers.append(
            Blocker(
                "FINAL_TIMELINE_SEGMENT_OVERSIZED_WORD_COUNT",
                "compiled segment contains too many words to be a safe edit unit",
                "compiler",
                context={"word_count": len(group), "word_ids": [word.word_id for word in group[:30]]},
            )
        )
    if len(text) > 60:
        blockers.append(
            Blocker(
                "FINAL_TIMELINE_SEGMENT_OVERSIZED_TEXT",
                "compiled segment text is too long to be a safe edit unit",
                "compiler",
                context={"text_length": len(text), "text": text[:80]},
            )
        )
    if unique_indices:
        span = unique_indices[-1] - unique_indices[0]
        contiguous = unique_indices == list(range(unique_indices[0], unique_indices[-1] + 1))
        if span > 3 or (not contiguous and len(unique_indices) > 2):
            blockers.append(
                Blocker(
                    "FINAL_TIMELINE_SEGMENT_MIXED_SUBTITLE_INDICES",
                    "compiled segment mixes too many unrelated subtitle indices",
                    "compiler",
                    context={"subtitle_indices": unique_indices[:30], "subtitle_index_span": span},
                )
            )
    last_end = None
    for word in group:
        if last_end is not None and word.source_start_us < last_end:
            blockers.append(
                Blocker(
                    "FINAL_TIMELINE_SEGMENT_UNSAFE_WORD_ORDER",
                    "compiled segment word source ranges overlap or go backwards",
                    "compiler",
                    context={"word_id": word.word_id, "source_start_us": word.source_start_us, "previous_source_end_us": last_end},
                )
            )
            break
        last_end = word.source_end_us
    return blockers
