from __future__ import annotations

from typing import Any


FINAL_VISIBLE_REPAIR_COUNT_KEYS = (
    "dangling_prefix_suffix_count",
    "semantic_garbage_or_asr_suspect_count",
    "semantic_integrity_count",
    "cross_caption_semantic_containment_count",
    "restart_repeat_visible_count",
)


def _repair_counts(gate: dict[str, Any]) -> dict[str, int]:
    return {key: int(gate.get(key) or 0) for key in FINAL_VISIBLE_REPAIR_COUNT_KEYS}


def _action(
    issue_type: str,
    decision: str,
    pass_index: int,
    candidate: dict[str, Any],
    **extra: Any,
) -> dict[str, Any]:
    return {
        "pass_index": pass_index,
        "issue_type": issue_type,
        "decision": decision,
        "caption_id": str(candidate.get("caption_id") or ""),
        "related_caption_id": str(candidate.get("related_caption_id") or ""),
        "reason": str(candidate.get("reason") or ""),
        "overlap_text": str(candidate.get("overlap_text") or ""),
        **extra,
    }


def _is_prefix(values: list[str], prefix: list[str]) -> bool:
    return len(values) >= len(prefix) and values[: len(prefix)] == prefix


def _is_suffix(values: list[str], suffix: list[str]) -> bool:
    return len(values) >= len(suffix) and values[len(values) - len(suffix) :] == suffix


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
