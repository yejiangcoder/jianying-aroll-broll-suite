from __future__ import annotations

import json
import math
from array import array
from pathlib import Path
from typing import Any

from aroll_safe_gap_cutter import FRAME_US, SAMPLE_RATE, SafeGapCutter


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _rms(frame: array) -> float:
    if not frame:
        return 0.0
    return math.sqrt(sum(int(x) * int(x) for x in frame) / len(frame))


def _load_samples(raw_path: Path) -> array:
    samples = array("h")
    samples.frombytes(raw_path.read_bytes())
    return samples


def speech_islands(raw_path: Path, start_us: int, end_us: int) -> list[dict[str, Any]]:
    if end_us <= start_us:
        return []
    samples = _load_samples(raw_path)
    frame_size = max(1, int(SAMPLE_RATE * FRAME_US / 1_000_000))
    start_sample = max(0, int(start_us * SAMPLE_RATE / 1_000_000))
    end_sample = min(len(samples), int(end_us * SAMPLE_RATE / 1_000_000))
    rows: list[dict[str, Any]] = []
    for offset in range(start_sample, end_sample, frame_size):
        frame = samples[offset : min(end_sample, offset + frame_size)]
        frame_start_us = int(offset * 1_000_000 / SAMPLE_RATE)
        frame_end_us = int(min(end_sample, offset + frame_size) * 1_000_000 / SAMPLE_RATE)
        rows.append({"start_us": frame_start_us, "end_us": frame_end_us, "rms": _rms(frame)})
    if not rows:
        return []
    rms_values = sorted(row["rms"] for row in rows)
    p35 = rms_values[int(len(rms_values) * 0.35)]
    threshold = max(180.0, p35 * 1.65)
    islands: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    gap_frames = 0
    for row in rows:
        active = row["rms"] >= threshold
        if active:
            if current is None:
                current = {
                    "start_us": row["start_us"],
                    "end_us": row["end_us"],
                    "peak_rms": row["rms"],
                    "avg_rms_values": [row["rms"]],
                }
            else:
                current["end_us"] = row["end_us"]
                current["peak_rms"] = max(float(current["peak_rms"]), float(row["rms"]))
                current["avg_rms_values"].append(row["rms"])
            gap_frames = 0
        elif current is not None:
            gap_frames += 1
            if gap_frames >= 3:
                values = current.pop("avg_rms_values")
                current["duration_us"] = int(current["end_us"]) - int(current["start_us"])
                current["avg_rms"] = sum(values) / len(values)
                if int(current["duration_us"]) >= 80_000:
                    islands.append(current)
                current = None
                gap_frames = 0
    if current is not None:
        values = current.pop("avg_rms_values")
        current["duration_us"] = int(current["end_us"]) - int(current["start_us"])
        current["avg_rms"] = sum(values) / len(values)
        if int(current["duration_us"]) >= 80_000:
            islands.append(current)
    return islands


def find_pinglun_occurrences(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(words, key=lambda row: (int(row.get("subtitle_index") or 0), int(row.get("word_index_in_subtitle") or 0)))
    occurrences: list[dict[str, Any]] = []
    for left, right in zip(ordered, ordered[1:]):
        if str(left.get("word_text") or "") == "评论" and str(right.get("word_text") or "") == "区":
            occurrences.append(
                {
                    "phrase": "评论区",
                    "word_ids": [left.get("word_id"), right.get("word_id")],
                    "start_us": int(left["start_us"]),
                    "end_us": int(right["end_us"]),
                    "subtitle_index": int(left.get("subtitle_index") or 0),
                    "left_word": left,
                    "right_word": right,
                }
            )
    return occurrences


def diagnose_hidden_repeat(
    grouped_subtitles: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
    cutter: SafeGapCutter,
) -> tuple[dict[str, Any], str]:
    target_group = next(
        (row for row in grouped_subtitles if "评论区" in str(row.get("fragment_text") or row.get("text") or "")),
        None,
    )
    if not target_group:
        report = {
            "target_text": "评论区",
            "word_timeline_occurrences": 0,
            "asr_collapsed_audio_repeat": False,
            "speech_islands": [],
            "hidden_repeat_candidates": [],
            "recommended_action": "no_action",
            "confidence": "low",
            "warnings": ["TARGET_GROUP_NOT_FOUND"],
        }
        return report, "# Hidden Audio Repeat Context\n\nTARGET_GROUP_NOT_FOUND\n"

    indices = {int(item) for item in target_group.get("source_subtitle_indices") or []}
    group_words = [row for row in word_timeline if int(row.get("subtitle_index") or -1) in indices]
    occurrences = find_pinglun_occurrences(group_words)
    word_timeline_occurrences = len(occurrences)
    warnings: list[str] = []
    if occurrences:
        window_start = max(0, int(occurrences[0]["start_us"]) - 500_000)
        window_end = int((occurrences[-1] if len(occurrences) > 1 else occurrences[0])["end_us"]) + 800_000
    else:
        window_start = max(0, int(target_group.get("source_start_us") or 0) - 500_000)
        window_end = int(target_group.get("source_end_us") or window_start) + 800_000
    islands = speech_islands(cutter.raw_path, window_start, window_end)
    candidates: list[dict[str, Any]] = []
    recommended_action = "no_action"
    confidence = "low"
    keep_from_word_id = ""
    if len(occurrences) >= 2:
        first, second = occurrences[0], occurrences[1]
        candidates.append(
            {
                "type": "word_timeline_duplicate",
                "remove_start_us": int(first["start_us"]),
                "remove_end_us": int(second["start_us"]),
                "keep_start_us": int(second["start_us"]),
                "first_occurrence": {
                    "start_us": int(first["start_us"]),
                    "end_us": int(first["end_us"]),
                    "word_ids": first["word_ids"],
                },
                "second_occurrence": {
                    "start_us": int(second["start_us"]),
                    "end_us": int(second["end_us"]),
                    "word_ids": second["word_ids"],
                },
                "gap_between_occurrences_us": int(second["start_us"]) - int(first["end_us"]),
            }
        )
        recommended_action = "remove_first_audio_island"
        confidence = "high"
        keep_from_word_id = str(second["word_ids"][0])
    elif len(occurrences) == 1:
        recommended_action = "keep_manual_review"
        confidence = "low"
        warnings.append("ASR_COLLAPSED_AUDIO_REPEAT_POSSIBLE_BUT_NOT_CONFIRMED_BY_WORD_TIMELINE")
    else:
        warnings.append("PINGLUN_WORD_OCCURRENCE_NOT_FOUND")
    report = {
        "target_text": "评论区",
        "target_fragment_id": target_group.get("fragment_id"),
        "word_timeline_occurrences": word_timeline_occurrences,
        "asr_collapsed_audio_repeat": word_timeline_occurrences == 1,
        "audio_window_start_us": window_start,
        "audio_window_end_us": window_end,
        "speech_islands": islands,
        "hidden_repeat_candidates": candidates,
        "recommended_action": recommended_action,
        "confidence": confidence,
        "keep_from_word_id": keep_from_word_id,
        "warnings": warnings,
        "actual_word_context": [
            {
                "word_id": row.get("word_id"),
                "subtitle_index": row.get("subtitle_index"),
                "word_text": row.get("word_text"),
                "start_us": row.get("start_us"),
                "end_us": row.get("end_us"),
                "duration_us": row.get("duration_us"),
            }
            for row in group_words
        ],
        "audio_path": str(cutter.video_path),
        "raw_path": str(cutter.raw_path),
    }
    lines = [
        "# Hidden Audio Repeat Context",
        "",
        f"- target_text: 评论区",
        f"- target_fragment_id: {target_group.get('fragment_id')}",
        f"- subtitle_text: {target_group.get('fragment_text') or target_group.get('text')}",
        f"- source_start_us: {target_group.get('source_start_us')}",
        f"- source_end_us: {target_group.get('source_end_us')}",
        f"- word_timeline_occurrences: {word_timeline_occurrences}",
        f"- recommended_action: {recommended_action}",
        f"- confidence: {confidence}",
        "",
        "## Word timeline context",
    ]
    for row in report["actual_word_context"]:
        lines.append(f"- {row['word_id']} | {row['word_text']} | {row['start_us']} - {row['end_us']}")
    lines.extend(["", "## Speech islands"])
    for row in islands:
        lines.append(f"- {row['start_us']} - {row['end_us']} | duration={row['duration_us']} | peak={round(row['peak_rms'], 2)}")
    return report, "\n".join(lines) + "\n"
