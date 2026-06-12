from __future__ import annotations

from dataclasses import dataclass
import difflib
import re

from .models import BrollItem, ExecPlanItem, ImageAsset, SubtitleRow


PUNCT = r"""`'"“”‘’\s,.!?;:，。！？；：、（）()【】[]《》<>-—…·"""


@dataclass(frozen=True)
class SubtitleWindow:
    start_index: int
    end_index: int
    width: int
    row: SubtitleRow
    rows_span: tuple[SubtitleRow, ...]
    text: str
    normalized: str
    normalized_parts: tuple[str, ...]


def normalize_text(value: str) -> str:
    value = re.sub(f"[{re.escape(PUNCT)}]", "", value or "")
    return value.lower().replace("国南", "国男").replace("0", "零")


def _bigrams(value: str) -> set[str]:
    if not value:
        return set()
    if len(value) == 1:
        return {value}
    return {value[i : i + 2] for i in range(len(value) - 1)}


def _dice_score(left: str, right: str) -> float:
    left_pairs = _bigrams(left)
    right_pairs = _bigrams(right)
    if not left_pairs or not right_pairs:
        return 0.0
    return 2 * len(left_pairs & right_pairs) / max(1, len(left_pairs) + len(right_pairs))


def _method_rank(method: str) -> int:
    return {
        "exact": 4,
        "target_contains": 3,
        "candidate_contains": 2,
        "normalized_fuzzy": 1,
        "empty": 0,
    }.get(method, 0)


def score_text(target: str, candidate: str) -> tuple[float, str]:
    target_norm = normalize_text(target)
    candidate_norm = normalize_text(candidate)
    if not target_norm or not candidate_norm:
        return 0.0, "empty"
    if target_norm == candidate_norm:
        return 1.0, "exact"
    if target_norm in candidate_norm:
        return min(0.99, 0.88 + len(target_norm) / max(1, len(candidate_norm)) * 0.11), "target_contains"
    if candidate_norm in target_norm and len(candidate_norm) >= 6:
        return min(0.92, len(candidate_norm) / len(target_norm) + 0.25), "candidate_contains"
    sequence = difflib.SequenceMatcher(None, target_norm, candidate_norm).ratio()
    overlap = len(set(target_norm) & set(candidate_norm)) / max(1, len(set(target_norm) | set(candidate_norm)))
    dice = _dice_score(target_norm, candidate_norm)
    return max(sequence * 0.55 + overlap * 0.25 + dice * 0.20, overlap * 0.78, dice * 0.82), "normalized_fuzzy"


def build_subtitle_windows(subtitles: list[SubtitleRow], max_window: int = 7) -> list[SubtitleWindow]:
    windows: list[SubtitleWindow] = []
    for idx in range(len(subtitles)):
        combined = ""
        for width in range(1, max_window + 1):
            if idx + width > len(subtitles):
                break
            combined = (combined + " " + subtitles[idx + width - 1].text).strip()
            normalized = normalize_text(combined)
            if not normalized:
                continue
            windows.append(
                SubtitleWindow(
                    start_index=idx,
                    end_index=idx + width - 1,
                    width=width,
                    row=subtitles[idx],
                    rows_span=tuple(subtitles[idx : idx + width]),
                    text=combined,
                    normalized=normalized,
                    normalized_parts=tuple(normalize_text(row.text) for row in subtitles[idx : idx + width]),
                )
            )
    return windows


def _anchor_window(window: SubtitleWindow, target_norm: str, method: str) -> SubtitleWindow:
    if method not in {"exact", "target_contains"} or not target_norm:
        return window
    position = window.normalized.find(target_norm)
    if position < 0:
        return window
    cursor = 0
    for offset, part in enumerate(window.normalized_parts):
        next_cursor = cursor + len(part)
        if position < next_cursor or (part and position == cursor):
            start_index = window.start_index + offset
            return SubtitleWindow(
                start_index=start_index,
                end_index=window.end_index,
                width=window.end_index - start_index + 1,
                row=window.rows_span[offset],
                rows_span=window.rows_span[offset:],
                text=window.text,
                normalized=window.normalized,
                normalized_parts=window.normalized_parts[offset:],
            )
        cursor = next_cursor
    return window


def _best_match_window(
    item: BrollItem,
    windows: list[SubtitleWindow],
    start_index: int,
) -> tuple[SubtitleWindow, float, str]:
    target_norm = normalize_text(item.target_quote)
    for window in windows:
        score, method = score_text(item.target_quote, window.text)
        candidate = _anchor_window(window, target_norm, method)
        if candidate.start_index < start_index:
            continue
        if method in {"exact", "target_contains"} and score >= 0.86:
            return candidate, score, method

    best_window: SubtitleWindow | None = None
    best_score = 0.0
    best_method = "empty"
    best_key: tuple[float, int, int, int] | None = None
    for window in windows:
        score, method = score_text(item.target_quote, window.text)
        candidate = _anchor_window(window, target_norm, method)
        if candidate.start_index < start_index:
            continue
        key = (
            round(score, 6),
            _method_rank(method),
            -candidate.width,
            -candidate.start_index,
        )
        if best_key is None or key > best_key:
            best_key = key
            best_window = candidate
            best_score = score
            best_method = method
    if best_window is None:
        raise ValueError(f"No subtitles available for image {item.image_id}")
    return best_window, best_score, best_method


def best_match(
    item: BrollItem,
    subtitles: list[SubtitleRow],
    start_index: int = 0,
    max_window: int = 7,
) -> tuple[SubtitleRow, str, float, str]:
    window, score, method = _best_match_window(item, build_subtitle_windows(subtitles, max_window), start_index)
    return window.row, window.text, score, method


def match_broll_to_subtitles(
    items: list[BrollItem],
    assets: dict[str, ImageAsset],
    subtitles: list[SubtitleRow],
    duration_sec: float = 1.3,
    min_confidence: float = 0.50,
    monotonic: bool = False,
) -> list[ExecPlanItem]:
    if not subtitles:
        raise ValueError("No subtitles were parsed")
    rows: list[ExecPlanItem] = []
    search_start = 0
    windows = build_subtitle_windows(subtitles)
    for item in items:
        if item.image_id not in assets:
            raise FileNotFoundError(f"Missing image asset for ID {item.image_id}")
        window, confidence, method = _best_match_window(item, windows, search_start if monotonic else 0)
        subtitle = window.row
        if confidence < min_confidence:
            raise ValueError(
                f"Low-confidence match for image {item.image_id}: {confidence:.3f}; target={item.target_quote!r}; best={window.text!r}"
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
                match_method=f"subtitle_text_window_{'monotonic' if monotonic else 'global'}:{method}",
                confidence=confidence,
            )
        )
        if monotonic:
            search_start = max(search_start, window.start_index + 1)
    return rows
