from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aroll_display_subtitle_planner import readability_report, smooth_bad_prefix_chunks, split_words_for_display
from aroll_repair_proposal import RepairProposal, proposal_to_dict


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def word_map(word_timeline: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("word_id") or ""): row for row in word_timeline if str(row.get("word_id") or "")}


def _tokens_for_word_ids(word_ids: list[str], words_by_id: dict[str, dict[str, Any]]) -> list[str]:
    return [str((words_by_id.get(word_id) or {}).get("word_text") or "") for word_id in word_ids]


def _best_repeated_island(tokens: list[str]) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for size in range(min(8, len(tokens) // 2), 1, -1):
        seen: dict[tuple[str, ...], int] = {}
        for index in range(0, len(tokens) - size + 1):
            gram = tuple(tokens[index : index + size])
            if not all(item.strip() for item in gram):
                continue
            first = seen.get(gram)
            if first is not None and index - first >= size:
                best = {
                    "phrase": "".join(gram),
                    "token_ngram_size": size,
                    "first_position": first,
                    "second_position": index,
                    "keep_positions": list(range(first, first + size)),
                    "remove_positions": list(range(index, index + size)),
                }
                return best
            seen.setdefault(gram, index)
    return best


def _source_range_for_word_ids(word_ids: list[str], words_by_id: dict[str, dict[str, Any]]) -> tuple[int, int]:
    starts: list[int] = []
    ends: list[int] = []
    for word_id in word_ids:
        word = words_by_id.get(word_id) or {}
        start = int(word.get("start_us") or 0)
        end = int(word.get("end_us") or 0)
        if end > start:
            starts.append(start)
            ends.append(end)
    return (min(starts), max(ends)) if starts and ends else (0, 0)


def _map_source_to_target(source_us: int, clips: list[dict[str, Any]]) -> int | None:
    for clip in clips:
        start = int(clip.get("source_start_us") or clip.get("source_timeline_start_us") or 0)
        end = int(clip.get("source_end_us") or clip.get("source_timeline_end_us") or 0)
        if start <= source_us <= end:
            return int(clip.get("target_start_us") or 0) + (source_us - start)
    return None


def rebuild_subtitle_plan_for_edl_words(
    final_edl: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build display subtitles strictly from words covered by the final EDL."""
    clips = sorted(final_edl, key=lambda row: int(row.get("target_start_us") or 0))
    words = sorted(word_timeline, key=lambda row: (int(row.get("start_us") or 0), int(row.get("end_us") or 0)))
    chunks: list[list[dict[str, Any]]] = []
    seen_word_ids: set[str] = set()
    dropped_word_ids: list[str] = []
    for clip in clips:
        source_start = int(clip.get("source_start_us") or clip.get("source_timeline_start_us") or 0)
        source_end = int(clip.get("source_end_us") or clip.get("source_timeline_end_us") or 0)
        if source_end <= source_start:
            continue
        clip_words: list[dict[str, Any]] = []
        for word in words:
            word_id = str(word.get("word_id") or "")
            if not word_id or word_id in seen_word_ids:
                continue
            start = int(word.get("start_us") or 0)
            end = int(word.get("end_us") or 0)
            if source_start <= start and end <= source_end:
                seen_word_ids.add(word_id)
                clip_words.append(
                    word
                    | {
                        "display_text_source": word.get("word_text"),
                        "source_text": word.get("word_text"),
                        "source_subtitle_uid": word.get("subtitle_uid"),
                        "source_subtitle_index": word.get("subtitle_index"),
                        "row_reason": "strict_edl_word_rebuild",
                    }
                )
        if clip_words:
            chunks.extend(split_words_for_display(clip_words))
    chunks = smooth_bad_prefix_chunks(chunks)
    plan: list[dict[str, Any]] = []
    dropped_chunks: list[dict[str, Any]] = []
    for idx, chunk in enumerate(chunks, start=1):
        if not chunk:
            continue
        source_start = int(chunk[0].get("start_us") or 0)
        source_end = int(chunk[-1].get("end_us") or 0)
        target_start = _map_source_to_target(source_start, clips)
        target_end = _map_source_to_target(source_end, clips)
        text = "".join(str(word.get("word_text") or "") for word in chunk)
        if target_start is None or target_end is None or target_end <= target_start:
            dropped_chunks.append({"text": text, "source_start_us": source_start, "source_end_us": source_end})
            dropped_word_ids.extend(str(word.get("word_id") or "") for word in chunk if str(word.get("word_id") or ""))
            continue
        source_indices = sorted({int(word.get("source_subtitle_index") or word.get("subtitle_index") or 0) for word in chunk})
        source_uids: list[str] = []
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
                "reason": "strict_edl_word_rebuild",
                "word_ids": [word.get("word_id") for word in chunk],
            }
        )
    report = readability_report(plan)
    report["dropped_chunk_count"] = len(dropped_chunks)
    report["dropped_chunks"] = dropped_chunks
    report["dropped_word_ids"] = sorted(set(dropped_word_ids))
    report["covered_word_count"] = len(seen_word_ids) - len(set(dropped_word_ids))
    return plan, report


def propose_hidden_repeat_repairs(
    *,
    hidden_repeat_report: dict[str, Any],
    display_subtitle_plan: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
) -> tuple[list[RepairProposal], dict[str, Any]]:
    words_by_id = word_map(word_timeline)
    proposals: list[RepairProposal] = []
    unresolved: list[dict[str, Any]] = []
    scanned = 0
    for row in display_subtitle_plan:
        word_ids = [str(word_id) for word_id in (row.get("word_ids") or []) if str(word_id)]
        if len(word_ids) < 4:
            continue
        scanned += 1
        tokens = _tokens_for_word_ids(word_ids, words_by_id)
        island = _best_repeated_island(tokens)
        if not island:
            continue
        remove_ids = [word_ids[pos] for pos in island["remove_positions"] if pos < len(word_ids)]
        keep_ids = [word_ids[pos] for pos in island["keep_positions"] if pos < len(word_ids)]
        start, end = _source_range_for_word_ids(remove_ids, words_by_id)
        if end <= start:
            unresolved.append({"fragment_id": row.get("fragment_id"), "reason": "repeated island has no source range", "island": island})
            continue
        proposals.append(
            RepairProposal(
                proposal_id=f"hidden_repeat_{len(proposals) + 1:04d}",
                repair_type="remove_duplicate_word_island",
                source_gate="hidden_audio_repeat_gate",
                confidence="high",
                reason="word timeline repeated island; keep first occurrence and remove second occurrence",
                duplicate_text=str(island.get("phrase") or ""),
                keep_word_ids=keep_ids,
                remove_word_ids=remove_ids,
                remove_source_start_us=start,
                remove_source_end_us=end,
                preserve_prefix=True,
                preserve_suffix=True,
                source_issue_id=str(row.get("fragment_id") or ""),
                metadata={
                    "fragment_text": row.get("fragment_text") or row.get("text"),
                    "token_ngram_size": island.get("token_ngram_size"),
                    "first_position": island.get("first_position"),
                    "second_position": island.get("second_position"),
                },
            )
        )
    report = {
        "source_gate_word_timeline_repeated_island_count": int(hidden_repeat_report.get("word_timeline_repeated_island_count") or 0),
        "scanned_fragment_count": scanned,
        "proposal_count": len(proposals),
        "unresolved_island_count": len(unresolved),
        "hidden_repeat_proposal_passed": len(unresolved) == 0,
        "proposals": [proposal_to_dict(proposal) for proposal in proposals],
        "unresolved": unresolved,
    }
    return proposals, report

