from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any


DEFAULT_LEAD_PAD_US = 40_000
DEFAULT_TAIL_PAD_US = 40_000
MIN_SENTENCE_GAP_US = 180_000
MIN_KEEP_GAP_US = 60_000
MAX_KEEP_GAP_US = 120_000
REPEAT_KEEP_GAP_US = 80_000


def read_json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def words_for_group(group: dict[str, Any], words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indices = {int(item) for item in group.get("source_subtitle_indices") or []}
    return [row for row in words if int(row.get("subtitle_index") or -1) in indices]


def group_speech_bounds(
    group: dict[str, Any],
    words: list[dict[str, Any]],
    hidden_repeat: dict[str, Any] | None = None,
) -> dict[str, Any]:
    group_words = words_for_group(group, words)
    adjustment = None
    if hidden_repeat and hidden_repeat.get("recommended_action") == "remove_first_audio_island":
        target_fragment_id = hidden_repeat.get("target_fragment_id")
        if target_fragment_id == group.get("fragment_id"):
            keep_from_word_id = str(hidden_repeat.get("keep_from_word_id") or "")
            keep_word = next((row for row in group_words if str(row.get("word_id") or "") == keep_from_word_id), None)
            if keep_word:
                keep_start = int(keep_word["start_us"])
                group_words = [row for row in group_words if int(row.get("end_us") or 0) > keep_start]
                adjustment = {
                    "type": "hidden_repeat_remove_first_audio_island",
                    "keep_from_word_id": keep_from_word_id,
                    "keep_from_us": keep_start,
                    "removed_until_us": keep_start,
                }
    if group_words:
        start_us = min(int(row["start_us"]) for row in group_words)
        end_us = max(int(row["end_us"]) for row in group_words)
    else:
        start_us = int(group.get("source_start_us") or 0)
        end_us = int(group.get("source_end_us") or start_us)
    return {
        "fragment_id": group.get("fragment_id"),
        "text": group.get("fragment_text") or group.get("text") or "",
        "source_subtitle_indices": group.get("source_subtitle_indices") or [],
        "source_subtitle_uids": group.get("source_subtitle_uids") or [],
        "speech_start_us": start_us,
        "speech_end_us": max(start_us, end_us),
        "word_count": len(group_words),
        "adjustment": adjustment,
        "group": group,
    }


def build_group_bounds(
    grouped_subtitles: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
    hidden_repeat: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    bounds = [
        group_speech_bounds(group, word_timeline, hidden_repeat)
        for group in grouped_subtitles
    ]
    bounds.sort(key=lambda row: int(row["speech_start_us"]))
    return bounds


def high_energy_ratio_from_silences(silences: list[dict[str, Any]], start_us: int, end_us: int) -> float | None:
    if end_us <= start_us:
        return None
    silent = 0
    for row in silences:
        overlap_start = max(start_us, int(row.get("start_us") or 0))
        overlap_end = min(end_us, int(row.get("end_us") or 0))
        if overlap_end > overlap_start:
            silent += overlap_end - overlap_start
    ratio = 1.0 - (silent / max(1, end_us - start_us))
    return max(0.0, min(1.0, ratio))


def build_sentence_gap_report(
    group_bounds: list[dict[str, Any]],
    silences: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str]:
    rows: list[dict[str, Any]] = []
    silences = silences or []
    for index, (prev, curr) in enumerate(zip(group_bounds, group_bounds[1:]), start=1):
        gap_start = int(prev["speech_end_us"])
        gap_end = int(curr["speech_start_us"])
        gap_duration = max(0, gap_end - gap_start)
        if gap_duration < MIN_SENTENCE_GAP_US:
            continue
        repeat_or_drop = gap_duration >= 700_000 or bool(curr.get("adjustment"))
        keep_gap = REPEAT_KEEP_GAP_US if repeat_or_drop else _clamp(gap_duration // 3, MIN_KEEP_GAP_US, MAX_KEEP_GAP_US)
        cut_duration = max(0, gap_duration - keep_gap)
        ratio = high_energy_ratio_from_silences(silences, gap_start, gap_end)
        vad_confirmed = ratio is not None and ratio < 0.25
        decision = "cut" if cut_duration > 0 else "keep"
        rows.append(
            {
                "gap_id": f"sg_{index:03d}",
                "prev_fragment_id": prev.get("fragment_id"),
                "next_fragment_id": curr.get("fragment_id"),
                "prev_text": prev.get("text") or "",
                "next_text": curr.get("text") or "",
                "source_gap_us": gap_duration,
                "original_gap_ms": round(gap_duration / 1000, 3),
                "target_keep_gap_ms": round(keep_gap / 1000, 3),
                "cut_duration_ms": round(cut_duration / 1000, 3),
                "removed_ratio": round(cut_duration / max(1, gap_duration), 4),
                "vad_confirmed": vad_confirmed,
                "high_energy_speech_ratio": None if ratio is None else round(ratio, 4),
                "decision": decision,
                "reason": "repeat/drop/hidden-repeat boundary" if repeat_or_drop else "sentence gap compression",
            }
        )
    cut_rows = [row for row in rows if row["decision"] == "cut"]
    before_values = [float(row["original_gap_ms"]) for row in rows]
    after_values = [float(row["target_keep_gap_ms"]) for row in cut_rows]
    summary = {
        "sentence_gap_candidate_count": len(rows),
        "sentence_gap_cut_count": len(cut_rows),
        "total_sentence_gap_removed_s": round(sum(float(row["cut_duration_ms"]) for row in cut_rows) / 1000, 3),
        "average_gap_before_ms": round(statistics.mean(before_values), 3) if before_values else 0,
        "average_gap_after_ms": round(statistics.mean(after_values), 3) if after_values else 0,
        "gaps": rows,
        "top_10_compressed_gaps": sorted(cut_rows, key=lambda row: float(row["cut_duration_ms"]), reverse=True)[:10],
    }
    lines = [
        "# Sentence Gap Compression Review",
        "",
        f"- sentence_gap_candidate_count: {summary['sentence_gap_candidate_count']}",
        f"- sentence_gap_cut_count: {summary['sentence_gap_cut_count']}",
        f"- total_sentence_gap_removed_s: {summary['total_sentence_gap_removed_s']}",
        f"- average_gap_before_ms: {summary['average_gap_before_ms']}",
        f"- average_gap_after_ms: {summary['average_gap_after_ms']}",
        "",
    ]
    for row in summary["top_10_compressed_gaps"]:
        lines.append(
            f"- {row['gap_id']} cut={row['cut_duration_ms']}ms keep={row['target_keep_gap_ms']}ms | "
            f"{row['prev_text']} -> {row['next_text']}"
        )
    return summary, "\n".join(lines) + "\n"


def build_group_level_edl(group_bounds: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    clips: list[dict[str, Any]] = []
    subtitles: list[dict[str, Any]] = []
    target_start = 0
    for index, group in enumerate(group_bounds, start=1):
        source_start = max(0, int(group["speech_start_us"]) - DEFAULT_LEAD_PAD_US)
        source_end = int(group["speech_end_us"]) + DEFAULT_TAIL_PAD_US
        duration = source_end - source_start
        if duration <= 0:
            raise RuntimeError(f"NON_POSITIVE_GROUP_CLIP:{group.get('fragment_id')}")
        clip_id = f"c3_{index:03d}"
        clips.append(
            {
                "clip_id": clip_id,
                "fragment_id": group.get("fragment_id"),
                "source_start_us": source_start,
                "source_end_us": source_end,
                "cut_start_us": source_start,
                "cut_end_us": source_end,
                "target_start_us": target_start,
                "target_duration_us": duration,
                "source_reason": "phase4c3_group_level_sentence_gap_compression",
                "subtitle_texts": [group.get("text") or ""],
            }
        )
        subtitles.append(
            {
                "fragment_id": group.get("fragment_id"),
                "source_subtitle_uids": group.get("source_subtitle_uids") or [],
                "source_subtitle_indices": group.get("source_subtitle_indices") or [],
                "source_start_us": int(group["speech_start_us"]),
                "source_end_us": int(group["speech_end_us"]),
                "target_start_us": target_start + (int(group["speech_start_us"]) - source_start),
                "target_duration_us": int(group["speech_end_us"]) - int(group["speech_start_us"]),
                "fragment_text": group.get("text") or "",
                "text": group.get("text") or "",
                "reason": "phase4c3_grouped_subtitle",
                "adjustment": group.get("adjustment"),
            }
        )
        target_start += duration
    return clips, subtitles
