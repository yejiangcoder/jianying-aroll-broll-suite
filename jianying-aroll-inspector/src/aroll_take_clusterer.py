from __future__ import annotations

import difflib
import re
from typing import Any


def norm_text(text: str) -> str:
    out = re.sub(r"[\s,，。.!！?？、:：;；\"'“”‘’（）()【】\[\]《》<>-]+", "", str(text or ""))
    return out.replace("她们", "他们").replace("它们", "他们")


def _ratio(left: str, right: str) -> float:
    left_n = norm_text(left)
    right_n = norm_text(right)
    if not left_n or not right_n:
        return 0.0
    return difflib.SequenceMatcher(None, left_n, right_n, autojunk=False).ratio()


def _containment(left: str, right: str) -> float:
    left_n = norm_text(left)
    right_n = norm_text(right)
    if len(left_n) < 4 or len(right_n) < 4:
        return 0.0
    short, long = (left_n, right_n) if len(left_n) <= len(right_n) else (right_n, left_n)
    if short in long:
        return 1.0
    matcher = difflib.SequenceMatcher(None, short, long, autojunk=False)
    return sum(block.size for block in matcher.get_matching_blocks()) / max(1, len(short))


def _words_by_subtitle(word_timeline: list[dict[str, Any]] | None) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for word in word_timeline or []:
        grouped.setdefault(int(word.get("subtitle_index") or -1), []).append(word)
    for rows in grouped.values():
        rows.sort(key=lambda row: (int(row.get("start_us") or 0), int(row.get("end_us") or 0)))
    return grouped


def _audio_quality_hint(words: list[dict[str, Any]]) -> str:
    if not words:
        return "unknown"
    durations = [int(row.get("end_us") or 0) - int(row.get("start_us") or 0) for row in words]
    if any(duration <= 40_000 for duration in durations):
        return "has_tiny_word"
    gaps = [
        int(right.get("start_us") or 0) - int(left.get("end_us") or 0)
        for left, right in zip(words, words[1:])
    ]
    if any(gap >= 450_000 for gap in gaps):
        return "has_long_internal_gap"
    return "normal"


def _candidate_for(row: dict[str, Any], words: list[dict[str, Any]]) -> dict[str, Any]:
    text = str(row.get("subtitle_text") or "")
    norm = norm_text(text)
    word_text = "".join(str(word.get("word_text") or "") for word in words)
    completeness = min(1.0, len(norm_text(word_text) or norm) / max(1, len(norm)))
    is_aborted = len(norm) <= 6 or completeness < 0.72
    return {
        "take_id": f"take_sub_{int(row.get('subtitle_index') or 0):06d}",
        "subtitle_indices": [row.get("subtitle_index")],
        "subtitle_uids": [row.get("subtitle_uid")],
        "text": text,
        "norm_text": norm,
        "source_start_us": row.get("start_us"),
        "source_end_us": row.get("end_us"),
        "completeness_score": round(completeness, 4),
        "audio_quality_hint": _audio_quality_hint(words),
        "is_aborted_start": is_aborted,
    }


def build_take_clusters(
    subtitles: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]] | None = None,
    *,
    window: int = 4,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pair_rows: list[dict[str, Any]] = []
    sorted_subs = sorted(subtitles, key=lambda row: int(row.get("start_us") or 0))
    for i, left in enumerate(sorted_subs):
        for right in sorted_subs[i + 1 : i + 1 + window]:
            left_text = str(left.get("subtitle_text") or "")
            right_text = str(right.get("subtitle_text") or "")
            left_n = norm_text(left_text)
            right_n = norm_text(right_text)
            if len(left_n) < 4 or len(right_n) < 4:
                continue
            ratio = _ratio(left_text, right_text)
            containment = _containment(left_text, right_text)
            cluster_type = ""
            confidence = "low"
            if left_n == right_n or ratio >= 0.92:
                cluster_type = "near_duplicate_take"
                confidence = "high"
            elif containment >= 0.88:
                cluster_type = "semantic_containment_take"
                confidence = "medium"
            elif right_n.startswith(left_n[: max(2, min(5, len(left_n)))]) and ratio >= 0.68:
                cluster_type = "restart_take"
                confidence = "medium"
            if not cluster_type:
                continue
            pair_rows.append(
                {
                    "cluster_type": cluster_type,
                    "confidence": confidence,
                    "similarity": round(ratio, 4),
                    "containment": round(containment, 4),
                    "left": left,
                    "right": right,
                    "recommended_drop_index": left.get("subtitle_index") if confidence == "high" else None,
                    "requires_llm": confidence != "high",
                }
            )
    by_index = {int(row.get("subtitle_index") or 0): row for row in sorted_subs}
    word_by_sub = _words_by_subtitle(word_timeline)
    groups: list[set[int]] = []
    metadata: list[list[dict[str, Any]]] = []
    for pair in pair_rows:
        pair_indices = {
            int(pair["left"].get("subtitle_index") or 0),
            int(pair["right"].get("subtitle_index") or 0),
        }
        attached = -1
        for idx, group in enumerate(groups):
            if group & pair_indices:
                attached = idx
                break
        if attached >= 0:
            groups[attached] |= pair_indices
            metadata[attached].append(pair)
        else:
            groups.append(set(pair_indices))
            metadata.append([pair])

    clusters: list[dict[str, Any]] = []
    for group, pairs in zip(groups, metadata):
        ordered = [by_index[idx] for idx in sorted(group) if idx in by_index]
        if len(ordered) < 2:
            continue
        candidates = [
            _candidate_for(row, word_by_sub.get(int(row.get("subtitle_index") or 0), []))
            for row in ordered[:5]
        ]
        confidence = "high" if all(str(pair.get("confidence")) == "high" for pair in pairs) else "medium"
        cluster_types = sorted({str(pair.get("cluster_type") or "unknown") for pair in pairs})
        recommended_drop = None
        if confidence == "high":
            aborted = [candidate for candidate in candidates if candidate.get("is_aborted_start")]
            if aborted:
                recommended_drop = int((aborted[0].get("subtitle_indices") or [0])[0] or 0)
            else:
                recommended_drop = int((candidates[0].get("subtitle_indices") or [0])[0] or 0)
        clusters.append(
            {
                "cluster_id": f"tc_{len(clusters) + 1:04d}",
                "cluster_type": cluster_types[0] if len(cluster_types) == 1 else "multi_take_cluster",
                "cluster_types": cluster_types,
                "confidence": confidence,
                "candidate_count": len(candidates),
                "candidates": candidates,
                "items": [
                    {
                        "subtitle_index": row.get("subtitle_index"),
                        "subtitle_uid": row.get("subtitle_uid"),
                        "text": row.get("subtitle_text"),
                        "start_us": row.get("start_us"),
                        "end_us": row.get("end_us"),
                    }
                    for row in ordered
                ],
                "recommended_drop_index": recommended_drop,
                "requires_llm": confidence != "high" or len(candidates) > 2,
                "pairwise_evidence": [
                    {
                        "left_index": pair["left"].get("subtitle_index"),
                        "right_index": pair["right"].get("subtitle_index"),
                        "similarity": pair.get("similarity"),
                        "containment": pair.get("containment"),
                        "cluster_type": pair.get("cluster_type"),
                    }
                    for pair in pairs
                ],
            }
        )
    report = {
        "take_cluster_count": len(clusters),
        "word_timing_available": bool(word_timeline),
        "cluster_schema": "cluster_level_v1",
        "cluster_type_counts": {},
    }
    for row in clusters:
        ctype = str(row.get("cluster_type") or "unknown")
        report["cluster_type_counts"][ctype] = int(report["cluster_type_counts"].get(ctype) or 0) + 1
    return clusters, report


def take_clusters_to_repeat_detector_rows(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cluster in clusters:
        candidates = cluster.get("candidates") or []
        window_indices = sorted(
            {
                int(index)
                for candidate in candidates
                for index in (candidate.get("subtitle_indices") or [])
                if int(index) > 0
            }
        )
        items = cluster.get("items") or []
        suggested_drop_indices = [int(cluster.get("recommended_drop_index") or 0)] if int(cluster.get("recommended_drop_index") or 0) > 0 else []
        suggested_drop_uids = [
            str(item.get("subtitle_uid") or "")
            for item in items
            if int(item.get("subtitle_index") or 0) in suggested_drop_indices and str(item.get("subtitle_uid") or "")
        ]
        keep_candidates = [
            candidate
            for candidate in candidates
            if int((candidate.get("subtitle_indices") or [0])[0] or 0) not in suggested_drop_indices
        ]
        keep_uid = ""
        if keep_candidates:
            keep_uid = str((keep_candidates[-1].get("subtitle_uids") or [""])[0] or "")
        elif items:
            keep_uid = str(items[-1].get("subtitle_uid") or "")
        suggested_action = "codex_self_review_required"
        if len(window_indices) == 2 and suggested_drop_indices:
            if suggested_drop_indices[0] == window_indices[0]:
                suggested_action = "drop_left"
            elif suggested_drop_indices[0] == window_indices[-1]:
                suggested_action = "drop_right"
        rows.append(
            {
                "cluster_id": cluster.get("cluster_id"),
                "cluster_type": cluster.get("cluster_type"),
                "confidence": cluster.get("confidence"),
                "items": items,
                "window_indices": window_indices,
                "candidates": candidates,
                "candidate_count": len(candidates),
                "suggested_action": suggested_action,
                "suggested_keep_uid": keep_uid,
                "suggested_drop_uids": suggested_drop_uids,
                "recommended_drop_index": cluster.get("recommended_drop_index"),
                "requires_llm": cluster.get("requires_llm"),
                "source": "take_clusterer",
            }
        )
    return rows
