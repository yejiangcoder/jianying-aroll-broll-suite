from __future__ import annotations

from typing import Any

from aroll_text_normalize import (
    char_ngrams,
    compact_text,
    jaccard,
    lcs_ratio,
    normalize_text,
    protected_atoms_in,
    repeated_phrase_spans,
    similarity,
)


CN_NUMERAL_EQUIV = {
    "零": "0",
    "一": "1",
    "二": "2",
    "两": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
}

RESTART_PREFIX_MIN_LEN = 2


def item_for(row: dict[str, Any]) -> dict[str, Any]:
    text = str(row.get("subtitle_text") or "")
    return {
        "subtitle_uid": row.get("subtitle_uid"),
        "subtitle_index": int(row.get("subtitle_index") or 0),
        "text": text,
        "norm_text": normalize_text(text),
        "start_us": int(row.get("start_us") or 0),
        "end_us": int(row.get("end_us") or 0),
    }


def cluster(
    cluster_id: str,
    cluster_type: str,
    rows: list[dict[str, Any]],
    sim: dict[str, Any] | None,
    suggested_action: str,
    suggested_keep_uid: str,
    suggested_drop_uids: list[str],
    reason: str,
    confidence: str,
) -> dict[str, Any]:
    return {
        "cluster_id": cluster_id,
        "cluster_type": cluster_type,
        "window_indices": [int(row.get("subtitle_index") or 0) for row in rows],
        "items": [item_for(row) for row in rows],
        "similarity": sim or {"lcs_ratio": 0.0, "jaccard": 0.0, "edit_ratio": 0.0},
        "suggested_action": suggested_action,
        "suggested_keep_uid": suggested_keep_uid,
        "suggested_drop_uids": suggested_drop_uids,
        "reason": reason,
        "confidence": confidence,
    }


def repeat_norm(text: str) -> str:
    out = normalize_text(text, pronouns=True, weak=True, stutter=False)
    for cn, digit in CN_NUMERAL_EQUIV.items():
        out = out.replace(cn + "分", digit + "分")
        out = out.replace(cn + "万", digit + "万")
        out = out.replace(cn + "秒", digit + "秒")
        out = out.replace(cn + "块", digit + "块")
    return out


def longest_common_substring(a: str, b: str) -> str:
    best = ""
    for start in range(len(a)):
        for end in range(start + 1, len(a) + 1):
            piece = a[start:end]
            if len(piece) <= len(best):
                continue
            if piece in b:
                best = piece
    return best


def is_dangling_fragment(norm: str) -> bool:
    if not norm:
        return False
    if len(norm) <= 12 and norm[-1:] in {"被", "把", "向", "对", "在", "就", "的"}:
        return True
    return False


def repeated_prefix_cleanup_text(text: str) -> str:
    norm = compact_text(text)
    if len(norm) < 4:
        return ""
    repeats = repeated_phrase_spans(text)
    if repeats:
        strongest = max(repeats, key=lambda item: (int(item["phrase_len"]), str(item["phrase"])))
        start = int(strongest["start_char"])
        size = int(strongest["phrase_len"])
        if size > 0:
            return norm[: start + size] + norm[start + (2 * size) :]
    for size in range(min(8, len(norm) // 2), RESTART_PREFIX_MIN_LEN - 1, -1):
        prefix = norm[:size]
        if norm.endswith(prefix) and len(norm) > size * 2:
            return prefix
    return ""


def boundary_overlap_cleanup(left_text: str, right_text: str) -> tuple[str, str]:
    left_norm = compact_text(left_text)
    right_norm = compact_text(right_text)
    max_len = min(8, len(left_norm), len(right_norm))
    for size in range(max_len, 1, -1):
        overlap = left_norm[-size:]
        if right_norm.startswith(overlap):
            cleaned = left_norm[:-size]
            if len(cleaned) >= 4:
                return cleaned, overlap
    return "", ""


def pair_overlap_score(left_text: str, right_text: str) -> dict[str, float]:
    left = repeat_norm(left_text)
    right = repeat_norm(right_text)
    lcs = lcs_ratio(left, right)
    jac = jaccard(char_ngrams(left, 2), char_ngrams(right, 2))
    longest = longest_common_substring(left, right)
    containment_ratio = len(longest) / max(1, min(len(left), len(right)))
    return {
        "lcs_ratio": round(lcs, 4),
        "jaccard": round(jac, 4),
        "longest_common_substring_ratio": round(containment_ratio, 4),
    }


def same_subtitle_clusters(rows: list[dict[str, Any]], start_id: int = 1) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cid = start_id
    for row in rows:
        text = str(row.get("subtitle_text") or "")
        cleanup = repeated_prefix_cleanup_text(text)
        repeats = repeated_phrase_spans(str(row.get("subtitle_text") or ""))
        if repeats:
            strongest = max(repeats, key=lambda item: (int(item["phrase_len"]), str(item["phrase"])))
            out.append(
                cluster(
                    f"rc_{cid:06d}",
                    "same_subtitle_repeated_phrase",
                    [row],
                    None,
                    "micro_cleanup",
                    str(row.get("subtitle_uid") or ""),
                    [],
                    f"same subtitle repeated phrase: {strongest['phrase']}",
                    "high" if int(strongest["phrase_len"]) >= 2 else "medium",
                )
            )
            out[-1]["repeat_phrases"] = repeats
            if cleanup and cleanup != compact_text(text):
                out[-1]["micro_cleanup_text"] = cleanup
            cid += 1
            continue
        if cleanup and cleanup != compact_text(text):
            out.append(
                cluster(
                    f"rc_{cid:06d}",
                    "same_subtitle_restart_fragment",
                    [row],
                    None,
                    "micro_cleanup",
                    str(row.get("subtitle_uid") or ""),
                    [],
                    "same subtitle restarts from an earlier phrase",
                    "high",
                )
            )
            out[-1]["micro_cleanup_text"] = cleanup
            cid += 1
    return out


def classify_pair(left: dict[str, Any], right: dict[str, Any]) -> tuple[str, str, str, list[str], str] | None:
    left_text = str(left.get("subtitle_text") or "")
    right_text = str(right.get("subtitle_text") or "")
    left_raw_norm = normalize_text(left_text, pronouns=False)
    right_raw_norm = normalize_text(right_text, pronouns=False)
    left_norm = normalize_text(left_text)
    right_norm = normalize_text(right_text)
    left_repeat = repeat_norm(left_text)
    right_repeat = repeat_norm(right_text)
    left_pron = normalize_text(left_text, pronouns=True, weak=True, stutter=True)
    right_pron = normalize_text(right_text, pronouns=True, weak=True, stutter=True)
    sim = similarity(left_text, right_text)

    if left_raw_norm and left_raw_norm == right_raw_norm:
        return "exact_duplicate", "drop_left", str(right.get("subtitle_uid") or ""), [str(left.get("subtitle_uid") or "")], "normalized text is exactly duplicated"

    if left_pron and left_pron == right_pron and left_raw_norm != right_raw_norm:
        return "pronoun_variant_duplicate", "drop_left", str(right.get("subtitle_uid") or ""), [str(left.get("subtitle_uid") or "")], "pronoun-normalized text matches"

    left_cleanup, overlap = boundary_overlap_cleanup(left_text, right_text)
    if left_cleanup:
        return "boundary_overlap_cleanup", "micro_cleanup_left", str(left.get("subtitle_uid") or ""), [], f"left subtitle repeats next boundary prefix: {overlap}"

    if left_repeat and right_repeat and right_repeat.startswith(left_repeat) and len(right_repeat) >= len(left_repeat) + 2:
        if is_dangling_fragment(right_repeat):
            return "dirty_expanded_fragment", "drop_right", str(left.get("subtitle_uid") or ""), [str(right.get("subtitle_uid") or "")], "right subtitle expands left but ends as an unfinished restart"
        return "prefix_fragment", "drop_left", str(right.get("subtitle_uid") or ""), [str(left.get("subtitle_uid") or "")], "left subtitle is a prefix fragment of the right subtitle"

    if left_repeat and right_repeat and left_repeat.startswith(right_repeat) and len(left_repeat) >= len(right_repeat) + 2:
        if is_dangling_fragment(left_repeat):
            return "dirty_expanded_fragment", "drop_left", str(right.get("subtitle_uid") or ""), [str(left.get("subtitle_uid") or "")], "left subtitle expands right but ends as an unfinished restart"
        return "prefix_fragment", "drop_right", str(left.get("subtitle_uid") or ""), [str(right.get("subtitle_uid") or "")], "right subtitle is a prefix fragment of the left subtitle"

    if sim["lcs_ratio"] >= 0.82 or sim["edit_ratio"] >= 0.82 or sim["jaccard"] >= 0.70:
        return "near_duplicate", "drop_left", str(right.get("subtitle_uid") or ""), [str(left.get("subtitle_uid") or "")], "high character-level similarity"

    if sim["substring_containment"] and min(len(left_norm), len(right_norm)) >= 4:
        return "weak_prefix_fragment", "drop_left" if len(left_norm) < len(right_norm) else "drop_right", str((right if len(left_norm) < len(right_norm) else left).get("subtitle_uid") or ""), [str((left if len(left_norm) < len(right_norm) else right).get("subtitle_uid") or "")], "one normalized text contains the other"

    overlap_score = pair_overlap_score(left_text, right_text)
    shared = longest_common_substring(left_repeat, right_repeat)
    if (
        len(shared) >= (3 if is_dangling_fragment(left_repeat) else 4)
        and (overlap_score["longest_common_substring_ratio"] >= 0.65 or is_dangling_fragment(left_repeat))
        and (is_dangling_fragment(left_repeat) or len(left_repeat) + 4 <= len(right_repeat))
    ):
        return "dirty_prefix_fragment", "drop_left", str(right.get("subtitle_uid") or ""), [str(left.get("subtitle_uid") or "")], "left is a damaged fragment before a cleaner nearby take"
    if (
        len(shared) >= (3 if is_dangling_fragment(right_repeat) else 4)
        and (overlap_score["longest_common_substring_ratio"] >= 0.65 or is_dangling_fragment(right_repeat))
        and (is_dangling_fragment(right_repeat) or len(right_repeat) + 4 <= len(left_repeat))
    ):
        return "dirty_prefix_fragment", "drop_right", str(left.get("subtitle_uid") or ""), [str(right.get("subtitle_uid") or "")], "right is a damaged fragment after a cleaner nearby take"

    return None


def detect_repeat_clusters(rows: list[dict[str, Any]], window: int = 4) -> list[dict[str, Any]]:
    clusters = same_subtitle_clusters(rows, 1)
    cid = len(clusters) + 1
    seen: set[tuple[str, tuple[int, ...]]] = set()
    for i, left in enumerate(rows):
        for j in range(i + 1, min(len(rows), i + 1 + window)):
            right = rows[j]
            classified = classify_pair(left, right)
            if not classified:
                continue
            ctype, action, keep_uid, drop_uids, reason = classified
            key = (ctype, tuple([int(left.get("subtitle_index") or 0), int(right.get("subtitle_index") or 0)]))
            if key in seen:
                continue
            seen.add(key)
            sim = similarity(str(left.get("subtitle_text") or ""), str(right.get("subtitle_text") or ""))
            confidence = "high"
            if ctype in {"near_duplicate", "weak_prefix_fragment", "semantic_replacement_candidate", "dirty_prefix_fragment"}:
                confidence = "medium"
            new_cluster = cluster(f"rc_{cid:06d}", ctype, [left, right], sim, action, keep_uid, drop_uids, reason, confidence)
            if ctype == "boundary_overlap_cleanup":
                cleanup, overlap = boundary_overlap_cleanup(
                    str(left.get("subtitle_text") or ""),
                    str(right.get("subtitle_text") or ""),
                )
                new_cluster["micro_cleanup_text"] = cleanup
                new_cluster["boundary_overlap_text"] = overlap
            clusters.append(new_cluster)
            cid += 1
    return clusters


def detector_tests() -> dict[str, Any]:
    test_rows = [
        {"subtitle_uid": "t_001", "subtitle_index": 1, "subtitle_text": "你可以选择左边版本", "start_us": 0, "end_us": 1000},
        {"subtitle_uid": "t_002", "subtitle_index": 2, "subtitle_text": "你可以选择右边版本", "start_us": 1000, "end_us": 2000},
        {"subtitle_uid": "t_003", "subtitle_index": 3, "subtitle_text": "早期的时候这句话说到一半", "start_us": 2000, "end_us": 3000},
        {"subtitle_uid": "t_004", "subtitle_index": 4, "subtitle_text": "早期的时候这句话说完整了", "start_us": 3000, "end_us": 4000},
        {"subtitle_uid": "t_005", "subtitle_index": 5, "subtitle_text": "短短重复短短重复", "start_us": 4000, "end_us": 5000},
        {"subtitle_uid": "t_006", "subtitle_index": 6, "subtitle_text": "短短重复", "start_us": 5000, "end_us": 6000},
        {"subtitle_uid": "t_007", "subtitle_index": 7, "subtitle_text": "片段片段也能清理", "start_us": 6000, "end_us": 7000},
        {"subtitle_uid": "t_008", "subtitle_index": 8, "subtitle_text": "给给样例文本", "start_us": 7000, "end_us": 8000},
        {"subtitle_uid": "t_009", "subtitle_index": 9, "subtitle_text": "重新说重新说完整句", "start_us": 8000, "end_us": 9000},
    ]
    clusters = detect_repeat_clusters(test_rows, window=4)
    checks = {
        "pronoun_variant_duplicate": any(c["cluster_type"] == "pronoun_variant_duplicate" for c in clusters),
        "young_semantic_micro_cleanup": any(
            c["cluster_type"] in {"semantic_replacement_candidate", "prefix_fragment", "dirty_prefix_fragment", "boundary_overlap_cleanup"}
            and "早期" in "".join(item["text"] for item in c["items"])
            for c in clusters
        ),
        "semantic_replacement": any(c["cluster_type"] == "semantic_replacement_candidate" and "短短重复" in "".join(item["text"] for item in c["items"]) for c in clusters),
        "phrase_repeat": any(c["cluster_type"] == "same_subtitle_repeated_phrase" and "片段" in c["reason"] for c in clusters),
        "geigei_repeat": any(c["cluster_type"] == "same_subtitle_repeated_phrase" and "给" in c["reason"] for c in clusters),
        "restart_repeat": any(c["cluster_type"] == "same_subtitle_repeated_phrase" and "重新说" in c["reason"] for c in clusters),
    }
    return {
        "tests": checks,
        "passed": all(checks.values()),
        "clusters": clusters,
    }
