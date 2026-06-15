from __future__ import annotations

import json
from typing import Any


TEXT_KEYS = ("text", "texts", "word", "words")
START_KEYS = ("start_time", "start", "starts", "startTime", "begin")
END_KEYS = ("end_time", "end", "ends", "endTime", "finish")


def safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def scalar_list(value: Any) -> bool:
    return isinstance(value, list) and all(not isinstance(item, (dict, list)) for item in value)


def candidate_from_dict(obj: dict[str, Any], path: str) -> dict[str, Any] | None:
    text_key = next((key for key in TEXT_KEYS if scalar_list(obj.get(key))), None)
    start_key = next((key for key in START_KEYS if scalar_list(obj.get(key))), None)
    end_key = next((key for key in END_KEYS if scalar_list(obj.get(key))), None)
    if not text_key or not start_key or not end_key:
        return None
    texts = [str(item) for item in obj.get(text_key) or []]
    starts = [safe_int(item) for item in obj.get(start_key) or []]
    ends = [safe_int(item) for item in obj.get(end_key) or []]
    n = min(len(texts), len(starts), len(ends))
    if n <= 0:
        return None
    starts = starts[:n]
    ends = ends[:n]
    if any(item is None for item in starts + ends):
        return None
    return {
        "path": path,
        "schema": "parallel_arrays",
        "text_key": text_key,
        "start_key": start_key,
        "end_key": end_key,
        "words": [
            {"text": texts[i], "start": int(starts[i]), "end": int(ends[i])}
            for i in range(n)
        ],
    }


def candidate_from_list(obj: list[Any], path: str) -> dict[str, Any] | None:
    if not obj or not all(isinstance(item, dict) for item in obj):
        return None
    words: list[dict[str, Any]] = []
    for item in obj:
        text = None
        for key in TEXT_KEYS:
            if key in item and not isinstance(item.get(key), (dict, list)):
                text = str(item.get(key) or "")
                break
        start = None
        end = None
        for key in START_KEYS:
            if key in item:
                start = safe_int(item.get(key))
                break
        for key in END_KEYS:
            if key in item:
                end = safe_int(item.get(key))
                break
        if text is None or start is None or end is None:
            return None
        words.append({"text": text, "start": start, "end": end})
    return {"path": path, "schema": "list_of_word_dicts", "words": words}


def find_word_candidates(value: Any, path: str = "material", depth: int = 0) -> list[dict[str, Any]]:
    if depth > 8:
        return []
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        direct = candidate_from_dict(value, path)
        if direct:
            found.append(direct)
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if isinstance(child, str) and child.strip().startswith(("{", "[")):
                try:
                    parsed = json.loads(child)
                except Exception:
                    parsed = None
                if parsed is not None:
                    found.extend(find_word_candidates(parsed, child_path + "#json", depth + 1))
            elif isinstance(child, (dict, list)):
                found.extend(find_word_candidates(child, child_path, depth + 1))
    elif isinstance(value, list):
        direct = candidate_from_list(value, path)
        if direct:
            found.append(direct)
        for index, child in enumerate(value[:30]):
            if isinstance(child, (dict, list)):
                found.extend(find_word_candidates(child, f"{path}[{index}]", depth + 1))
    return found


def detect_unit(words: list[dict[str, Any]], subtitle_start_us: int, subtitle_end_us: int) -> str:
    if not words:
        return "unknown"
    starts = [int(word["start"]) for word in words]
    ends = [int(word["end"]) for word in words]
    max_time = max(max(starts), max(ends))
    min_time = min(min(starts), min(ends))
    duration_us = max(1, subtitle_end_us - subtitle_start_us)
    duration_ms = duration_us / 1000.0

    if subtitle_start_us * 0.75 <= min_time <= subtitle_end_us * 1.25 and subtitle_start_us * 0.75 <= max_time <= subtitle_end_us * 1.25:
        return "absolute_us"
    if abs(max_time - duration_ms) <= max(160.0, duration_ms * 0.45) or max_time <= duration_ms * 1.8:
        return "ms"
    if abs(max_time - duration_us) <= max(160_000.0, duration_us * 0.45):
        return "us"
    return "unknown"


def convert_time(raw: int, unit: str, subtitle_start_us: int) -> int | None:
    if unit == "ms":
        return subtitle_start_us + raw * 1000
    if unit == "us":
        return subtitle_start_us + raw
    if unit == "absolute_us":
        return raw
    return None


def build_word_timeline(subtitles: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    word_rows: list[dict[str, Any]] = []
    schema_rows: list[dict[str, Any]] = []
    unit_stats = {"ms": 0, "us": 0, "absolute_us": 0, "unknown": 0}
    subtitle_with_word_timing = 0
    warnings: list[str] = []

    for row in subtitles:
        subtitle_uid = str(row.get("subtitle_uid") or "")
        subtitle_index = int(row.get("subtitle_index") or 0)
        subtitle_start_us = int(row.get("start_us") or 0)
        subtitle_end_us = int(row.get("end_us") or 0)
        candidates = find_word_candidates(row.get("material") or {})
        candidates.sort(key=lambda item: len(item.get("words") or []), reverse=True)
        selected = candidates[0] if candidates else None
        if not selected:
            warnings.append(f"{subtitle_uid}:WORDS_NOT_FOUND")
            schema_rows.append({"subtitle_uid": subtitle_uid, "subtitle_index": subtitle_index, "candidate_count": 0, "selected_path": ""})
            continue
        words = selected["words"]
        unit = detect_unit(words, subtitle_start_us, subtitle_end_us)
        unit_stats[unit] += 1
        schema_rows.append(
            {
                "subtitle_uid": subtitle_uid,
                "subtitle_index": subtitle_index,
                "candidate_count": len(candidates),
                "selected_path": selected.get("path"),
                "selected_schema": selected.get("schema"),
                "selected_word_count": len(words),
                "unit_detected": unit,
                "candidate_paths": [
                    {"path": item.get("path"), "schema": item.get("schema"), "word_count": len(item.get("words") or [])}
                    for item in candidates[:8]
                ],
            }
        )
        if unit == "unknown":
            warnings.append(f"{subtitle_uid}:WORD_TIME_UNIT_UNKNOWN")
            continue
        subtitle_with_word_timing += 1
        for word_index, word in enumerate(words):
            start_us = convert_time(int(word["start"]), unit, subtitle_start_us)
            end_us = convert_time(int(word["end"]), unit, subtitle_start_us)
            if start_us is None or end_us is None:
                continue
            end_us = max(start_us, end_us)
            word_rows.append(
                {
                    "word_id": f"w_{len(word_rows) + 1:06d}",
                    "subtitle_uid": subtitle_uid,
                    "subtitle_index": subtitle_index,
                    "word_text": str(word["text"]),
                    "word_index_in_subtitle": word_index,
                    "word_start_raw": int(word["start"]),
                    "word_end_raw": int(word["end"]),
                    "unit_detected": unit,
                    "start_us": start_us,
                    "end_us": end_us,
                    "duration_us": end_us - start_us,
                    "subtitle_start_us": subtitle_start_us,
                    "subtitle_end_us": subtitle_end_us,
                }
            )

    report = {
        "subtitle_count": len(subtitles),
        "subtitle_with_word_timing": subtitle_with_word_timing,
        "word_count": len(word_rows),
        "unit_stats": unit_stats,
        "schema_rows": schema_rows,
        "fatal_reasons": [],
        "warnings": warnings,
    }
    return word_rows, report
