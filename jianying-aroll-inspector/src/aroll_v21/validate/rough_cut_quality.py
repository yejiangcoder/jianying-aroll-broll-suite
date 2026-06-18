from __future__ import annotations

from typing import Any

from aroll_text_normalize import normalize_text
from aroll_v21.ir.models import CaptionRenderUnit, FinalTimelineSegment


def build_rough_cut_quality_metrics(
    *,
    final_timeline: list[FinalTimelineSegment],
    captions: list[CaptionRenderUnit],
    material_write_plan: dict[str, Any],
    visible_caption_track_count: int = 1,
    old_subtitle_residue_track_count: int = 0,
    overlapping_caption_segments_count: int = 0,
) -> dict[str, Any]:
    durations = [int(segment.target_end_us) - int(segment.target_start_us) for segment in final_timeline]
    normalized_texts = [normalize_text(caption.text) for caption in captions]
    material_count = len(material_write_plan.get("materials") or [])
    segment_count = len(material_write_plan.get("segments") or [])
    target_gap_count = 0
    target_overlap_count = 0
    previous_end = None
    for segment in final_timeline:
        start = int(segment.target_start_us)
        end = int(segment.target_end_us)
        if previous_end is not None:
            if start > previous_end:
                target_gap_count += 1
            if start < previous_end:
                target_overlap_count += 1
        previous_end = end
    text_counts: dict[str, int] = {}
    adjacent_duplicate_text_count = 0
    for index, text in enumerate(normalized_texts):
        if not text:
            continue
        text_counts[text] = text_counts.get(text, 0) + 1
        if index and text == normalized_texts[index - 1]:
            adjacent_duplicate_text_count += 1
    non_adjacent_duplicate_text_count = sum(1 for _text, count in text_counts.items() if count > 1) - adjacent_duplicate_text_count
    containment_repeat_count = 0
    for index, text in enumerate(normalized_texts):
        if not text:
            continue
        for other_index in range(index + 2, len(normalized_texts)):
            other = normalized_texts[other_index]
            if other and text != other and (text in other or other in text):
                containment_repeat_count += 1
                break
    metrics = {
        "final_timeline_count": len(final_timeline),
        "caption_count": len(captions),
        "material_count": material_count,
        "segment_count": segment_count,
        "video_caption_decoupled": len(captions) != len(final_timeline),
        "caption_material_segment_count_match": len(captions) == material_count == segment_count,
        "caption_count_covers_video_segments": len(final_timeline) > 0 and len(captions) >= len(final_timeline),
        "caption_per_video_segment_ratio": round(len(captions) / len(final_timeline), 4) if final_timeline else 0.0,
        "segments_lt_300ms": sum(1 for value in durations if value < 300_000),
        "segments_lt_500ms": sum(1 for value in durations if value < 500_000),
        "segments_lt_700ms": sum(1 for value in durations if value < 700_000),
        "shortest_segment_ms": min(durations) / 1000 if durations else 0,
        "one_char_captions": sum(1 for text in normalized_texts if len(text) == 1),
        "captions_le_3_chars": sum(1 for text in normalized_texts if 0 < len(text) <= 3),
        "visible_caption_track_count": int(visible_caption_track_count),
        "old_subtitle_residue_track_count": int(old_subtitle_residue_track_count),
        "overlapping_caption_segments_count": int(overlapping_caption_segments_count),
        "segments_with_no_lead_handle": sum(1 for segment in final_timeline if int(segment.lead_handle_us or 0) <= 0),
        "segments_with_no_tail_handle": sum(1 for segment in final_timeline if int(segment.tail_handle_us or 0) <= 0),
        "adjacent_duplicate_text_count": adjacent_duplicate_text_count,
        "non_adjacent_duplicate_text_count": max(0, non_adjacent_duplicate_text_count),
        "containment_repeat_count": containment_repeat_count,
        "target_gap_count": target_gap_count,
        "target_overlap_count": target_overlap_count,
    }
    metrics["rough_cut_quality_gate_passed"] = bool(
        metrics["segments_lt_300ms"] == 0
        and metrics["one_char_captions"] == 0
        and metrics["adjacent_duplicate_text_count"] == 0
        and metrics["visible_caption_track_count"] == 1
        and metrics["old_subtitle_residue_track_count"] == 0
        and metrics["overlapping_caption_segments_count"] == 0
        and metrics["caption_material_segment_count_match"]
        and metrics["caption_count_covers_video_segments"]
        and metrics["target_gap_count"] == 0
        and metrics["target_overlap_count"] == 0
    )
    return metrics
