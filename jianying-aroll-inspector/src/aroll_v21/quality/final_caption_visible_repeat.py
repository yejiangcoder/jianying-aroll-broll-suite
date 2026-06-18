from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from aroll_adjacent_modifier_semantic_redundancy_gate import detect_adjacent_modifier_semantic_redundancy
from aroll_text_normalize import normalize_text
from aroll_v21.ir.models import CaptionRenderUnit
from aroll_v21.quality.repeat_span_repair import longest_suffix_prefix_overlap, self_repair_aborted_phrase_candidate


NGRAM_SIZE = 4
PREFIX_SUFFIX_MIN_OVERLAP = 3
NEAR_DUPLICATE_RATIO = 0.9


def build_final_caption_visible_repeat_gate(captions: list[CaptionRenderUnit]) -> dict[str, Any]:
    ordered = sorted(captions, key=lambda row: (int(row.target_start_us), int(row.target_end_us), str(row.caption_id)))
    containment_candidates = _containment_candidates(ordered)
    containment_pairs = _candidate_pairs(containment_candidates)
    prefix_suffix_candidates = _prefix_suffix_candidates(ordered, containment_pairs)
    excluded_pairs = _candidate_pairs([*containment_candidates, *prefix_suffix_candidates])
    ngram_candidates = _ngram_candidates(ordered, excluded_pairs)
    near_duplicate_candidates = _near_duplicate_candidates(ordered, containment_candidates, prefix_suffix_candidates)
    modifier_redundancy_candidates = _modifier_redundancy_candidates(ordered)
    self_repair_candidates = _self_repair_aborted_phrase_candidates(ordered)
    visible_repeat_candidates = [
        *containment_candidates,
        *prefix_suffix_candidates,
        *ngram_candidates,
        *near_duplicate_candidates,
    ]
    blocker_codes: list[str] = []
    if visible_repeat_candidates:
        blocker_codes.append("V21_FINAL_CAPTION_VISIBLE_REPEAT_GATE_FAILED")
    if modifier_redundancy_candidates:
        blocker_codes.append("V21_FATAL_MODIFIER_REDUNDANCY_UNRESOLVED")
    if self_repair_candidates:
        blocker_codes.append("V21_SELF_REPAIR_ABORTED_PHRASE_UNRESOLVED")
    return {
        "gate_passed": not blocker_codes,
        "blocker_codes": blocker_codes,
        "visible_repeat_candidate_count": len(visible_repeat_candidates),
        "containment_repeat_count": len(containment_candidates),
        "prefix_suffix_overlap_count": len(prefix_suffix_candidates),
        "ngram_repeat_count": len(ngram_candidates),
        "near_duplicate_visible_caption_count": len(near_duplicate_candidates),
        "modifier_redundancy_residual_count": len(modifier_redundancy_candidates),
        "self_repair_aborted_phrase_count": len(self_repair_candidates),
        "visible_repeat_candidates": visible_repeat_candidates,
        "containment_repeat_candidates": containment_candidates,
        "prefix_suffix_overlap_candidates": prefix_suffix_candidates,
        "ngram_repeat_candidates": ngram_candidates,
        "near_duplicate_visible_caption_candidates": near_duplicate_candidates,
        "modifier_redundancy_residual_candidates": modifier_redundancy_candidates,
        "self_repair_aborted_phrase_candidates": self_repair_candidates,
        "final_caption_visible_repeat_gate_enabled": True,
        "ngram_size": NGRAM_SIZE,
        "prefix_suffix_min_overlap": PREFIX_SUFFIX_MIN_OVERLAP,
        "near_duplicate_ratio": NEAR_DUPLICATE_RATIO,
    }


def _containment_candidates(captions: list[CaptionRenderUnit]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for left_index, left in enumerate(captions):
        left_text = normalize_text(left.text)
        if not left_text:
            continue
        for right_index in range(left_index + 1, len(captions)):
            right = captions[right_index]
            right_text = normalize_text(right.text)
            if not right_text:
                continue
            if left_text == right_text or (len(left_text) >= 2 and left_text in right_text) or (len(right_text) >= 2 and right_text in left_text):
                candidates.append(
                    _candidate(
                        "containment_repeat",
                        left,
                        right,
                        overlap_text=left_text if len(left_text) <= len(right_text) else right_text,
                        score=1.0,
                    )
                )
    return candidates


def _prefix_suffix_candidates(captions: list[CaptionRenderUnit], excluded_pairs: set[tuple[str, str]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for left, right in zip(captions, captions[1:]):
        if (left.caption_id, right.caption_id) in excluded_pairs:
            continue
        left_chars = list(normalize_text(left.text))
        right_chars = list(normalize_text(right.text))
        overlap = longest_suffix_prefix_overlap(left_chars, right_chars)
        if overlap >= PREFIX_SUFFIX_MIN_OVERLAP:
            candidates.append(
                _candidate(
                    "prefix_suffix_overlap",
                    left,
                    right,
                    overlap_text="".join(left_chars[-overlap:]),
                    score=overlap,
                )
            )
    return candidates


def _ngram_candidates(captions: list[CaptionRenderUnit], excluded_pairs: set[tuple[str, str]]) -> list[dict[str, Any]]:
    seen: dict[str, tuple[CaptionRenderUnit, int]] = {}
    candidates: list[dict[str, Any]] = []
    emitted: set[tuple[str, str, str]] = set()
    for caption_index, caption in enumerate(captions):
        text = normalize_text(caption.text)
        for ngram in _ngrams(text, NGRAM_SIZE):
            previous_row = seen.get(ngram)
            if previous_row is None:
                seen[ngram] = (caption, caption_index)
                continue
            previous, previous_index = previous_row
            if (previous.caption_id, caption.caption_id) in excluded_pairs:
                continue
            if not _ngram_repeat_is_blocking(previous, caption, ngram, previous_index, caption_index):
                continue
            key = (previous.caption_id, caption.caption_id, ngram)
            if key in emitted:
                continue
            emitted.add(key)
            candidates.append(
                _candidate(
                    "ngram_repeat",
                    previous,
                    caption,
                    overlap_text=ngram,
                    score=NGRAM_SIZE,
                )
            )
    return candidates


def _ngram_repeat_is_blocking(
    left: CaptionRenderUnit,
    right: CaptionRenderUnit,
    ngram: str,
    left_index: int,
    right_index: int,
) -> bool:
    if right_index - left_index == 1:
        return True
    left_text = normalize_text(left.text)
    right_text = normalize_text(right.text)
    shorter = min(len(left_text), len(right_text))
    if not shorter:
        return False
    return len(ngram) / shorter >= 0.75


def _near_duplicate_candidates(
    captions: list[CaptionRenderUnit],
    containment_candidates: list[dict[str, Any]],
    prefix_suffix_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    excluded_pairs = _candidate_pairs([*containment_candidates, *prefix_suffix_candidates])
    candidates: list[dict[str, Any]] = []
    for left_index, left in enumerate(captions):
        left_text = normalize_text(left.text)
        if len(left_text) < NGRAM_SIZE:
            continue
        for right_index in range(left_index + 1, len(captions)):
            right = captions[right_index]
            right_text = normalize_text(right.text)
            if len(right_text) < NGRAM_SIZE:
                continue
            pair = (left.caption_id, right.caption_id)
            if pair in excluded_pairs:
                continue
            ratio = SequenceMatcher(None, left_text, right_text).ratio()
            if ratio >= NEAR_DUPLICATE_RATIO:
                candidates.append(
                    _candidate(
                        "near_duplicate_visible_caption",
                        left,
                        right,
                        overlap_text="",
                        score=round(ratio, 6),
                    )
                )
    return candidates


def _modifier_redundancy_candidates(captions: list[CaptionRenderUnit]) -> list[dict[str, Any]]:
    rows = [
        {
            "fragment_id": caption.caption_id,
            "fragment_text": caption.text,
            "text": caption.text,
        }
        for caption in captions
    ]
    candidates: list[dict[str, Any]] = []
    for row in detect_adjacent_modifier_semantic_redundancy(rows):
        severity = str(row.get("severity") or "fatal")
        if severity not in {"fatal", "high"}:
            continue
        row_index = int(row.get("row_index") or 0)
        if not (1 <= row_index <= len(captions)):
            continue
        caption = captions[row_index - 1]
        related_caption = captions[int(row.get("next_row_index") or row_index) - 1] if int(row.get("next_row_index") or 0) in range(1, len(captions) + 1) else caption
        candidate = _candidate(
            "fatal_modifier_redundancy_residual",
            caption,
            related_caption,
            overlap_text=str(row.get("phrase") or ""),
            score=1.0,
        )
        candidate.update(
            {
                "type": str(row.get("type") or "adjacent_modifier_semantic_redundancy"),
                "severity": severity,
                "scope": str(row.get("scope") or ""),
                "phrase": str(row.get("phrase") or ""),
                "modifiers": [
                    str(row.get("left_modifier") or ""),
                    str(row.get("right_modifier") or ""),
                ],
                "head": str(row.get("head_text") or ""),
                "requires_semantic_adjudication": True,
                "suggested_decision": "drop_redundant_modifier",
            }
        )
        candidates.append(candidate)
    return candidates


def _self_repair_aborted_phrase_candidates(captions: list[CaptionRenderUnit]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for left, right in zip(captions, captions[1:]):
        row = self_repair_aborted_phrase_candidate(left.text, right.text)
        if row is None:
            continue
        candidate = _candidate(
            "self_repair_aborted_phrase_residual",
            left,
            right,
            overlap_text=str(row.get("common_prefix") or ""),
            score=float(row.get("similarity") or 0.0),
        )
        candidate.update(row)
        candidates.append(candidate)
    return candidates


def _candidate_pairs(rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {
        (str(row.get("caption_id") or ""), str(row.get("related_caption_id") or ""))
        for row in rows
    }


def _ngrams(text: str, size: int) -> list[str]:
    if len(text) < size:
        empty: list[str] = []
        return empty
    return [text[index : index + size] for index in range(0, len(text) - size + 1)]


def _candidate(
    reason: str,
    caption: CaptionRenderUnit,
    related: CaptionRenderUnit,
    *,
    overlap_text: str,
    score: float | int,
) -> dict[str, Any]:
    return {
        "reason": reason,
        "caption_id": caption.caption_id,
        "related_caption_id": related.caption_id,
        "target_start_us": int(caption.target_start_us),
        "target_end_us": int(caption.target_end_us),
        "duration_us": int(caption.target_end_us) - int(caption.target_start_us),
        "text": caption.text,
        "related_target_start_us": int(related.target_start_us),
        "related_target_end_us": int(related.target_end_us),
        "related_text": related.text,
        "overlap_text": overlap_text,
        "score": score,
        "caption_word_ids": list(caption.word_ids),
        "related_word_ids": list(related.word_ids),
    }
