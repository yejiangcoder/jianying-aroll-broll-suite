from __future__ import annotations

from typing import Any

from aroll_v21.ir.models import CanonicalSourceGraph, FinalTimelineSegment

def _child_segment_records(
    segment: FinalTimelineSegment,
    word_lookup: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    raw_records = list(segment.debug_hints.get("visual_pacing_child_segments") or [])
    if not raw_records:
        return [
            {
                "segment_id": segment.segment_id,
                "source_start_us": int(segment.source_start_us),
                "source_end_us": int(segment.source_end_us),
                "target_start_us": int(segment.target_start_us),
                "target_end_us": int(segment.target_end_us),
                "word_ids": list(segment.word_ids),
            }
        ]
    if word_lookup is None:
        return [dict(row) for row in raw_records if isinstance(row, dict)]
    kept_word_ids = set(segment.word_ids)
    records: list[dict[str, Any]] = []
    for row in raw_records:
        if not isinstance(row, dict):
            continue
        word_ids = [str(word_id) for word_id in list(row.get("word_ids") or []) if str(word_id) in kept_word_ids]
        if not word_ids:
            continue
        words = [word_lookup[word_id] for word_id in word_ids if word_id in word_lookup]
        if not words:
            continue
        records.append(
            {
                "segment_id": str(row.get("segment_id") or ""),
                "source_start_us": int(words[0].source_start_us),
                "source_end_us": int(words[-1].source_end_us),
                "target_start_us": int(row.get("target_start_us") or segment.target_start_us),
                "target_end_us": int(row.get("target_end_us") or segment.target_end_us),
                "word_ids": word_ids,
            }
        )
    if records:
        return records
    base_records = [
        {
            "segment_id": segment.segment_id,
            "source_start_us": int(segment.source_start_us),
            "source_end_us": int(segment.source_end_us),
            "target_start_us": int(segment.target_start_us),
            "target_end_us": int(segment.target_end_us),
            "word_ids": list(segment.word_ids),
        }
    ]
    return base_records


def _words_overlapping_range(
    source_graph: CanonicalSourceGraph,
    start_us: int,
    end_us: int,
    child_word_ids: set[str],
) -> list[Any]:
    if end_us <= start_us:
        no_words: list[Any] = []
        return no_words
    return [
        word
        for word in source_graph.words
        if word.word_id not in child_word_ids
        and int(word.source_end_us) > int(start_us)
        and int(word.source_start_us) < int(end_us)
    ]


def _dropped_segment_ids_for_words(words: list[Any]) -> list[str]:
    ids: set[str] = set()
    for word in words:
        subtitle_index = getattr(word, "subtitle_index", None)
        if subtitle_index is not None:
            ids.add(f"subtitle_{int(subtitle_index):06d}")
            continue
        subtitle_uid = str(getattr(word, "subtitle_uid", "") or "")
        if subtitle_uid:
            ids.add(f"subtitle_{subtitle_uid}")
    return sorted(ids)


def _dropped_cluster_ids_for_words(words: list[Any]) -> list[str]:
    cluster_ids: set[str] = set()
    for word in words:
        hints = getattr(word, "debug_hints", {}) or {}
        if not isinstance(hints, dict):
            continue
        for key in ("repeat_cluster_id", "cluster_id", "final_repeat_cluster_id"):
            value = str(hints.get(key) or "")
            if value:
                cluster_ids.add(value)
    return sorted(cluster_ids)
