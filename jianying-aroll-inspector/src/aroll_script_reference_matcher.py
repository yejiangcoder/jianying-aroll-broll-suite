from __future__ import annotations

from pathlib import Path
from typing import Any

from aroll_text_normalize import char_ngrams, jaccard, lcs_ratio, normalize_text


def _window_score(query: str, window: str) -> float:
    if not query or not window:
        return 0.0
    return max(
        lcs_ratio(query, window),
        jaccard(char_ngrams(query, 2), char_ngrams(window, 2)),
    )


def load_script_text(script_path: Path | None) -> str:
    if not script_path or not script_path.exists():
        return ""
    return script_path.read_text("utf-8", errors="ignore")


def match_script_reference(
    source_text: str,
    script_text: str,
    *,
    excerpt_radius: int = 320,
    stride: int = 80,
    window_chars: int = 180,
) -> dict[str, Any]:
    query = normalize_text(source_text)
    if not query or not script_text:
        return {
            "script_reference_excerpt": "",
            "script_reference_match_score": 0,
            "script_reference_status": "not_found",
        }

    script_norm = normalize_text(script_text)
    direct = script_norm.find(query)
    if direct >= 0:
        raw_start = max(0, direct - excerpt_radius)
        raw_end = min(len(script_text), direct + len(source_text) + excerpt_radius)
        return {
            "script_reference_excerpt": script_text[raw_start:raw_end],
            "script_reference_match_score": 1.0,
            "script_reference_status": "direct",
        }

    best_score = 0.0
    best_start = 0
    for start in range(0, max(1, len(script_text)), stride):
        raw = script_text[start : start + window_chars]
        if not raw:
            continue
        score = _window_score(query, normalize_text(raw))
        if score > best_score:
            best_score = score
            best_start = start
    if best_score < 0.35:
        return {
            "script_reference_excerpt": "",
            "script_reference_match_score": round(best_score, 4),
            "script_reference_status": "not_found",
        }
    raw_start = max(0, best_start - excerpt_radius)
    raw_end = min(len(script_text), best_start + window_chars + excerpt_radius)
    return {
        "script_reference_excerpt": script_text[raw_start:raw_end],
        "script_reference_match_score": round(best_score, 4),
        "script_reference_status": "fuzzy",
    }
