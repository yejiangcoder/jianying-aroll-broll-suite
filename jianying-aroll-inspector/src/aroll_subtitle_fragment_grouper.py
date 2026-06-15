from __future__ import annotations

from typing import Any


MIN_TEXT_LEN = 4
MERGE_GAP_US = 300_000
MIN_DURATION_US = 800_000
MAX_DURATION_US = 4_500_000
MAX_TEXT_LEN = 24


def should_merge(prev: dict[str, Any], curr: dict[str, Any]) -> bool:
    prev_text = str(prev.get("text") or "")
    curr_text = str(curr.get("text") or "")
    gap = int(curr.get("source_start_us") or 0) - int(prev.get("source_end_us") or 0)
    if len(prev_text) < MIN_TEXT_LEN or len(curr_text) < MIN_TEXT_LEN:
        return gap < MERGE_GAP_US
    if gap < MERGE_GAP_US and len(prev_text) + len(curr_text) <= MAX_TEXT_LEN:
        return True
    return False


def group_subtitle_fragments(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: (int(row.get("source_start_us") or 0), int(row.get("source_end_us") or 0)))
    groups: list[dict[str, Any]] = []
    for row in ordered:
        text = str(row.get("text") or "")
        if not text:
            continue
        item = {
            "source_subtitle_uids": [row.get("subtitle_uid")],
            "source_subtitle_indices": [row.get("subtitle_index")],
            "source_texts": [row.get("source_text") or text],
            "fragment_text": text,
            "text": text,
            "source_start_us": int(row.get("source_start_us") or 0),
            "source_end_us": int(row.get("source_end_us") or 0),
            "reason": row.get("reason") or "normal",
        }
        if groups and should_merge(groups[-1], item):
            prev = groups[-1]
            prev["source_subtitle_uids"].extend(item["source_subtitle_uids"])
            prev["source_subtitle_indices"].extend(item["source_subtitle_indices"])
            prev["source_texts"].extend(item["source_texts"])
            prev["fragment_text"] = str(prev["fragment_text"]) + str(item["fragment_text"])
            prev["text"] = prev["fragment_text"]
            prev["source_end_us"] = item["source_end_us"]
            prev["reason"] = "grouped_phrase"
        else:
            groups.append(item)
    for idx, group in enumerate(groups, start=1):
        group["fragment_id"] = f"gsub_{idx:04d}"
        group["target_start_us"] = 0
        group["target_duration_us"] = max(MIN_DURATION_US, min(MAX_DURATION_US, int(group["source_end_us"]) - int(group["source_start_us"])))
    single_char_count = sum(1 for group in groups if len(str(group.get("fragment_text") or "")) == 1)
    report = {
        "input_fragment_count": len(rows),
        "grouped_subtitle_count": len(groups),
        "single_char_subtitle_count": single_char_count,
        "has_split_ni_keyi_xiao_tamen": any(str(group.get("fragment_text") or "") == "你可以" for group in groups)
        and any(str(group.get("fragment_text") or "") == "嘲笑他们虚伪" for group in groups),
        "final_subtitle_texts": [group["fragment_text"] for group in groups],
    }
    return groups, report

