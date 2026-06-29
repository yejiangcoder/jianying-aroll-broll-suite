from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from aroll_v21.ir.models import CaptionRenderUnit
from aroll_v21.quality.final_caption_visible.types import FinalCaptionVisibleEvidence


@dataclass(frozen=True)
class FinalCaptionVisibleDetectorSet:
    containment_candidates: Callable[[list[CaptionRenderUnit]], list[dict[str, Any]]]
    candidate_pairs: Callable[[list[dict[str, Any]]], set[tuple[str, str]]]
    prefix_suffix_candidates: Callable[[list[CaptionRenderUnit], set[tuple[str, str]]], list[dict[str, Any]]]
    ngram_candidates: Callable[[list[CaptionRenderUnit], set[tuple[str, str]]], list[dict[str, Any]]]
    near_duplicate_candidates: Callable[
        [list[CaptionRenderUnit], list[dict[str, Any]], list[dict[str, Any]]],
        list[dict[str, Any]],
    ]
    modifier_redundancy_candidates: Callable[[list[CaptionRenderUnit]], list[dict[str, Any]]]
    self_repair_candidates: Callable[[list[CaptionRenderUnit]], list[dict[str, Any]]]
    dangling_candidates: Callable[[list[CaptionRenderUnit]], list[dict[str, Any]]]
    semantic_suspect_candidates: Callable[[list[CaptionRenderUnit]], list[dict[str, Any]]]
    semantic_integrity_candidates: Callable[[list[CaptionRenderUnit]], list[dict[str, Any]]]
    cross_caption_containment_candidates: Callable[[list[CaptionRenderUnit]], list[dict[str, Any]]]
    restart_repeat_candidates: Callable[[list[CaptionRenderUnit]], list[dict[str, Any]]]


def detect_final_caption_visible_evidence(
    captions: list[CaptionRenderUnit],
    detectors: FinalCaptionVisibleDetectorSet,
) -> FinalCaptionVisibleEvidence:
    ordered = sorted(captions, key=lambda row: (int(row.target_start_us), int(row.target_end_us), str(row.caption_id)))
    raw_containment_candidates = detectors.containment_candidates(ordered)
    containment_pairs = detectors.candidate_pairs(raw_containment_candidates)
    raw_prefix_suffix_candidates = detectors.prefix_suffix_candidates(ordered, containment_pairs)
    excluded_pairs = detectors.candidate_pairs([*raw_containment_candidates, *raw_prefix_suffix_candidates])
    return FinalCaptionVisibleEvidence(
        captions=ordered,
        raw_containment_candidates=raw_containment_candidates,
        raw_prefix_suffix_candidates=raw_prefix_suffix_candidates,
        raw_ngram_candidates=detectors.ngram_candidates(ordered, excluded_pairs),
        raw_near_duplicate_candidates=detectors.near_duplicate_candidates(
            ordered,
            raw_containment_candidates,
            raw_prefix_suffix_candidates,
        ),
        modifier_redundancy_candidates=detectors.modifier_redundancy_candidates(ordered),
        self_repair_candidates=detectors.self_repair_candidates(ordered),
        dangling_candidates=detectors.dangling_candidates(ordered),
        semantic_suspect_candidates=detectors.semantic_suspect_candidates(ordered),
        semantic_integrity_candidates=detectors.semantic_integrity_candidates(ordered),
        raw_cross_caption_containment_candidates=detectors.cross_caption_containment_candidates(ordered),
        raw_restart_repeat_candidates=detectors.restart_repeat_candidates(ordered),
    )
