from __future__ import annotations

from typing import Any

from aroll_text_normalize import normalize_text
from aroll_v21.ir.models import CaptionRenderUnit


ADJACENT_TARGET_GAP_US = 800_000
NEAR_TARGET_GAP_US = 3_000_000
SHORT_CONCEPT_MAX_CJK_CHARS = 3


def classify_final_visible_repeat_candidates(
    captions: list[CaptionRenderUnit],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    index_by_caption_id = {caption.caption_id: index for index, caption in enumerate(captions)}
    caption_by_id = {caption.caption_id: caption for caption in captions}
    classified: list[dict[str, Any]] = []
    for candidate in candidates:
        row = dict(candidate)
        caption_id = str(row.get("caption_id") or "")
        related_caption_id = str(row.get("related_caption_id") or "")
        caption = caption_by_id.get(caption_id)
        related = caption_by_id.get(related_caption_id)
        distance_kind = _distance_kind(
            candidate=row,
            caption_index=index_by_caption_id.get(caption_id),
            related_index=index_by_caption_id.get(related_caption_id),
        )
        classification, severity, risk_tags, reason = _classification_for_candidate(
            row,
            distance_kind=distance_kind,
            caption=caption,
            related=related,
        )
        row.update(
            {
                "classification": classification,
                "repeat_kind": classification,
                "classified_as": classification,
                "distance_kind": distance_kind,
                "severity": severity,
                "risk_tags": risk_tags,
                "classification_reason": reason,
            }
        )
        classified.append(row)
    return classified


def blocking_repeat_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [candidate for candidate in candidates if str(candidate.get("severity") or "") in {"fatal", "high"}]


def warning_repeat_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [candidate for candidate in candidates if str(candidate.get("severity") or "") == "warning"]


def allowed_repeat_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [candidate for candidate in candidates if str(candidate.get("severity") or "") == "allow"]


def _classification_for_candidate(
    candidate: dict[str, Any],
    *,
    distance_kind: str,
    caption: CaptionRenderUnit | None,
    related: CaptionRenderUnit | None,
) -> tuple[str, str, list[str], str]:
    reason = str(candidate.get("reason") or candidate.get("type") or "")
    overlap_text = normalize_text(str(candidate.get("overlap_text") or ""))
    if distance_kind == "same_segment" and "restart" in reason:
        return "same_segment_restart", "fatal", ["same_segment", "local_restart"], "same segment restart remains blocking"
    if "restart" in reason:
        if distance_kind in {"adjacent", "near"}:
            return "local_restart", "fatal", [distance_kind, "restart"], "adjacent or near restart remains blocking"
        return "distant_restart_like_recurrence", "warning", ["distant"], "distant restart-like recurrence is not auto-fatal"
    if reason == "prefix_suffix_overlap":
        if distance_kind in {"adjacent", "near"}:
            return "local_boundary_overlap", "fatal", [distance_kind, "boundary_overlap"], "local suffix/prefix overlap remains blocking"
        return _nonlocal_reuse_classification(overlap_text, "distant_boundary_overlap")
    if reason == "cross_caption_semantic_containment":
        if distance_kind in {"adjacent", "near"}:
            return "local_cross_caption_containment", "fatal", [distance_kind, "cross_caption_window"], "local cross-caption containment remains blocking"
        return _nonlocal_reuse_classification(overlap_text, "distant_containment")
    if reason == "near_duplicate_visible_caption":
        if distance_kind in {"adjacent", "near"}:
            return "local_near_duplicate", "fatal", [distance_kind, "near_duplicate"], "local near duplicate remains blocking"
        return "distant_semantic_recurrence", "warning", ["distant"], "distant near-duplicate recurrence requires review but is not auto-fatal"
    if reason == "ngram_repeat":
        return _ngram_classification(candidate, distance_kind=distance_kind, caption=caption, related=related)
    if reason == "containment_repeat":
        return _containment_classification(candidate, distance_kind=distance_kind, caption=caption, related=related)
    if distance_kind in {"adjacent", "near"}:
        return "local_visible_repeat", "fatal", [distance_kind], "local visible repeat remains blocking"
    return _nonlocal_reuse_classification(overlap_text, "semantic_recurrence")


def _containment_classification(
    candidate: dict[str, Any],
    *,
    distance_kind: str,
    caption: CaptionRenderUnit | None,
    related: CaptionRenderUnit | None,
) -> tuple[str, str, list[str], str]:
    overlap_text = normalize_text(str(candidate.get("overlap_text") or ""))
    if distance_kind in {"adjacent", "near"} and _exact_visible_duplicate(caption=caption, related=related):
        return "local_exact_duplicate", "fatal", [distance_kind, "exact_duplicate"], "local exact visible duplicate remains blocking"
    if distance_kind in {"adjacent", "near"} and _boundary_containment_like_restart(candidate, caption=caption, related=related):
        return "local_containment_restart", "fatal", [distance_kind, "containment_restart"], "local containment touches a boundary and remains blocking"
    if distance_kind in {"adjacent", "near"}:
        return "local_semantic_recurrence", "warning", [distance_kind], "local containment without restart boundary is warning only"
    return _nonlocal_reuse_classification(overlap_text, "distant_containment")


def _exact_visible_duplicate(
    *,
    caption: CaptionRenderUnit | None,
    related: CaptionRenderUnit | None,
) -> bool:
    if caption is None or related is None:
        return False
    left_text = normalize_text(caption.text)
    right_text = normalize_text(related.text)
    return bool(left_text) and left_text == right_text


def _ngram_classification(
    candidate: dict[str, Any],
    *,
    distance_kind: str,
    caption: CaptionRenderUnit | None,
    related: CaptionRenderUnit | None,
) -> tuple[str, str, list[str], str]:
    overlap_text = normalize_text(str(candidate.get("overlap_text") or ""))
    if distance_kind in {"adjacent", "near"} and _ngram_forms_boundary_restart(overlap_text, caption=caption, related=related):
        return "local_ngram_boundary_repeat", "fatal", [distance_kind, "ngram_boundary"], "local ngram touches a caption boundary and remains blocking"
    if distance_kind in {"adjacent", "near"}:
        return "local_semantic_recurrence", "warning", [distance_kind], "local shared ngram away from boundaries is warning only"
    return _nonlocal_reuse_classification(overlap_text, "distant_semantic_recurrence")


def _nonlocal_reuse_classification(
    overlap_text: str,
    default_classification: str,
) -> tuple[str, str, list[str], str]:
    cjk_count = _cjk_char_count(overlap_text)
    if cjk_count and cjk_count <= SHORT_CONCEPT_MAX_CJK_CHARS:
        return "short_concept_reuse", "allow", ["short_concept", "nonlocal_reuse"], "short concept or address term recurrence is allowed"
    return default_classification, "warning", ["nonlocal_reuse"], "distant recurrence is reported but not auto-fatal"


def _boundary_containment_like_restart(
    candidate: dict[str, Any],
    *,
    caption: CaptionRenderUnit | None,
    related: CaptionRenderUnit | None,
) -> bool:
    if caption is None or related is None:
        return False
    overlap_text = normalize_text(str(candidate.get("overlap_text") or ""))
    left_text = normalize_text(caption.text)
    right_text = normalize_text(related.text)
    if not overlap_text:
        return False
    return (
        left_text == overlap_text
        and right_text.startswith(overlap_text)
        and len(right_text) > len(overlap_text)
    ) or (
        right_text == overlap_text
        and left_text.startswith(overlap_text)
        and len(left_text) > len(overlap_text)
    )


def _ngram_forms_boundary_restart(
    overlap_text: str,
    *,
    caption: CaptionRenderUnit | None,
    related: CaptionRenderUnit | None,
) -> bool:
    if caption is None or related is None or not overlap_text:
        return False
    left_text = normalize_text(caption.text)
    right_text = normalize_text(related.text)
    return (
        left_text.endswith(overlap_text)
        and right_text.startswith(overlap_text)
        and len(left_text) > len(overlap_text)
        and len(right_text) > len(overlap_text)
    ) or (
        right_text.endswith(overlap_text)
        and left_text.startswith(overlap_text)
        and len(left_text) > len(overlap_text)
        and len(right_text) > len(overlap_text)
    )


def _distance_kind(
    *,
    candidate: dict[str, Any],
    caption_index: int | None,
    related_index: int | None,
) -> str:
    if str(candidate.get("caption_id") or "") == str(candidate.get("related_caption_id") or ""):
        return "same_segment"
    if caption_index is None or related_index is None:
        return "distant"
    index_gap = abs(int(related_index) - int(caption_index))
    if _target_ranges_overlap(candidate):
        if index_gap <= 1:
            return "adjacent"
        if index_gap <= 2:
            return "near"
    target_gap_us = _target_gap_us(candidate)
    if index_gap == 1 and -80_000 <= target_gap_us <= ADJACENT_TARGET_GAP_US:
        return "adjacent"
    if 1 <= index_gap <= 2 and -80_000 <= target_gap_us <= NEAR_TARGET_GAP_US:
        return "near"
    return "distant"


def _target_ranges_overlap(candidate: dict[str, Any]) -> bool:
    left_start = int(candidate.get("target_start_us") or 0)
    left_end = int(candidate.get("target_end_us") or 0)
    right_start = int(candidate.get("related_target_start_us") or 0)
    right_end = int(candidate.get("related_target_end_us") or 0)
    return max(left_start, right_start) < min(left_end, right_end)


def _target_gap_us(candidate: dict[str, Any]) -> int:
    left_start = int(candidate.get("target_start_us") or 0)
    left_end = int(candidate.get("target_end_us") or 0)
    right_start = int(candidate.get("related_target_start_us") or 0)
    right_end = int(candidate.get("related_target_end_us") or 0)
    if right_start >= left_start:
        return right_start - left_end
    return left_start - right_end


def _cjk_char_count(text: str) -> int:
    return sum(1 for char in str(text or "") if "\u3400" <= char <= "\u9fff")
