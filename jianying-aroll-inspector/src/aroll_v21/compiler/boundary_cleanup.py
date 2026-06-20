from __future__ import annotations

from typing import Any


def configure_compiler_dependencies(dependencies: dict[str, Any]) -> None:
    globals().update(dependencies)


def _pre_emit_boundary_prefix_normalization(
    self,
    segments: list[FinalTimelineSegment],
    decision_plan: DecisionPlan,
) -> tuple[list[FinalTimelineSegment], list[Blocker]]:
    if len(segments) < 2:
        return segments, []
    current = list(segments)
    blockers: list[Blocker] = []
    seen_blocker_pairs: set[tuple[str, str]] = set()
    while True:
        dropped_indices: set[int] = set()
        for index, (left, right) in enumerate(zip(current, current[1:])):
            left_text = normalize_text(left.text)
            right_text = normalize_text(right.text)
            if not left_text or left_text == right_text or not right_text.startswith(left_text):
                continue
            if not self._safe_pre_emit_boundary_prefix_drop(left, right):
                pair_key = (
                    left.text,
                    right.text,
                    str(left.source_start_us),
                    str(left.source_end_us),
                    str(right.source_start_us),
                    str(right.source_end_us),
                )
                if pair_key not in seen_blocker_pairs:
                    seen_blocker_pairs.add(pair_key)
                    blockers.append(
                        Blocker(
                            code="BOUNDARY_PREFIX_CONTAINMENT_REQUIRES_HUMAN_REVIEW",
                            message="final timeline contains prefix containment that is not safe for automatic pre-emit drop",
                            layer="compiler",
                            severity="write_blocker",
                            context={
                                "left_segment_id": left.segment_id,
                                "right_segment_id": right.segment_id,
                                "left_text": left.text,
                                "right_text": right.text,
                            },
                        )
                    )
                continue
            dropped_indices.add(index)
            decision_plan.decision_trace.append(
                {
                    "route": "boundary_prefix_containment",
                    "stage": "final_timeline_pre_emit",
                    "left_text": left.text,
                    "right_text": right.text,
                    "decision": "drop_left_keep_right",
                    "applied": True,
                    "reason": "right segment is strict prefix extension of left segment",
                    "source": "local_policy",
                    "left_segment_id": left.segment_id,
                    "right_segment_id": right.segment_id,
                }
            )
        if not dropped_indices:
            return current, blockers
        kept = [segment for index, segment in enumerate(current) if index not in dropped_indices]
        current = self._repack_target_timeline(kept)


def _safe_pre_emit_boundary_prefix_drop(self, left: FinalTimelineSegment, right: FinalTimelineSegment) -> bool:
    left_text = normalize_text(left.text)
    right_text = normalize_text(right.text)
    if not right_text.startswith(left_text) or right_text == left_text:
        return False
    if not left.word_ids or not right.word_ids:
        return False
    return True


def _post_normalizer_adjacent_exact_duplicate_cleanup(
    self,
    segments: list[FinalTimelineSegment],
    decision_plan: DecisionPlan,
) -> tuple[list[FinalTimelineSegment], list[Blocker]]:
    if len(segments) < 2:
        return segments, []
    current = list(segments)
    while True:
        dropped_indices: set[int] = set()
        for index, (left, right) in enumerate(zip(current, current[1:])):
            left_text = normalize_text(left.text)
            right_text = normalize_text(right.text)
            if not left_text or left_text != right_text:
                continue
            if not left.word_ids or not right.word_ids:
                continue
            left_duration = int(left.source_end_us) - int(left.source_start_us)
            right_duration = int(right.source_end_us) - int(right.source_start_us)
            drop_index = index if left_duration <= right_duration else index + 1
            dropped = current[drop_index]
            kept = right if drop_index == index else left
            dropped_indices.add(drop_index)
            decision_plan.decision_trace.append(
                {
                    "route": "adjacent_exact_duplicate_cleanup",
                    "stage": "final_timeline_pre_emit",
                    "left_text": left.text,
                    "right_text": right.text,
                    "decision": "drop_left" if drop_index == index else "drop_right",
                    "applied": True,
                    "dropped_segment_id": dropped.segment_id,
                    "kept_segment_id": kept.segment_id,
                    "reason": "adjacent final segments have identical normalized text",
                    "source": "local_policy",
                }
            )
            break
        if not dropped_indices:
            return current, []
        current = self._repack_target_timeline([segment for index, segment in enumerate(current) if index not in dropped_indices])


def _final_cjk_boundary_suffix_prefix_overlap_cleanup(
    self,
    segments: list[FinalTimelineSegment],
    source_graph: CanonicalSourceGraph,
    decision_plan: DecisionPlan,
) -> tuple[list[FinalTimelineSegment], list[Blocker]]:
    if len(segments) < 2:
        return segments, []
    word_lookup = {word.word_id: word for word in source_graph.words}
    current = list(segments)
    blockers: list[Blocker] = []
    while True:
        changed = False
        for index, (left, right) in enumerate(zip(current, current[1:])):
            overlap = self._boundary_suffix_prefix_overlap(left.text, right.text)
            if len(overlap) < 2:
                continue
            if is_semantic_label_reuse_boundary(left.text, right.text, overlap):
                continue
            drop_word_ids = self._trailing_word_ids_for_overlap(left, word_lookup, overlap)
            if not drop_word_ids:
                blockers.append(
                    Blocker(
                        code="BOUNDARY_SUFFIX_PREFIX_OVERLAP_WORD_BINDING_MISSING",
                        message="boundary suffix-prefix overlap could not be bound to trailing whole word ids",
                        layer="compiler",
                        context={
                            "left_segment_id": left.segment_id,
                            "right_segment_id": right.segment_id,
                            "left_text": left.text,
                            "right_text": right.text,
                            "overlap_text": overlap,
                            "left_word_ids": left.word_ids,
                        },
                    )
                )
                return current, blockers
            drop_set = set(drop_word_ids)
            kept_word_ids = [word_id for word_id in left.word_ids if word_id not in drop_set]
            left_before = left.text
            if kept_word_ids:
                kept_words = [word_lookup[word_id] for word_id in kept_word_ids if word_id in word_lookup]
                if len(kept_words) != len(kept_word_ids):
                    blockers.append(
                        Blocker(
                            code="BOUNDARY_SUFFIX_PREFIX_OVERLAP_WORD_BINDING_MISSING",
                            message="boundary suffix-prefix overlap cleanup lost source word bindings",
                            layer="compiler",
                            context={
                                "left_segment_id": left.segment_id,
                                "right_segment_id": right.segment_id,
                                "overlap_text": overlap,
                                "kept_word_ids": kept_word_ids,
                            },
                        )
                    )
                    return current, blockers
                updated_left = replace(
                    left,
                    source_end_us=int(getattr(kept_words[-1], "source_end_us")),
                    word_ids=kept_word_ids,
                    text="".join(str(getattr(word, "text")) for word in kept_words),
                    decision_ids=sorted(set(left.decision_ids + ["final_cjk_boundary_suffix_prefix_overlap_cleanup"])),
                    spoken_source_start_us=None,
                    spoken_source_end_us=None,
                    clip_source_start_us=None,
                    clip_source_end_us=None,
                    lead_handle_us=0,
                    tail_handle_us=0,
                )
                current[index] = updated_left
                left_after = updated_left.text
            else:
                current = [segment for position, segment in enumerate(current) if position != index]
                left_after = ""
            decision_plan.decision_trace.append(
                {
                    "route": "final_cjk_boundary_suffix_prefix_overlap_cleanup",
                    "stage": "final_timeline_pre_emit",
                    "decision": "drop_left_overlap_suffix",
                    "applied": True,
                    "left_segment_id": left.segment_id,
                    "right_segment_id": right.segment_id,
                    "overlap_text": overlap,
                    "dropped_word_ids": drop_word_ids,
                    "left_text_before": left_before,
                    "left_text_after": left_after,
                    "right_text": right.text,
                    "reason": "left suffix repeats right prefix at final subtitle boundary",
                }
            )
            current = self._repack_target_timeline(current)
            changed = True
            break
        if not changed:
            return current, []


def _boundary_suffix_prefix_overlap(self, left_text: str, right_text: str) -> str:
    return boundary_suffix_prefix_overlap(left_text, right_text)


def _trailing_word_ids_for_overlap(
    self,
    segment: FinalTimelineSegment,
    word_lookup: dict[str, object],
    overlap: str,
) -> list[str]:
    selected: list[str] = []
    empty_selection: list[str] = []
    selected_text = ""
    for word_id in reversed(segment.word_ids):
        word = word_lookup.get(word_id)
        if word is None:
            return empty_selection
        selected.insert(0, word_id)
        selected_text = normalize_text(str(getattr(word, "text", "") or "")) + selected_text
        if len(selected_text) >= len(overlap):
            break
    return selected if selected_text == overlap else empty_selection
