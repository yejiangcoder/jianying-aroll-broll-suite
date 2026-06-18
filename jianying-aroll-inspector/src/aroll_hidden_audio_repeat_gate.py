from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aroll_adjacent_modifier_semantic_redundancy_gate import detect_adjacent_modifier_semantic_redundancy
from aroll_cjk_short_repeat_gate import classify_adjacent_cjk_ngram_repeat, detect_cjk_short_repeats


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _text(row: dict[str, Any]) -> str:
    return str(row.get("fragment_text") or row.get("text") or row.get("subtitle_text") or "")


def _word_map(word_timeline: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("word_id") or ""): row for row in word_timeline if str(row.get("word_id") or "")}


def _repeated_islands(tokens: list[str], min_n: int = 2, max_n: int = 6) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for n in range(min_n, max_n + 1):
        seen: dict[tuple[str, ...], list[int]] = {}
        for i in range(0, max(0, len(tokens) - n + 1)):
            gram = tuple(tokens[i : i + n])
            if not all(item.strip() for item in gram):
                continue
            seen.setdefault(gram, []).append(i)
        for gram, positions in seen.items():
            if len(positions) < 2:
                continue
            if positions[-1] - positions[0] < n:
                continue
            first_position = positions[0]
            second_position = positions[1]
            if second_position - first_position == n:
                phrase = "".join(gram)
                normalized = "".join(tokens)
                char_start = sum(len(token) for token in tokens[:first_position])
                severity, _reason = classify_adjacent_cjk_ngram_repeat(normalized, char_start, len(phrase), phrase)
                if severity != "fatal":
                    continue
            samples.append(
                {
                    "phrase": "".join(gram),
                    "token_ngram_size": n,
                    "positions": positions[:10],
                    "occurrence_count": len(positions),
                }
            )
    samples.sort(key=lambda row: (-int(row.get("token_ngram_size") or 0), -int(row.get("occurrence_count") or 0), str(row.get("phrase") or "")))
    deduped: list[dict[str, Any]] = []
    used: set[str] = set()
    for row in samples:
        phrase = str(row.get("phrase") or "")
        if phrase in used:
            continue
        used.add(phrase)
        deduped.append(row)
    return deduped


def build_hidden_audio_repeat_report(
    residual_repeat_audit: dict[str, Any],
    display_subtitle_plan: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    issues = [
        row for row in (residual_repeat_audit.get("issues") or [])
        if str(row.get("issue_type") or "") in {"word_timeline_hidden_repeat", "hidden_audio_repeat", "intra_subtitle_restart"}
    ]
    high = [row for row in issues if str(row.get("confidence") or "") == "high"]
    words_by_id = _word_map(word_timeline)
    island_samples: list[dict[str, Any]] = []
    for group in display_subtitle_plan:
        word_ids = [str(item) for item in (group.get("word_ids") or []) if str(item)]
        tokens = [str((words_by_id.get(word_id) or {}).get("word_text") or "") for word_id in word_ids]
        islands = _repeated_islands(tokens)
        for island in islands[:5]:
            island_samples.append(
                {
                    "fragment_id": group.get("fragment_id"),
                    "fragment_text": _text(group),
                    "word_ids": word_ids,
                    **island,
                }
            )
    short_repeat_candidates = detect_cjk_short_repeats(display_subtitle_plan)
    short_repeat_fatal = [row for row in short_repeat_candidates if str(row.get("severity") or "fatal") == "fatal"]
    short_repeat_warning = [row for row in short_repeat_candidates if str(row.get("severity") or "fatal") != "fatal"]
    modifier_redundancy_candidates = detect_adjacent_modifier_semantic_redundancy(display_subtitle_plan)
    modifier_redundancy_fatal = [row for row in modifier_redundancy_candidates if str(row.get("severity") or "fatal") == "fatal"]
    island_blockers = [
        {
            "type": "word_timeline_repeated_island",
            "issue_type": "word_timeline_repeated_island",
            "severity": "fatal",
            "confidence": "high",
            "reason": "word timeline contains repeated non-overlapping token island",
            **row,
        }
        for row in island_samples
    ]
    residual_blockers = [
        {
            "severity": "fatal",
            "confidence": row.get("confidence") or "high",
            **row,
        }
        for row in high
    ]
    blocking_issues = (residual_blockers + island_blockers + short_repeat_fatal + modifier_redundancy_fatal)[:100]

    report = {
        "word_timeline_hidden_repeat_count": len(high),
        "word_timeline_repeated_island_count": len(island_samples),
        "final_spoken_text_short_repeat_count": len(short_repeat_candidates),
        "final_spoken_text_short_repeat_fatal_count": len(short_repeat_fatal),
        "final_spoken_text_short_repeat_warning_count": len(short_repeat_warning),
        "adjacent_modifier_semantic_redundancy_count": len(modifier_redundancy_candidates),
        "adjacent_modifier_semantic_redundancy_fatal_count": len(modifier_redundancy_fatal),
        "repeated_island_samples": island_samples[:100],
        "final_spoken_text_short_repeat_samples": short_repeat_candidates[:100],
        "adjacent_modifier_semantic_redundancy_samples": modifier_redundancy_candidates[:100],
        "audio_only_repeat_supported": False,
        "audio_only_repeat_not_supported_warning": True,
        "word_timeline_hidden_repeat_supported": True,
        "hidden_audio_repeat_gate_passed": len(blocking_issues) == 0,
        "blocking_issues": blocking_issues,
        "issues": blocking_issues,
    }
    if output_path:
        write_json(output_path, report)
    return report
