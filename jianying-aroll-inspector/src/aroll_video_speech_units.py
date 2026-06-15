from __future__ import annotations

from typing import Any

from aroll_display_subtitle_planner import kept_words_for_row


def selected_rows_for_range(
    subtitles: list[dict[str, Any]],
    drops: set[int],
    micros: dict[int, dict[str, Any]],
    source_start_us: int,
    source_end_us: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for subtitle in subtitles:
        index = int(subtitle.get("subtitle_index") or 0)
        start = int(subtitle.get("start_us") or 0)
        end = int(subtitle.get("end_us") or start)
        if end <= source_start_us or start >= source_end_us:
            continue
        if index in drops:
            continue
        text = str(subtitle.get("subtitle_text") or "")
        if index in micros:
            text = str(micros[index].get("clean_text") or micros[index].get("replacement_text") or text)
        rows.append(
            {
                "subtitle_index": index,
                "subtitle_uid": subtitle.get("subtitle_uid"),
                "text": text,
                "source_start_us": max(start, source_start_us),
                "source_end_us": min(end, source_end_us),
                "source_subtitle": subtitle,
                "micro_cleanup": micros.get(index),
            }
        )
    rows.sort(key=lambda row: (int(row["source_start_us"]), int(row["source_end_us"])))
    return rows


def build_video_speech_units(
    selected_rows: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    units: list[dict[str, Any]] = []
    missing_word_rows: list[int] = []
    for index, row in enumerate(selected_rows, start=1):
        words = kept_words_for_row(row, word_timeline)
        if words:
            start = int(words[0].get("start_us") or row["source_start_us"])
            end = int(words[-1].get("end_us") or row["source_end_us"])
            text = "".join(str(word.get("word_text") or "") for word in words) or str(row.get("text") or "")
            word_ids = [word.get("word_id") for word in words]
        else:
            missing_word_rows.append(int(row.get("subtitle_index") or 0))
            start = int(row.get("source_start_us") or 0)
            end = int(row.get("source_end_us") or start)
            text = str(row.get("text") or "")
            word_ids = []
        if end <= start:
            continue
        units.append(
            {
                "unit_id": f"vu_{index:06d}",
                "fragment_id": f"vunit_{index:04d}",
                "subtitle_index": row.get("subtitle_index"),
                "subtitle_uid": row.get("subtitle_uid"),
                "text": text,
                "source_subtitle_indices": [int(row.get("subtitle_index") or 0)],
                "source_subtitle_uids": [row.get("subtitle_uid")],
                "speech_start_us": start,
                "speech_end_us": end,
                "source_start_us": start,
                "source_end_us": end,
                "source_duration_us": end - start,
                "word_count": len(words),
                "word_ids": word_ids,
                "adjustment": None,
                "row_reason": row.get("reason"),
            }
        )
    units.sort(key=lambda row: int(row["speech_start_us"]))
    return units, {
        "unit_count": len(units),
        "missing_word_row_count": len(missing_word_rows),
        "missing_word_rows": missing_word_rows[:50],
    }
