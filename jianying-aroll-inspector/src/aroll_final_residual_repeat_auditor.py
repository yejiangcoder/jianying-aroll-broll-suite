from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any


WEAK_PREFIX_WORDS = {"的", "呃", "嗯", "啊", "就"}
WEAK_INTRO_SUFFIXES = ("有这么", "这么", "发现有这么")
WEAK_LEADING_TEXT = ("这", "这个", "那", "那个", "就", "就是", "所以", "然后")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def norm_text(text: str) -> str:
    text = str(text or "")
    text = re.sub(r"[\s,，。.!！?？、:：;；\"'“”‘’（）()【】\[\]《》<>-]+", "", text)
    for src in ("她们", "它们", "他们们"):
        text = text.replace(src, "他们")
    text = re.sub(r"(.)\1{2,}", r"\1\1", text)
    return text


def words_by_id(word_timeline: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("word_id") or ""): row for row in word_timeline}


def words_by_subtitle_index(word_timeline: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for word in word_timeline:
        out.setdefault(int(word.get("subtitle_index") or -1), []).append(word)
    for rows in out.values():
        rows.sort(key=lambda row: (int(row.get("start_us") or 0), int(row.get("end_us") or 0)))
    return out


def join_words(words: list[dict[str, Any]]) -> str:
    return "".join(str(word.get("word_text") or "") for word in words)


def trim_weak_prefix(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = list(words)
    while rows and str(rows[0].get("word_text") or "") in WEAK_PREFIX_WORDS:
        rows.pop(0)
    return rows


def longest_suffix_prefix_overlap(left: str, right: str) -> str:
    left_n = norm_text(left)
    right_n = norm_text(right)
    best = ""
    max_len = min(len(left_n), len(right_n))
    for size in range(2, max_len + 1):
        if left_n[-size:] == right_n[:size]:
            best = left_n[-size:]
    return best


def lcs_ratio(left: str, right: str) -> float:
    left_n = norm_text(left)
    right_n = norm_text(right)
    if not left_n or not right_n:
        return 0.0
    return difflib.SequenceMatcher(None, left_n, right_n).ratio()


def lcs_match_len(left: str, right: str) -> int:
    if not left or not right:
        return 0
    matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
    return sum(block.size for block in matcher.get_matching_blocks())


def strip_weak_leading_text(text: str) -> str:
    out = norm_text(text)
    changed = True
    while changed:
        changed = False
        for prefix in WEAK_LEADING_TEXT:
            if out.startswith(prefix) and len(out) > len(prefix) + 4:
                out = out[len(prefix):]
                changed = True
                break
    return out


def containment_coverage(short_text: str, long_text: str) -> float:
    short_n = strip_weak_leading_text(short_text)
    long_n = strip_weak_leading_text(long_text)
    if len(short_n) < 7 or len(long_n) < len(short_n):
        return 0.0
    if short_n in long_n:
        return 1.0
    return lcs_match_len(short_n, long_n) / max(1, len(short_n))


def _group_words(group: dict[str, Any], by_word: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    words = [by_word[str(word_id)] for word_id in (group.get("word_ids") or []) if str(word_id) in by_word]
    return sorted(words, key=lambda row: (int(row.get("start_us") or 0), int(row.get("end_us") or 0)))


def _restart_prefix_split(words: list[dict[str, Any]]) -> int:
    max_split = min(4, len(words) - 1)
    for split in range(max_split, 0, -1):
        left_text = join_words(words[:split])
        right_text = join_words(words[split : min(len(words), split + max(4, split + 1))])
        left_n = norm_text(left_text)
        right_n = norm_text(right_text)
        if len(left_n) < 2 or len(left_n) > 6 or len(right_n) < len(left_n):
            continue
        if not right_n.startswith(left_n[:1]):
            continue
        coverage = lcs_match_len(left_n, right_n[: max(6, len(left_n) + 3)]) / len(left_n)
        common_chars = len(set(left_n) & set(right_n))
        if coverage >= 0.72 and common_chars >= 2:
            return split
    return 0


def _target_range_for_issue(groups: list[dict[str, Any]]) -> tuple[int, int]:
    starts = [int(row.get("target_start_us") or 0) for row in groups]
    ends = [int(row.get("target_start_us") or 0) + int(row.get("target_duration_us") or 0) for row in groups]
    return (min(starts) if starts else 0, max(ends) if ends else 0)


def detect_intra_subtitle_restart_repeats(
    display_plan: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_word = words_by_id(word_timeline)
    issues: list[dict[str, Any]] = []
    for group in display_plan:
        words = _group_words(group, by_word)
        if len(words) < 3:
            continue
        split = _restart_prefix_split(words)
        if split <= 0:
            continue
        removed_words = words[:split]
        kept_words = words[split:]
        removed_text = join_words(removed_words)
        kept_text = join_words(kept_words)
        if not removed_text or not kept_text:
            continue
        remove_start = int(removed_words[0]["start_us"])
        remove_end = int(kept_words[0]["start_us"])
        if remove_end <= remove_start or remove_end - remove_start > 900_000:
            continue
        source_indices = sorted({int(word.get("subtitle_index") or -1) for word in kept_words if int(word.get("subtitle_index") or -1) >= 0})
        target_start, target_end = _target_range_for_issue([group])
        issues.append(
            {
                "issue_id": f"fr_restart_{len(issues) + 1:03d}",
                "issue_type": "intra_subtitle_restart",
                "target_start_us": target_start,
                "target_end_us": target_end,
                "source_start_us": remove_start,
                "source_end_us": remove_end,
                "left_text": removed_text,
                "right_text": kept_text,
                "involved_clip_ids": [],
                "involved_subtitle_ids": [group.get("fragment_id")],
                "confidence": "high",
                "deterministic_safe": True,
                "requires_llm": False,
                "risk_level": "low",
                "recommended_action": "remove_hidden_first_audio_island",
                "reason": "same subtitle starts with a short aborted phrase and immediately restarts with a similar phrase",
                "replacement_subtitle": {
                    "fragment_id": group.get("fragment_id"),
                    "fragment_text": kept_text,
                    "text": kept_text,
                    "source_subtitle_indices": source_indices,
                    "source_subtitle_uids": [f"sub_{idx:06d}" for idx in source_indices],
                    "source_start_us": int(kept_words[0]["start_us"]),
                    "source_end_us": int(kept_words[-1]["end_us"]),
                    "word_ids": [word.get("word_id") for word in kept_words],
                },
            }
        )
    return issues


def detect_multi_source_hidden_repeats(
    display_plan: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_word = words_by_id(word_timeline)
    by_sub = words_by_subtitle_index(word_timeline)
    issues: list[dict[str, Any]] = []
    for group in display_plan:
        indices = [int(item) for item in (group.get("source_subtitle_indices") or [])]
        if len(indices) < 2:
            continue
        group_words = [by_word[str(word_id)] for word_id in (group.get("word_ids") or []) if str(word_id) in by_word]
        if not group_words:
            continue
        first_index = indices[0]
        later_index = indices[-1]
        early_words = [word for word in group_words if int(word.get("subtitle_index") or -1) == first_index]
        later_all = by_sub.get(later_index) or []
        later_trimmed = trim_weak_prefix(later_all)
        early_text = join_words(early_words)
        later_text = join_words(later_trimmed)
        if not early_text or not later_text:
            continue
        early_n = norm_text(early_text)
        later_n = norm_text(later_text)
        if not later_n.startswith(early_n) and lcs_ratio(early_text, later_text[: len(early_text) + 3]) < 0.82:
            continue
        remove_start = min(int(word["start_us"]) for word in early_words)
        remove_end = int(later_trimmed[0]["start_us"]) if later_trimmed else max(int(word["end_us"]) for word in early_words)
        target_start, target_end = _target_range_for_issue([group])
        issues.append(
            {
                "issue_id": f"fr_{len(issues) + 1:03d}",
                "issue_type": "word_timeline_hidden_repeat",
                "target_start_us": target_start,
                "target_end_us": target_end,
                "source_start_us": remove_start,
                "source_end_us": remove_end,
                "left_text": early_text,
                "right_text": later_text,
                "involved_clip_ids": [],
                "involved_subtitle_ids": [group.get("fragment_id")],
                "confidence": "high",
                "deterministic_safe": True,
                "requires_llm": False,
                "risk_level": "low",
                "recommended_action": "remove_hidden_first_audio_island",
                "reason": "display subtitle merges words from multiple source subtitle groups; earlier phrase repeats at start of later group",
                "replacement_subtitle": {
                    "fragment_id": group.get("fragment_id"),
                    "fragment_text": later_text,
                    "text": later_text,
                    "source_subtitle_indices": [later_index],
                    "source_subtitle_uids": [f"sub_{later_index:06d}"],
                    "source_start_us": int(later_trimmed[0]["start_us"]),
                    "source_end_us": int(later_trimmed[-1]["end_us"]),
                    "word_ids": [word.get("word_id") for word in later_trimmed],
                },
            }
        )
    return issues


def detect_adjacent_text_repeats(display_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for left, right in zip(display_plan, display_plan[1:]):
        left_text = str(left.get("fragment_text") or left.get("text") or "")
        right_text = str(right.get("fragment_text") or right.get("text") or "")
        left_n = norm_text(left_text)
        right_n = norm_text(right_text)
        if not left_n or not right_n:
            continue
        overlap = longest_suffix_prefix_overlap(left_text, right_text)
        ratio = lcs_ratio(left_text, right_text)
        action = ""
        confidence = "low"
        reason = ""
        deterministic_safe = False
        requires_llm = False
        risk_level = "medium"
        if left_n == right_n or ratio >= 0.94:
            action = "drop_left"
            confidence = "high"
            deterministic_safe = True
            risk_level = "low"
            reason = "adjacent final subtitles are exact or near duplicate"
        elif ratio >= 0.90:
            action = "drop_left"
            confidence = "high"
            requires_llm = True
            risk_level = "high"
            reason = "adjacent final subtitles are near duplicate but require semantic confirmation"
        elif len(left_n) <= len(right_n) and containment_coverage(left_text, right_text) >= 0.86:
            action = "drop_left"
            confidence = "high"
            requires_llm = True
            risk_level = "high"
            reason = "left subtitle is semantically contained in the following fuller restart"
        elif len(overlap) >= 4:
            left_remainder = left_n[: -len(overlap)]
            if left_remainder.endswith(WEAK_INTRO_SUFFIXES) or len(left_remainder) <= 6:
                action = "drop_left"
                confidence = "high"
                deterministic_safe = len(left_remainder) <= 3
                requires_llm = not deterministic_safe
                risk_level = "low" if deterministic_safe else "high"
                reason = "left subtitle is a weak intro ending with the same phrase that starts the next subtitle"
            else:
                action = "trim_left_phrase"
                confidence = "medium"
                requires_llm = True
                risk_level = "high"
                reason = "adjacent final subtitles have suffix/prefix overlap but left side may contain independent meaning"
        if not action:
            continue
        target_start, target_end = _target_range_for_issue([left, right])
        issues.append(
            {
                "issue_id": f"fr_text_{len(issues) + 1:03d}",
                "issue_type": "semantic_containment_repeat" if "contained" in reason else ("prefix_overlap" if overlap else "near_repeat"),
                "target_start_us": target_start,
                "target_end_us": target_end,
                "source_start_us": int(left.get("source_start_us") or 0),
                "source_end_us": int(left.get("source_end_us") or 0),
                "left_source_start_us": int(left.get("source_start_us") or 0),
                "left_source_end_us": int(left.get("source_end_us") or 0),
                "right_source_start_us": int(right.get("source_start_us") or 0),
                "right_source_end_us": int(right.get("source_end_us") or 0),
                "left_text": left_text,
                "right_text": right_text,
                "overlap_text": overlap,
                "similarity": round(ratio, 4),
                "involved_clip_ids": [],
                "involved_subtitle_ids": [left.get("fragment_id"), right.get("fragment_id")],
                "confidence": confidence,
                "deterministic_safe": deterministic_safe,
                "requires_llm": requires_llm,
                "risk_level": risk_level,
                "recommended_action": action,
                "reason": reason,
            }
        )
    return issues


def audit_final_residual_repeats(
    final_edl: list[dict[str, Any]],
    display_plan: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    issues = []
    issues.extend(detect_multi_source_hidden_repeats(display_plan, word_timeline))
    issues.extend(detect_intra_subtitle_restart_repeats(display_plan, word_timeline))
    issues.extend(detect_adjacent_text_repeats(display_plan))
    for idx, issue in enumerate(issues, start=1):
        issue["issue_id"] = f"fr_{idx:03d}"
        src_start = int(issue.get("source_start_us") or 0)
        src_end = int(issue.get("source_end_us") or 0)
        issue["involved_clip_ids"] = [
            str(clip.get("clip_id") or "")
            for clip in final_edl
            if int(clip.get("source_end_us") or 0) > src_start and int(clip.get("source_start_us") or 0) < src_end
        ]
    text_repeat_count = sum(
        1
        for row in issues
        if row["issue_type"] in {"exact_repeat", "near_repeat", "prefix_overlap", "suffix_overlap", "same_phrase_repeated", "semantic_containment_repeat", "intra_subtitle_restart"}
        and row["confidence"] == "high"
        and (row.get("deterministic_safe") is True or row.get("requires_llm") is False)
    )
    hidden_count = sum(1 for row in issues if row["issue_type"] in {"word_timeline_hidden_repeat", "hidden_audio_repeat"} and row["confidence"] == "high")
    return {
        "issue_count": len(issues),
        "high_confidence_text_repeat_count": text_repeat_count,
        "high_confidence_hidden_audio_repeat_count": hidden_count,
        "high_confidence_word_timeline_hidden_repeat_count": hidden_count,
        "audio_only_repeat_detection_enabled": False,
        "hidden_repeat_detection_basis": "text_word_timeline",
        "deterministic_safe_issue_count": sum(1 for row in issues if row.get("deterministic_safe") is True),
        "requires_llm_issue_count": sum(1 for row in issues if row.get("requires_llm") is True),
        "issues": issues,
    }
