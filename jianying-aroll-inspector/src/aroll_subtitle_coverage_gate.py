from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _overlap(left_start: int, left_end: int, right_start: int, right_end: int) -> int:
    return max(0, min(left_end, right_end) - max(left_start, right_start))


def _text(row: dict[str, Any]) -> str:
    return str(row.get("fragment_text") or row.get("text") or row.get("subtitle_text") or "")


def _word_id(row: dict[str, Any]) -> str:
    return str(row.get("word_id") or "")


def _word_text_by_id(word_timeline: list[dict[str, Any]]) -> dict[str, str]:
    return {_word_id(row): str(row.get("word_text") or "") for row in word_timeline if _word_id(row)}


def _expected_word_rows(
    final_edl: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for word in word_timeline:
        word_id = _word_id(word)
        if not word_id:
            continue
        word_start = int(word.get("start_us") or 0)
        word_end = int(word.get("end_us") or 0)
        if word_end <= word_start:
            continue
        best: dict[str, Any] | None = None
        best_overlap = 0
        for clip in final_edl:
            clip_start = int(clip.get("source_start_us") or clip.get("source_timeline_start_us") or 0)
            clip_end = int(clip.get("source_end_us") or clip.get("source_timeline_end_us") or 0)
            overlap = _overlap(word_start, word_end, clip_start, clip_end)
            if overlap > best_overlap:
                best_overlap = overlap
                best = clip
        if best and best_overlap / max(1, word_end - word_start) >= 0.50:
            clip_source_start = int(best.get("source_start_us") or best.get("source_timeline_start_us") or 0)
            clip_source_end = int(best.get("source_end_us") or best.get("source_timeline_end_us") or 0)
            clip_target_start = int(best.get("target_start_us") or 0)
            clip_target_duration = int(best.get("target_duration_us") or 0)
            source_duration = max(1, clip_source_end - clip_source_start)
            target_word_start = clip_target_start + int((max(word_start, clip_source_start) - clip_source_start) * clip_target_duration / source_duration)
            target_word_end = clip_target_start + int((min(word_end, clip_source_end) - clip_source_start) * clip_target_duration / source_duration)
            rows.append(
                {
                    "word_id": word_id,
                    "word_text": word.get("word_text"),
                    "source_start_us": word_start,
                    "source_end_us": word_end,
                    "target_start_us": target_word_start,
                    "target_end_us": target_word_end,
                }
            )
    return rows


def audit_subtitle_coverage(
    final_speech_units: list[dict[str, Any]],
    display_subtitle_plan: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]] | None = None,
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    final_units = [
        row for row in final_speech_units
        if int(row.get("source_end_us") or row.get("source_timeline_end_us") or 0)
        > int(row.get("source_start_us") or row.get("source_timeline_start_us") or 0)
    ]
    covered = 0
    missing: list[dict[str, Any]] = []
    for unit in final_units:
        start = int(unit.get("source_start_us") or unit.get("source_timeline_start_us") or 0)
        end = int(unit.get("source_end_us") or unit.get("source_timeline_end_us") or 0)
        if end <= start:
            continue
        best_overlap = 0
        best_text = ""
        for sub in display_subtitle_plan:
            sub_start = int(sub.get("source_start_us") or 0)
            sub_end = int(sub.get("source_end_us") or 0)
            overlap = _overlap(start, end, sub_start, sub_end)
            if overlap > best_overlap:
                best_overlap = overlap
                best_text = _text(sub)
        ratio = best_overlap / max(1, end - start)
        if ratio >= 0.30:
            covered += 1
        else:
            missing.append(
                {
                    "unit_id": unit.get("unit_id") or unit.get("clip_id"),
                    "source_start_us": start,
                    "source_end_us": end,
                    "unit_text": _text(unit),
                    "best_subtitle_text": best_text,
                    "coverage_ratio": round(ratio, 4),
                }
            )

    word_timeline = word_timeline or []
    expected_word_rows = _expected_word_rows(final_speech_units, word_timeline) if word_timeline else []
    expected_word_ids = {str(row.get("word_id") or "") for row in expected_word_rows if row.get("word_id")}
    displayed_word_ids = {
        str(word_id)
        for row in display_subtitle_plan
        for word_id in (row.get("word_ids") or [])
        if str(word_id)
    }
    missing_word_ids = sorted(expected_word_ids - displayed_word_ids)
    word_text = _word_text_by_id(word_timeline)
    missing_word_rows = [row for row in expected_word_rows if str(row.get("word_id") or "") in set(missing_word_ids)]
    word_coverage_ratio = len(expected_word_ids & displayed_word_ids) / max(1, len(expected_word_ids)) if expected_word_ids else 1.0

    report = {
        "final_speech_unit_count": len(final_units),
        "subtitle_covered_speech_unit_count": covered,
        "missing_subtitle_unit_count": len(missing),
        "missing_subtitle_text_samples": [row.get("unit_text") or "" for row in missing[:20]],
        "expected_word_count": len(expected_word_ids),
        "displayed_word_count": len(displayed_word_ids),
        "missing_word_count": len(missing_word_ids),
        "missing_word_ids": missing_word_ids[:200],
        "missing_word_text_samples": [word_text.get(word_id, "") for word_id in missing_word_ids[:50]],
        "missing_word_source_ranges": [
            {"word_id": row.get("word_id"), "start_us": row.get("source_start_us"), "end_us": row.get("source_end_us")}
            for row in missing_word_rows[:50]
        ],
        "missing_word_target_ranges": [
            {"word_id": row.get("word_id"), "start_us": row.get("target_start_us"), "end_us": row.get("target_end_us")}
            for row in missing_word_rows[:50]
        ],
        "subtitle_word_coverage_ratio": round(word_coverage_ratio, 6),
        "word_level_coverage_supported": bool(word_timeline),
        "subtitle_coverage_gate_passed": len(missing) == 0 and len(missing_word_ids) == 0 and word_coverage_ratio >= 0.98,
        "missing_units": missing[:100],
    }
    if output_path:
        write_json(output_path, report)
    return report
