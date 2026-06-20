from __future__ import annotations

from dataclasses import replace

from aroll_v21.ir.models import CanonicalSourceGraph, CaptionRenderUnit, FinalTimelineSegment


def unique_values(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def caption_segment_ids(caption: CaptionRenderUnit) -> list[str]:
    values = list(caption.timeline_segment_ids or [])
    if caption.containing_video_segment_id:
        values.append(str(caption.containing_video_segment_id))
    return unique_values(values)


def text_from_word_ids(word_ids: list[str], source_graph: CanonicalSourceGraph) -> str:
    words_by_id = {word.word_id: word for word in source_graph.words}
    return "".join(words_by_id[word_id].text for word_id in word_ids if word_id in words_by_id)


def segment_duration_us(segment: FinalTimelineSegment) -> int:
    return max(0, int(segment.target_end_us) - int(segment.target_start_us))


def ordered_captions(captions: list[CaptionRenderUnit]) -> list[CaptionRenderUnit]:
    return sorted(captions, key=lambda row: (int(row.target_start_us), int(row.target_end_us), str(row.caption_id)))


def ordered_segments(segments: list[FinalTimelineSegment]) -> list[FinalTimelineSegment]:
    return sorted(segments, key=lambda row: (int(row.target_start_us), int(row.target_end_us), str(row.segment_id)))


def caption_by_id(captions: list[CaptionRenderUnit], caption_id: str) -> CaptionRenderUnit | None:
    for caption in captions:
        if caption.caption_id == caption_id:
            return caption
    no_caption: CaptionRenderUnit | None = None
    return no_caption


def caption_index(captions: list[CaptionRenderUnit], caption_id: str) -> int | None:
    for index, caption in enumerate(captions):
        if caption.caption_id == caption_id:
            return index
    no_index: int | None = None
    return no_index


def repack_timeline(final_timeline: list[FinalTimelineSegment]) -> list[FinalTimelineSegment]:
    repacked: list[FinalTimelineSegment] = []
    cursor = 0
    for segment in final_timeline:
        duration = max(0, int(segment.target_end_us) - int(segment.target_start_us))
        repacked.append(replace(segment, target_start_us=cursor, target_end_us=cursor + duration))
        cursor += duration
    return repacked


def renumber_captions(captions: list[CaptionRenderUnit]) -> list[CaptionRenderUnit]:
    return [
        replace(caption, caption_id=f"v21_cap_{index:06d}")
        for index, caption in enumerate(ordered_captions(captions), start=1)
    ]
