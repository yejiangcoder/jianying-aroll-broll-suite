from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any


TARGET_MIN_CHARS = 10
TARGET_MAX_CHARS = 18
HARD_MAX_CHARS = 20
MIN_DURATION_US = 800_000
TARGET_MAX_DURATION_US = 3_000_000
HARD_MAX_DURATION_US = 3_500_000


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def text_len(text: str) -> int:
    return len(str(text or "").strip())


def source_to_target(source_us: int, clips: list[dict[str, Any]]) -> int | None:
    for clip in clips:
        start = int(clip.get("source_timeline_start_us") or clip["source_start_us"])
        end = int(clip.get("source_timeline_end_us") or clip["source_end_us"])
        if start <= source_us <= end:
            return int(clip["target_start_us"]) + (source_us - start)
    future = [clip for clip in clips if int(clip.get("source_timeline_start_us") or clip["source_start_us"]) > source_us]
    if future:
        nearest = min(future, key=lambda row: int(row.get("source_timeline_start_us") or row["source_start_us"]))
        return int(nearest["target_start_us"])
    return None


def words_for_indices(word_timeline: list[dict[str, Any]], indices: set[int]) -> list[dict[str, Any]]:
    return sorted(
        [row for row in word_timeline if int(row.get("subtitle_index") or -1) in indices],
        key=lambda row: (int(row.get("start_us") or 0), int(row.get("end_us") or 0)),
    )


def find_contiguous_word_span(words: list[dict[str, Any]], wanted_text: str) -> list[dict[str, Any]]:
    wanted = str(wanted_text or "")
    if not wanted:
        return []
    best: list[dict[str, Any]] = []
    for start in range(len(words)):
        acc = ""
        for end in range(start, len(words)):
            acc += str(words[end].get("word_text") or "")
            if acc == wanted:
                best = words[start : end + 1]
            if len(acc) > len(wanted) + 8:
                break
    return best or words


def kept_words_for_row(row: dict[str, Any], word_timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indices = {int(row["subtitle_index"])}
    words = words_for_indices(word_timeline, indices)
    text = str(row.get("text") or "")
    source_text = str(row.get("source_text") or text)
    if text and text != source_text:
        return find_contiguous_word_span(words, text)
    return words


def kept_words_from_rows(rows: list[dict[str, Any]], word_timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        for word in kept_words_for_row(row, word_timeline):
            out.append(
                word | {
                    "display_text_source": row.get("text"),
                    "source_text": row.get("source_text"),
                    "source_subtitle_uid": row.get("subtitle_uid"),
                    "source_subtitle_index": row.get("subtitle_index"),
                    "row_reason": row.get("reason") or "normal",
                }
            )
    out.sort(key=lambda word: (int(word.get("start_us") or 0), int(word.get("end_us") or 0)))
    return out


def split_words_for_display(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []

    def current_text() -> str:
        return "".join(str(word.get("word_text") or "") for word in current)

    for word in words:
        candidate_text = current_text() + str(word.get("word_text") or "")
        candidate_start = int(current[0]["start_us"]) if current else int(word["start_us"])
        candidate_end = int(word["end_us"])
        candidate_duration = candidate_end - candidate_start
        if current and (text_len(candidate_text) > TARGET_MAX_CHARS or candidate_duration > TARGET_MAX_DURATION_US):
            chunks.append(current)
            current = [word]
        else:
            current.append(word)
    if current:
        chunks.append(current)

    # Merge very short chunks forward/backward when it does not violate hard limits.
    merged: list[list[dict[str, Any]]] = []
    index = 0
    while index < len(chunks):
        chunk = chunks[index]
        chunk_text = "".join(str(word.get("word_text") or "") for word in chunk)
        if text_len(chunk_text) < 4 and index + 1 < len(chunks):
            next_chunk = chunks[index + 1]
            combined = chunk + next_chunk
            combined_text = "".join(str(word.get("word_text") or "") for word in combined)
            duration = int(combined[-1]["end_us"]) - int(combined[0]["start_us"])
            if text_len(combined_text) <= HARD_MAX_CHARS and duration <= HARD_MAX_DURATION_US:
                merged.append(combined)
                index += 2
                continue
        if text_len(chunk_text) < 4 and merged:
            combined = merged[-1] + chunk
            combined_text = "".join(str(word.get("word_text") or "") for word in combined)
            duration = int(combined[-1]["end_us"]) - int(combined[0]["start_us"])
            if text_len(combined_text) <= HARD_MAX_CHARS and duration <= HARD_MAX_DURATION_US:
                merged[-1] = combined
                index += 1
                continue
        merged.append(chunk)
        index += 1
    return merged


def _chunk_text(chunk: list[dict[str, Any]]) -> str:
    return "".join(str(word.get("word_text") or "") for word in chunk)


def smooth_bad_prefix_chunks(chunks: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    """Repair ASR subtitle boundaries that split as "...X / 的X..."."""
    if len(chunks) < 2:
        return chunks
    repaired: list[list[dict[str, Any]]] = []
    index = 0
    bad_prefixes = {"的"}
    while index < len(chunks):
        if index + 1 >= len(chunks):
            repaired.append(chunks[index])
            break
        prev = chunks[index]
        curr = chunks[index + 1]
        prev_text = _chunk_text(prev)
        curr_text = _chunk_text(curr)
        if not curr_text or curr_text[0] not in bad_prefixes or len(prev) < 3:
            repaired.append(prev)
            index += 1
            continue
        curr_without_prefix = curr_text[1:]
        best_suffix_word_start: int | None = None
        best_suffix_text = ""
        for suffix_start in range(1, len(prev)):
            suffix_text = _chunk_text(prev[suffix_start:])
            if len(suffix_text) < 2:
                continue
            if curr_without_prefix.startswith(suffix_text) and len(suffix_text) > len(best_suffix_text):
                best_suffix_word_start = suffix_start
                best_suffix_text = suffix_text
        if best_suffix_word_start is None:
            repaired.append(prev)
            index += 1
            continue
        duplicate_prefix_len = 1 + len(best_suffix_text)
        consumed = 0
        curr_tail_start = 0
        for word_i, word in enumerate(curr):
            consumed += len(str(word.get("word_text") or ""))
            if consumed >= duplicate_prefix_len:
                curr_tail_start = word_i + 1
                break
        new_prev = prev[:best_suffix_word_start]
        new_curr = prev[best_suffix_word_start:] + curr[curr_tail_start:]
        if (
            text_len(_chunk_text(new_prev)) >= 4
            and text_len(_chunk_text(new_curr)) <= HARD_MAX_CHARS
        ):
            repaired.append(new_prev)
            repaired.append(new_curr)
            index += 2
            continue
        repaired.append(prev)
        index += 1
    return repaired


def build_display_subtitle_plan(
    selected_rows: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
    final_edl: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    chunks: list[list[dict[str, Any]]] = []
    for row in selected_rows:
        row_words = [
            word | {
                "display_text_source": row.get("text"),
                "source_text": row.get("source_text"),
                "source_subtitle_uid": row.get("subtitle_uid"),
                "source_subtitle_index": row.get("subtitle_index"),
                "row_reason": row.get("reason") or "normal",
            }
            for word in kept_words_for_row(row, word_timeline)
        ]
        chunks.extend(split_words_for_display(row_words))
    chunks = smooth_bad_prefix_chunks(chunks)
    plan: list[dict[str, Any]] = []
    dropped_chunks: list[dict[str, Any]] = []
    for idx, chunk in enumerate(chunks, start=1):
        if not chunk:
            continue
        source_start = int(chunk[0]["start_us"])
        source_end = int(chunk[-1]["end_us"])
        target_start = source_to_target(source_start, final_edl)
        target_end = source_to_target(source_end, final_edl)
        text = "".join(str(word.get("word_text") or "") for word in chunk)
        if target_start is None or target_end is None or target_end <= target_start:
            dropped_chunks.append({"text": text, "source_start_us": source_start, "source_end_us": source_end})
            continue
        source_indices = sorted({int(word.get("source_subtitle_index") or word.get("subtitle_index") or 0) for word in chunk})
        source_uids = []
        for word in chunk:
            uid = str(word.get("source_subtitle_uid") or word.get("subtitle_uid") or "")
            if uid and uid not in source_uids:
                source_uids.append(uid)
        plan.append(
            {
                "fragment_id": f"dsub_{idx:04d}",
                "fragment_text": text,
                "text": text,
                "source_subtitle_indices": source_indices,
                "source_subtitle_uids": source_uids,
                "source_start_us": source_start,
                "source_end_us": source_end,
                "target_start_us": target_start,
                "target_duration_us": target_end - target_start,
                "reason": "phase4d2_display_subtitle",
                "word_ids": [word.get("word_id") for word in chunk],
            }
        )
    report = readability_report(plan)
    report["dropped_chunk_count"] = len(dropped_chunks)
    report["dropped_chunks"] = dropped_chunks
    return plan, report


def readability_report(plan: list[dict[str, Any]]) -> dict[str, Any]:
    char_counts = [text_len(str(row.get("fragment_text") or "")) for row in plan]
    durations = [int(row.get("target_duration_us") or 0) for row in plan]
    overlong = [row for row in plan if text_len(str(row.get("fragment_text") or "")) > HARD_MAX_CHARS]
    single_char = [row for row in plan if text_len(str(row.get("fragment_text") or "")) == 1]
    too_short = [row for row in plan if int(row.get("target_duration_us") or 0) < MIN_DURATION_US]
    too_long_duration = [row for row in plan if int(row.get("target_duration_us") or 0) > HARD_MAX_DURATION_US]
    return {
        "subtitle_count": len(plan),
        "max_chars": max(char_counts) if char_counts else 0,
        "avg_chars": round(statistics.mean(char_counts), 3) if char_counts else 0,
        "max_duration_s": round(max(durations) / 1_000_000, 3) if durations else 0,
        "avg_duration_s": round(statistics.mean(durations) / 1_000_000, 3) if durations else 0,
        "overlong_subtitle_count": len(overlong),
        "single_char_subtitle_count": len(single_char),
        "too_short_subtitle_count": len(too_short),
        "too_long_duration_count": len(too_long_duration),
        "has_overlong_subtitle": bool(overlong),
        "has_single_char_subtitle": bool(single_char),
        "overlong_subtitles": [{"text": row.get("fragment_text"), "chars": text_len(str(row.get("fragment_text") or ""))} for row in overlong],
        "single_char_subtitles": [{"text": row.get("fragment_text"), "fragment_id": row.get("fragment_id")} for row in single_char],
    }
