from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from aroll_final_residual_repeat_auditor import norm_text
from aroll_repeat_fix_planner import source_range_to_target_range


WEAK_ONLY_TEXT = {"就", "然后", "这个", "就是", "那么", "呃", "嗯", "啊", "的"}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def words_for_subtitle_indices(word_timeline: list[dict[str, Any]], indices: list[int]) -> list[dict[str, Any]]:
    wanted = {int(item) for item in indices}
    return sorted(
        [word for word in word_timeline if int(word.get("subtitle_index") or -1) in wanted],
        key=lambda word: (int(word.get("start_us") or 0), int(word.get("end_us") or 0)),
    )


def join_words(words: list[dict[str, Any]]) -> str:
    return "".join(str(word.get("word_text") or "") for word in words)


def find_phrase_word_span(words: list[dict[str, Any]], phrase: str) -> tuple[int, int] | None:
    phrase_n = norm_text(phrase)
    if not phrase_n:
        return None
    best: tuple[int, int] | None = None
    for start in range(len(words)):
        acc = ""
        for end in range(start, len(words)):
            acc += str(words[end].get("word_text") or "")
            acc_n = norm_text(acc)
            if acc_n == phrase_n:
                best = (start, end + 1)
            if len(acc_n) > len(phrase_n) + 4:
                break
    return best


def meaningful_unique(text: str) -> bool:
    text_n = norm_text(text)
    if len(text_n) < 3:
        return False
    if text_n in WEAK_ONLY_TEXT:
        return False
    return True


def build_clip_pieces_for_source_range(source_edl: list[dict[str, Any]], source_start: int, source_end: int, reason: str) -> list[dict[str, Any]]:
    pieces: list[dict[str, Any]] = []
    for clip in source_edl:
        clip_start = int(clip.get("source_start_us") or 0)
        clip_end = int(clip.get("source_end_us") or 0)
        overlap_start = max(source_start, clip_start)
        overlap_end = min(source_end, clip_end)
        if overlap_end <= overlap_start:
            continue
        cloned = deepcopy(clip)
        cloned["clip_id"] = f"{clip.get('clip_id')}_semtrim"
        cloned["parent_clip_id"] = clip.get("clip_id")
        cloned["source_start_us"] = overlap_start
        cloned["source_end_us"] = overlap_end
        cloned["source_timeline_start_us"] = overlap_start
        cloned["source_timeline_end_us"] = overlap_end
        cloned["cut_start_us"] = overlap_start
        cloned["cut_end_us"] = overlap_end
        cloned["target_duration_us"] = overlap_end - overlap_start
        cloned["final_target_duration_us"] = overlap_end - overlap_start
        cloned["material_start_us"] = None
        cloned["material_end_us"] = None
        cloned["source_reason"] = reason
        pieces.append(cloned)
    return pieces


def rebase_edl_by_source_order(edl: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rebased = sorted(edl, key=lambda clip: (int(clip.get("source_start_us") or 0), int(clip.get("source_end_us") or 0)))
    target_start = 0
    for clip in rebased:
        duration = int(clip.get("source_end_us") or 0) - int(clip.get("source_start_us") or 0)
        if duration <= 0:
            continue
        clip["target_start_us"] = target_start
        clip["target_duration_us"] = duration
        clip["final_target_start_us"] = target_start
        clip["final_target_duration_us"] = duration
        clip["final_target_end_us"] = target_start + duration
        clip["source_timeline_start_us"] = int(clip.get("source_start_us") or 0)
        clip["source_timeline_end_us"] = int(clip.get("source_end_us") or 0)
        target_start += duration
    return [clip for clip in rebased if int(clip.get("target_duration_us") or 0) > 0]


def apply_semantic_overlap_trim(
    phase4d3_edl: list[dict[str, Any]],
    phase4d3_subtitles: list[dict[str, Any]],
    phase4d3_fix_plan: dict[str, Any],
    phase4d3_before_audit: dict[str, Any],
    source_edl: list[dict[str, Any]],
    source_subtitles: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    restored_clips: list[dict[str, Any]] = []
    added_subtitles: list[dict[str, Any]] = []
    issue_rows: list[dict[str, Any]] = []
    prevented = 0
    partial_trim = 0
    manual_review: list[dict[str, Any]] = []
    dropped_ids = {str(item) for item in phase4d3_fix_plan.get("subtitle_drops") or []}

    for issue in phase4d3_before_audit.get("issues") or []:
        if issue.get("recommended_action") != "drop_left" or issue.get("confidence") != "high":
            continue
        subtitle_ids = [str(item) for item in (issue.get("involved_subtitle_ids") or [])]
        left_id = subtitle_ids[0] if subtitle_ids else ""
        if left_id not in dropped_ids:
            continue
        left_source = next((row for row in source_subtitles if str(row.get("fragment_id") or "") == left_id), None)
        if not left_source:
            manual_review.append(issue | {"manual_reason": "left source subtitle not found"})
            continue
        shared_phrase = str(issue.get("overlap_text") or "")
        if norm_text(str(issue.get("left_text") or "")) == norm_text(shared_phrase):
            issue_rows.append(
                {
                    "issue_id": issue.get("issue_id"),
                    "left_text": issue.get("left_text"),
                    "right_text": issue.get("right_text"),
                    "shared_phrase": shared_phrase,
                    "left_unique_prefix": "",
                    "old_action_would_be": "drop_left",
                    "new_action": "drop_left",
                    "reason": "left text is only the duplicated shared phrase",
                }
            )
            continue
        indices = [int(item) for item in (left_source.get("source_subtitle_indices") or [])]
        words = words_for_subtitle_indices(word_timeline, indices)
        span = find_phrase_word_span(words, shared_phrase)
        if not span:
            manual_review.append(issue | {"manual_reason": "shared phrase word span not found"})
            continue
        prefix_words = words[: span[0]]
        prefix_text = join_words(prefix_words)
        if not meaningful_unique(prefix_text):
            issue_rows.append(
                {
                    "issue_id": issue.get("issue_id"),
                    "left_text": issue.get("left_text"),
                    "right_text": issue.get("right_text"),
                    "shared_phrase": shared_phrase,
                    "left_unique_prefix": prefix_text,
                    "old_action_would_be": "drop_left",
                    "new_action": "drop_left",
                    "reason": "left unique prefix is not meaningful",
                }
            )
            continue
        prefix_start = int(prefix_words[0]["start_us"])
        prefix_end = int(prefix_words[-1]["end_us"])
        pieces = build_clip_pieces_for_source_range(
            source_edl,
            prefix_start,
            prefix_end,
            "phase4d4_preserve_left_unique_prefix",
        )
        if not pieces:
            manual_review.append(issue | {"manual_reason": "no source clip pieces for unique prefix"})
            continue
        restored_clips.extend(pieces)
        new_subtitle = {
            "fragment_id": f"{left_id}_prefix",
            "fragment_text": prefix_text,
            "text": prefix_text,
            "source_subtitle_indices": indices,
            "source_subtitle_uids": left_source.get("source_subtitle_uids") or [],
            "source_start_us": prefix_start,
            "source_end_us": prefix_end,
            "word_ids": [word.get("word_id") for word in prefix_words],
            "reason": "phase4d4_preserve_unique_prefix",
        }
        added_subtitles.append(new_subtitle)
        prevented += 1
        partial_trim += 1
        issue_rows.append(
            {
                "issue_id": issue.get("issue_id"),
                "left_text": issue.get("left_text"),
                "right_text": issue.get("right_text"),
                "shared_phrase": shared_phrase,
                "left_unique_prefix": prefix_text,
                "left_unique_suffix": "",
                "right_unique_prefix": "",
                "right_unique_suffix": str(issue.get("right_text") or "").replace(shared_phrase, "", 1),
                "old_action_would_be": "drop_left",
                "new_action": "preserve_left_unique_prefix_drop_duplicated_shared_phrase",
                "preserved_source_start_us": prefix_start,
                "preserved_source_end_us": prefix_end,
                "dropped_duplicate_text": shared_phrase,
            }
        )

    if restored_clips:
        fixed_edl = rebase_edl_by_source_order(phase4d3_edl + restored_clips)
    else:
        fixed_edl = rebase_edl_by_source_order(phase4d3_edl)

    fixed_subtitles = []
    for row in phase4d3_subtitles + added_subtitles:
        source_start = int(row.get("source_start_us") or 0)
        source_end = int(row.get("source_end_us") or source_start)
        target_range = source_range_to_target_range(source_start, source_end, fixed_edl)
        if target_range is None:
            continue
        cloned = deepcopy(row)
        cloned["target_start_us"], target_end = target_range
        cloned["target_duration_us"] = target_end - int(cloned["target_start_us"])
        fixed_subtitles.append(cloned)
    fixed_subtitles.sort(key=lambda row: int(row.get("target_start_us") or 0))
    for idx, row in enumerate(fixed_subtitles, start=1):
        row["fragment_id"] = f"dsub_{idx:04d}"

    report = {
        "semantic_overlap_issue_count": len(issue_rows),
        "full_drop_prevented_count": prevented,
        "partial_trim_count": partial_trim,
        "manual_review_count": len(manual_review),
        "llm_arbitration_count": 0,
        "issues": issue_rows,
        "manual_review": manual_review,
        "added_subtitle_count": len(added_subtitles),
        "restored_clip_count": len(restored_clips),
    }
    return fixed_edl, fixed_subtitles, report


def semantic_overlap_regression(report: dict[str, Any], subtitle_plan: list[dict[str, Any]]) -> dict[str, Any]:
    target = next(
        (row for row in report.get("issues") or [] if "精分" in str(row.get("left_text") or "") and "数字游民" in str(row.get("right_text") or "")),
        None,
    )
    texts = [str(row.get("fragment_text") or row.get("text") or "") for row in subtitle_plan]
    return {
        "detected": bool(target),
        "old_action_would_be": (target or {}).get("old_action_would_be", ""),
        "new_action": (target or {}).get("new_action", ""),
        "preserved_unique_text": (target or {}).get("left_unique_prefix", ""),
        "dropped_duplicate_text": (target or {}).get("dropped_duplicate_text", ""),
        "final_text_sequence": texts,
        "risk": "low" if target and (target or {}).get("left_unique_prefix") and any("数字游民" in text for text in texts) else "review",
    }
