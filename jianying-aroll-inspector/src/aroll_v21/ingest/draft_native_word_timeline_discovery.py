from __future__ import annotations

from typing import Any


WORD_PATH_TOKENS = {"word", "words", "word_timeline", "token", "tokens", "asr_words", "recognized_words"}
FORBIDDEN_PATH_TOKENS = {"subtitle", "subtitles", "sentence", "sentences", "caption", "captions"}
WORD_TEXT_KEYS = ("word_text", "word", "token", "text", "content")
START_KEYS = ("source_start_us", "start_us", "start", "start_time", "startTime", "begin", "begin_us", "from")
END_KEYS = ("source_end_us", "end_us", "end", "end_time", "endTime", "finish", "finish_us", "to")
DURATION_KEYS = ("duration_us", "duration", "duration_time", "durationTime")
RANGE_KEYS = ("source_timerange", "timerange", "time_range", "timeRange", "range")


def _path_tokens(path: str) -> set[str]:
    return {token for token in path.lower().replace("[", "/").replace("]", "/").split("/") if token}


def _path_is_word_level(path: str) -> bool:
    tokens = _path_tokens(path)
    if tokens & FORBIDDEN_PATH_TOKENS:
        return False
    return bool(tokens & WORD_PATH_TOKENS)


def _has_word_text(row: dict[str, Any]) -> bool:
    return any(isinstance(row.get(key), str) and str(row.get(key) or "").strip() for key in WORD_TEXT_KEYS)


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_int(row: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        if row.get(key) is not None:
            return _coerce_int(row.get(key))
    return None


def _range_value(row: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for range_key in RANGE_KEYS:
        value = row.get(range_key)
        if isinstance(value, dict):
            found = _first_int(value, keys)
            if found is not None:
                return found
        elif isinstance(value, list) and len(value) >= 2:
            if keys == START_KEYS:
                return _coerce_int(value[0])
            if keys == END_KEYS:
                return _coerce_int(value[1])
    return None


def _word_start_end(row: dict[str, Any]) -> tuple[int | None, int | None, str]:
    explicit_source = row.get("source_start_us") is not None and row.get("source_end_us") is not None
    start = _first_int(row, START_KEYS)
    end = _first_int(row, END_KEYS)
    timing_scope = "source" if explicit_source else "unknown"
    if start is None:
        start = _range_value(row, START_KEYS)
        if start is not None:
            timing_scope = "range"
    if end is None:
        end = _range_value(row, END_KEYS)
        if end is not None and timing_scope == "unknown":
            timing_scope = "range"
    if start is not None and end is None:
        duration = _first_int(row, DURATION_KEYS) or _range_value(row, DURATION_KEYS)
        if duration is not None:
            end = start + duration
    return start, end, timing_scope


def _has_word_timing(row: dict[str, Any]) -> bool:
    start, end, _scope = _word_start_end(row)
    return start is not None and end is not None and end > start


def is_draft_native_word_row(row: dict[str, Any]) -> bool:
    return _has_word_text(row) and _has_word_timing(row)


def normalize_draft_native_word_row(row: dict[str, Any], index: int) -> dict[str, Any]:
    start, end, timing_scope = _word_start_end(row)
    start = int(start or 0)
    end = int(end or 0)
    explicit_source = row.get("source_start_us") is not None and row.get("source_end_us") is not None
    word_index = row.get("word_index_in_subtitle")
    if word_index is None:
        word_index = row.get("word_index")
    if word_index is None:
        word_index = index - 1
    return {
        "word_id": str(row.get("word_id") or row.get("id") or f"real_word_{index:06d}"),
        "word_text": str(row.get("word_text") or row.get("word") or row.get("token") or row.get("text") or row.get("content") or ""),
        "start_us": start,
        "end_us": end,
        "source_start_us": start if explicit_source else None,
        "source_end_us": end if explicit_source else None,
        "native_timing_scope": timing_scope,
        "source_material_id": str(row.get("source_material_id") or row.get("material_id") or ""),
        "source_segment_id": str(row.get("source_segment_id") or row.get("segment_id") or "") or None,
        "text_material_id": str(row.get("text_material_id") or ""),
        "subtitle_uid": str(row.get("subtitle_uid") or row.get("subtitle_id") or "") or None,
        "subtitle_index": int(row.get("subtitle_index")) if row.get("subtitle_index") is not None else None,
        "word_index_in_subtitle": int(word_index),
        "confidence": float(row.get("confidence")) if row.get("confidence") is not None else None,
        "is_cuttable_left": bool(row.get("is_cuttable_left", True)),
        "is_cuttable_right": bool(row.get("is_cuttable_right", True)),
    }


def _word_row_rejection_reason(row: dict[str, Any]) -> str:
    if not _has_word_text(row):
        return "missing_word_text"
    start, end, _scope = _word_start_end(row)
    if start is None or end is None:
        return "missing_word_timing"
    if end <= start:
        return "invalid_word_timing"
    return ""


def _empty_material_debug(material_count: int = 0) -> dict[str, Any]:
    return {
        "scanned_text_material_count": material_count,
        "materials_with_words_key": 0,
        "materials_with_nonempty_words": 0,
        "candidate_count": 0,
        "accepted_count": 0,
        "rejected_count": 0,
        "words_schema": "",
        "words_schema_counts": {},
        "sample_rejections": [],
    }


def _merge_debug(*rows: dict[str, Any]) -> dict[str, Any]:
    merged = _empty_material_debug()
    for row in rows:
        merged["scanned_text_material_count"] += int(row.get("scanned_text_material_count") or 0)
        merged["materials_with_words_key"] += int(row.get("materials_with_words_key") or 0)
        merged["materials_with_nonempty_words"] += int(row.get("materials_with_nonempty_words") or 0)
        merged["candidate_count"] += int(row.get("candidate_count") or 0)
        merged["accepted_count"] += int(row.get("accepted_count") or 0)
        merged["rejected_count"] += int(row.get("rejected_count") or 0)
        for schema, count in (row.get("words_schema_counts") or {}).items():
            merged["words_schema_counts"][str(schema)] = int(merged["words_schema_counts"].get(str(schema), 0)) + int(count or 0)
        if len(merged["sample_rejections"]) < 20:
            merged["sample_rejections"].extend((row.get("sample_rejections") or [])[: 20 - len(merged["sample_rejections"])])
    if merged["words_schema_counts"]:
        merged["words_schema"] = max(merged["words_schema_counts"].items(), key=lambda item: item[1])[0]
    return merged


def _dict_of_arrays_word_rows(value: dict[str, Any], *, path: str) -> tuple[list[dict[str, Any]], int, str]:
    starts = value.get("start_time")
    ends = value.get("end_time")
    texts = value.get("text")
    if starts is None and ends is None and texts is None:
        return [], 0, ""
    if not isinstance(starts, list) or not isinstance(ends, list) or not isinstance(texts, list):
        return [], 1, "dict_of_arrays_missing_required_arrays"
    if not (len(starts) == len(ends) == len(texts)):
        return [], 1, "dict_of_arrays_length_mismatch"
    rows: list[dict[str, Any]] = []
    for index, (start, end, text) in enumerate(zip(starts, ends, texts), start=1):
        start_int = _coerce_int(start)
        end_int = _coerce_int(end)
        if start_int is None or end_int is None:
            return [], len(texts), "dict_of_arrays_non_numeric_timing"
        rows.append(
            {
                "text": str(text or ""),
                "start_us": start_int * 1000,
                "end_us": end_int * 1000,
                "native_words_schema": "dict_of_arrays",
                "native_timing_unit": "milliseconds",
                "native_words_path": path,
                "word_index_in_subtitle": index - 1,
            }
        )
    return rows, len(rows), ""


def _material_words(materials: list[dict[str, Any]], *, path: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []
    debug = _empty_material_debug(len(materials))
    for material_index, material in enumerate(materials, start=1):
        if not isinstance(material, dict):
            continue
        if "words" in material:
            debug["materials_with_words_key"] += 1
        words_value = material.get("words")
        if isinstance(words_value, dict):
            expanded_rows, candidate_count, reason = _dict_of_arrays_word_rows(words_value, path=path)
            if candidate_count:
                debug["materials_with_nonempty_words"] += 1
                debug["candidate_count"] += candidate_count
                debug["words_schema_counts"]["dict_of_arrays"] = int(debug["words_schema_counts"].get("dict_of_arrays", 0)) + candidate_count
                debug["words_schema"] = "dict_of_arrays"
            if reason:
                debug["rejected_count"] += 1
                if len(debug["sample_rejections"]) < 20:
                    debug["sample_rejections"].append(
                        {
                            "path": path,
                            "text_material_id": str(material.get("id") or material.get("material_id") or ""),
                            "text_material_index": material_index,
                            "word_index": 0,
                            "reason": reason,
                        }
                    )
                continue
            rows = expanded_rows
        else:
            rows = [row for row in (words_value or []) if isinstance(row, dict)]
        if not rows:
            continue
        if not isinstance(words_value, dict):
            debug["materials_with_nonempty_words"] += 1
            debug["candidate_count"] += len(rows)
            debug["words_schema_counts"]["list_of_objects"] = int(debug["words_schema_counts"].get("list_of_objects", 0)) + len(rows)
            if not debug["words_schema"]:
                debug["words_schema"] = "list_of_objects"
        for row_index, row in enumerate(rows, start=1):
            reason = _word_row_rejection_reason(row)
            if reason:
                debug["rejected_count"] += 1
                if len(debug["sample_rejections"]) < 20:
                    debug["sample_rejections"].append(
                        {
                            "path": path,
                            "text_material_id": str(material.get("id") or material.get("material_id") or ""),
                            "text_material_index": material_index,
                            "word_index": row_index,
                            "reason": reason,
                        }
                    )
                continue
            debug["accepted_count"] += 1
            rows_out.append(
                dict(
                    row,
                    text_material_id=str(material.get("id") or material.get("material_id") or ""),
                    text_material_index=material_index,
                    native_words_path=path,
                )
            )
    return rows_out, debug


def discover_draft_native_word_timeline(
    data: dict[str, Any],
    *,
    text_materials: list[dict[str, Any]] | None = None,
    text_segments: list[dict[str, Any]] | None = None,
    source_segments: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates: list[tuple[str, list[dict[str, Any]]]] = []
    rejected_timed_text_rows = 0
    recursive_debug = _empty_material_debug()
    normalized_text_material_word_rows, normalized_debug = _material_words(
        [dict(row) for row in (text_materials or []) if isinstance(row, dict)],
        path="/normalized_text_materials[]/words",
    )
    if normalized_text_material_word_rows:
        candidates.append(("/normalized_text_materials[]/words", normalized_text_material_word_rows))

    materials = data.get("materials") if isinstance(data.get("materials"), dict) else {}
    raw_debug = _empty_material_debug()
    if int(normalized_debug.get("candidate_count") or 0) == 0:
        text_material_word_rows, raw_debug = _material_words(
            [dict(row) for row in (materials.get("texts") or []) if isinstance(row, dict)],
            path="/materials/texts[]/words",
        )
        if text_material_word_rows:
            candidates.append(("/materials/texts[]/words", text_material_word_rows))
    else:
        raw_debug["scan_skipped_reason"] = "normalized_text_material_words_present"

    def walk(obj: Any, path: str = "", depth: int = 0) -> None:
        nonlocal rejected_timed_text_rows
        if depth > 6:
            return
        if isinstance(obj, dict):
            for key, value in obj.items():
                walk(value, f"{path}/{key}", depth + 1)
            return
        if not isinstance(obj, list) or not obj:
            return
        if path == "/materials/texts[]/words":
            return
        dict_rows = [row for row in obj if isinstance(row, dict)]
        if dict_rows and len(dict_rows) == len(obj):
            if _path_is_word_level(path):
                accepted_rows: list[dict[str, Any]] = []
                recursive_debug["candidate_count"] += len(dict_rows)
                for row_index, row in enumerate(dict_rows, start=1):
                    reason = _word_row_rejection_reason(row)
                    if reason:
                        recursive_debug["rejected_count"] += 1
                        if len(recursive_debug["sample_rejections"]) < 20:
                            recursive_debug["sample_rejections"].append(
                                {"path": path, "word_index": row_index, "reason": reason}
                            )
                    else:
                        recursive_debug["accepted_count"] += 1
                        accepted_rows.append(dict(row))
                if accepted_rows:
                    candidates.append((path, accepted_rows))
            elif _path_tokens(path) & FORBIDDEN_PATH_TOKENS:
                for row in dict_rows:
                    has_text = isinstance(row.get("text"), str) and str(row.get("text") or "").strip()
                    has_time = (row.get("start_us") is not None or row.get("start") is not None) and (
                        row.get("end_us") is not None
                        or row.get("end") is not None
                        or row.get("duration_us") is not None
                        or row.get("duration") is not None
                    )
                    if has_text and has_time:
                        rejected_timed_text_rows += 1
        for row in obj[:10]:
            walk(row, f"{path}[]", depth + 1)

    walk(data)
    material_debug = _merge_debug(normalized_debug, raw_debug, recursive_debug)
    candidate_path_count = len(candidates)
    if not candidates:
        return [], {
            "provider": "draft_native",
            "candidate_count": material_debug["candidate_count"],
            "accepted_count": material_debug["accepted_count"],
            "rejected_count": material_debug["rejected_count"],
            "candidate_path_count": 0,
            "subtitle_as_word_rejected_count": rejected_timed_text_rows,
            "invalid_word_row_count": material_debug["rejected_count"],
            "normalized_text_material_count": len(text_materials or []),
            "text_segment_count": len(text_segments or []),
            "source_segment_count": len(source_segments or []),
            "words_schema": material_debug.get("words_schema") or "",
            "words_schema_counts": material_debug.get("words_schema_counts") or {},
            "scanned_text_material_count": normalized_debug["scanned_text_material_count"],
            "materials_with_words_key": normalized_debug["materials_with_words_key"],
            "materials_with_nonempty_words": normalized_debug["materials_with_nonempty_words"],
            "sample_rejections": material_debug["sample_rejections"],
            "material_word_scan": {
                "normalized_text_materials": normalized_debug,
                "raw_material_texts": raw_debug,
                "recursive": recursive_debug,
                "total": material_debug,
            },
        }
    path, rows = max(candidates, key=lambda item: len(item[1]))
    return [normalize_draft_native_word_row(row, index) for index, row in enumerate(rows, start=1)], {
        "provider": "draft_native",
        "candidate_count": material_debug["candidate_count"],
        "accepted_count": material_debug["accepted_count"],
        "rejected_count": material_debug["rejected_count"],
        "candidate_path_count": candidate_path_count,
        "selected_path": path,
        "selected_word_count": len(rows),
        "subtitle_as_word_rejected_count": rejected_timed_text_rows,
        "invalid_word_row_count": material_debug["rejected_count"],
        "normalized_text_material_count": len(text_materials or []),
        "text_segment_count": len(text_segments or []),
        "source_segment_count": len(source_segments or []),
        "words_schema": material_debug.get("words_schema") or "",
        "words_schema_counts": material_debug.get("words_schema_counts") or {},
        "scanned_text_material_count": normalized_debug["scanned_text_material_count"],
        "materials_with_words_key": normalized_debug["materials_with_words_key"],
        "materials_with_nonempty_words": normalized_debug["materials_with_nonempty_words"],
        "sample_rejections": material_debug["sample_rejections"],
        "material_word_scan": {
            "normalized_text_materials": normalized_debug,
            "raw_material_texts": raw_debug,
            "recursive": recursive_debug,
            "total": material_debug,
        },
    }
