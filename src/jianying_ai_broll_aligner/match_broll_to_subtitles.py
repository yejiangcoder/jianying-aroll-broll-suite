from __future__ import annotations

import difflib
import re

from .models import BrollItem, ExecPlanItem, ImageAsset, SubtitleRow


PUNCT = r"""`'"“”‘’\s,.!?;:，。！？；：、（）()【】[]《》<>-—…·"""


def normalize_text(value: str) -> str:
    value = re.sub(f"[{re.escape(PUNCT)}]", "", value or "")
    return value.lower()


def score_text(target: str, candidate: str) -> tuple[float, str]:
    target_norm = normalize_text(target)
    candidate_norm = normalize_text(candidate)
    if not target_norm or not candidate_norm:
        return 0.0, "empty"
    if target_norm == candidate_norm or target_norm in candidate_norm:
        return 1.0, "exact_or_contains"
    if candidate_norm in target_norm and len(candidate_norm) >= 6:
        return min(0.92, len(candidate_norm) / len(target_norm) + 0.25), "candidate_contains"
    sequence = difflib.SequenceMatcher(None, target_norm, candidate_norm).ratio()
    overlap = len(set(target_norm) & set(candidate_norm)) / max(1, len(set(target_norm) | set(candidate_norm)))
    return max(sequence, overlap * 0.80), "normalized_fuzzy"


def best_match(
    item: BrollItem,
    subtitles: list[SubtitleRow],
    start_index: int = 0,
    max_window: int = 4,
) -> tuple[SubtitleRow, str, float, str]:
    best: tuple[float, int, SubtitleRow, str, str] | None = None
    for idx in range(start_index, len(subtitles)):
        combined = ""
        for width in range(1, max_window + 1):
            if idx + width > len(subtitles):
                break
            combined = (combined + " " + subtitles[idx + width - 1].text).strip()
            score, method = score_text(item.target_quote, combined)
            candidate = (score, -width, subtitles[idx], combined, method)
            if best is None or candidate > best:
                best = candidate
    if best is None:
        raise ValueError(f"No subtitles available for image {item.image_id}")
    score, _neg_width, row, combined, method = best
    return row, combined, score, method


def match_broll_to_subtitles(
    items: list[BrollItem],
    assets: dict[str, ImageAsset],
    subtitles: list[SubtitleRow],
    duration_sec: float = 1.3,
    min_confidence: float = 0.50,
    monotonic: bool = True,
) -> list[ExecPlanItem]:
    if not subtitles:
        raise ValueError("No subtitles were parsed")
    rows: list[ExecPlanItem] = []
    search_start = 0
    for item in items:
        if item.image_id not in assets:
            raise FileNotFoundError(f"Missing image asset for ID {item.image_id}")
        subtitle, matched_text, confidence, method = best_match(item, subtitles, search_start)
        if confidence < min_confidence:
            raise ValueError(
                f"Low-confidence match for image {item.image_id}: {confidence:.3f}; target={item.target_quote!r}; best={matched_text!r}"
            )
        rows.append(
            ExecPlanItem(
                image_id=item.image_id,
                image_path=assets[item.image_id].path,
                subtitle_index=subtitle.index,
                subtitle_text=subtitle.text,
                start_sec=subtitle.start_sec,
                duration_sec=duration_sec,
                target_quote=item.target_quote,
                match_method=method,
                confidence=confidence,
            )
        )
        if monotonic:
            search_start = max(search_start, subtitle.index - 1)
    return rows

