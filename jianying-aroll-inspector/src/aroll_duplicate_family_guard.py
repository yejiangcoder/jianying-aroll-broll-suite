from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _text_by_index(subtitles: list[dict[str, Any]]) -> dict[int, str]:
    return {
        int(row.get("subtitle_index") or 0): str(row.get("subtitle_text") or "")
        for row in subtitles
        if int(row.get("subtitle_index") or 0) > 0
    }


def _uid_index(uid: str) -> int:
    try:
        return int(str(uid).split("_")[-1])
    except Exception:
        return 0


def _exact_pairs(repeat_clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for cluster in repeat_clusters:
        if str(cluster.get("cluster_type") or "") != "exact_duplicate":
            continue
        items = cluster.get("items") or []
        if len(items) != 2:
            continue
        left = int(items[0].get("subtitle_index") or 0)
        right = int(items[1].get("subtitle_index") or 0)
        if left <= 0 or right <= left:
            continue
        pairs.append(
            {
                "cluster_id": cluster.get("cluster_id"),
                "left_index": left,
                "right_index": right,
                "offset": right - left,
                "suggested_keep_index": _uid_index(str(cluster.get("suggested_keep_uid") or "")),
                "cluster": cluster,
            }
        )
    pairs.sort(key=lambda row: (int(row["offset"]), int(row["left_index"])))
    return pairs


def detect_duplicate_families(
    subtitles: list[dict[str, Any]],
    repeat_clusters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    text_by_index = _text_by_index(subtitles)
    pairs = _exact_pairs(repeat_clusters)
    families: list[dict[str, Any]] = []
    used: set[str] = set()
    family_id = 1
    for pair in pairs:
        key = str(pair["cluster_id"])
        if key in used:
            continue
        chain = [pair]
        used.add(key)
        current_left = int(pair["left_index"])
        offset = int(pair["offset"])
        while True:
            next_pair = next(
                (
                    candidate
                    for candidate in pairs
                    if str(candidate["cluster_id"]) not in used
                    and int(candidate["offset"]) == offset
                    and int(candidate["left_index"]) == current_left + 1
                ),
                None,
            )
            if not next_pair:
                break
            chain.append(next_pair)
            used.add(str(next_pair["cluster_id"]))
            current_left = int(next_pair["left_index"])
        if len(chain) < 2:
            continue
        left_indices = [int(row["left_index"]) for row in chain]
        right_indices = [int(row["right_index"]) for row in chain]
        if left_indices != list(range(left_indices[0], left_indices[-1] + 1)):
            continue
        if right_indices != list(range(right_indices[0], right_indices[-1] + 1)):
            continue
        families.append(
            {
                "family_id": f"df_{family_id:03d}",
                "family_type": "multi_line_exact_duplicate_take",
                "cluster_ids": [row.get("cluster_id") for row in chain],
                "candidates": [
                    {
                        "take_id": f"df_{family_id:03d}_take_01",
                        "subtitle_indices": left_indices,
                        "text": " ".join(text_by_index.get(index, "") for index in left_indices).strip(),
                    },
                    {
                        "take_id": f"df_{family_id:03d}_take_02",
                        "subtitle_indices": right_indices,
                        "text": " ".join(text_by_index.get(index, "") for index in right_indices).strip(),
                    },
                ],
                "suggested_keep_indices": [
                    int(row["suggested_keep_index"])
                    for row in chain
                    if int(row.get("suggested_keep_index") or 0) > 0
                ],
            }
        )
        family_id += 1
    return families


def _choose_restore_candidate(family: dict[str, Any], drop_indices: set[int]) -> dict[str, Any]:
    candidates = family.get("candidates") or []
    suggested = {int(index) for index in family.get("suggested_keep_indices") or []}

    def score(candidate: dict[str, Any]) -> tuple[int, int, int, int]:
        indices = [int(index) for index in candidate.get("subtitle_indices") or []]
        suggested_hits = sum(1 for index in indices if index in suggested)
        dropped_count = sum(1 for index in indices if index in drop_indices)
        text_len = len(str(candidate.get("text") or ""))
        last_index = max(indices) if indices else 0
        return suggested_hits, dropped_count, text_len, last_index

    return max(candidates, key=score)


def apply_duplicate_family_guard(
    merged: dict[str, Any],
    subtitles: list[dict[str, Any]],
    repeat_clusters: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    guarded = deepcopy(merged)
    families = detect_duplicate_families(subtitles, repeat_clusters)
    drop_decisions = list(guarded.get("drop_decisions") or [])
    drop_by_index = {
        int(row.get("subtitle_index") or 0): row
        for row in drop_decisions
        if int(row.get("subtitle_index") or 0) > 0
    }
    drop_indices = set(drop_by_index)
    restorations: list[dict[str, Any]] = []
    all_dropped_before = 0
    for family in families:
        candidates = family.get("candidates") or []
        all_candidates_dropped = True
        for candidate in candidates:
            indices = [int(index) for index in candidate.get("subtitle_indices") or []]
            if not indices or not all(index in drop_indices for index in indices):
                all_candidates_dropped = False
                break
        family["all_candidates_dropped_before"] = all_candidates_dropped
        if not all_candidates_dropped:
            continue
        all_dropped_before += 1
        restore = _choose_restore_candidate(family, drop_indices)
        restored_indices = [int(index) for index in restore.get("subtitle_indices") or []]
        removed_drop_decisions = []
        for index in restored_indices:
            removed = drop_by_index.pop(index, None)
            drop_indices.discard(index)
            if removed:
                removed_drop_decisions.append(removed)
        restorations.append(
            {
                "family_id": family.get("family_id"),
                "restored_take_id": restore.get("take_id"),
                "restored_indices": restored_indices,
                "restored_text": restore.get("text"),
                "removed_drop_decisions": removed_drop_decisions,
                "reason": "restore one complete duplicate take family candidate",
            }
        )

    remaining_all_dropped = 0
    for family in families:
        candidates = family.get("candidates") or []
        if candidates and all(
            all(int(index) in drop_by_index for index in candidate.get("subtitle_indices") or [])
            for candidate in candidates
        ):
            remaining_all_dropped += 1

    guarded["drop_decisions"] = [drop_by_index[index] for index in sorted(drop_by_index)]
    guarded["duplicate_family_guard"] = {
        "family_count": len(families),
        "all_dropped_family_count_before": all_dropped_before,
        "restored_family_count": len(restorations),
        "all_dropped_family_count_after": remaining_all_dropped,
    }
    summary = guarded.setdefault("summary", {})
    summary["duplicate_family_count"] = len(families)
    summary["all_dropped_duplicate_family_count_before"] = all_dropped_before
    summary["restored_duplicate_family_count"] = len(restorations)
    summary["all_dropped_duplicate_family_count_after"] = remaining_all_dropped
    report = {
        "family_count": len(families),
        "all_dropped_family_count": all_dropped_before,
        "all_dropped_family_count_before": all_dropped_before,
        "restored_family_count": len(restorations),
        "all_dropped_family_count_after": remaining_all_dropped,
        "families": families,
        "restorations": restorations,
        "fatal_reasons": ["DUPLICATE_FAMILY_STILL_ALL_DROPPED"] if remaining_all_dropped else [],
    }
    return guarded, report
