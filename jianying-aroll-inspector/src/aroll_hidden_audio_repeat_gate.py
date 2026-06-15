from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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

    report = {
        "word_timeline_hidden_repeat_count": len(high),
        "word_timeline_repeated_island_count": len(island_samples),
        "repeated_island_samples": island_samples[:100],
        "audio_only_repeat_supported": False,
        "audio_only_repeat_not_supported_warning": True,
        "word_timeline_hidden_repeat_supported": True,
        "hidden_audio_repeat_gate_passed": len(high) == 0 and len(island_samples) == 0,
        "issues": high[:100],
    }
    if output_path:
        write_json(output_path, report)
    return report
