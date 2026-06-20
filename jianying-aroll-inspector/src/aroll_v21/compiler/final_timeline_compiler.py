from __future__ import annotations

from dataclasses import replace

from aroll_adjacent_modifier_semantic_redundancy_gate import detect_adjacent_modifier_semantic_redundancy
from aroll_text_normalize import normalize_text
from aroll_v21.compiler import boundary_cleanup as boundary_cleanup_helpers
from aroll_v21.compiler import modifier_semantic_pass as modifier_semantic_pass_helpers
from aroll_v21.compiler import suffix_cleanup as suffix_cleanup_helpers
from aroll_v21.compiler.compiler_report import combine_compiler_blockers
from aroll_v21.compiler.rough_cut_quality_normalizer import RoughCutQualityNormalizer
from aroll_v21.compiler.segment_builder import (
    group_blockers,
    groups,
    source_order_blockers,
)
from aroll_v21.compiler.timeline_repack import (
    range_window_count,
    repack_segments,
    repack_target_timeline,
    source_windows,
    window_for_range,
)
from aroll_v21.compiler.unit_split_materializer import materialize_drop_and_split_decisions
from aroll_v21.decision.deterministic_baseline_policy import DeterministicBaselinePolicy
from aroll_v21.decision.semantic_decision_planner import FORBIDDEN_DEEPSEEK_FIELDS
from aroll_v21.decision.final_target_repeat_resolver import FinalTargetRepeatResolver
from aroll_v21.ir.models import Blocker, CanonicalSourceGraph, DecisionPlan, FinalTimelineSegment
from aroll_v21.quality.boundary_overlap import (
    boundary_suffix_prefix_overlap,
    is_semantic_label_reuse_boundary,
)


class FinalTimelineCompiler:
    """Single-pass compiler from source graph + semantic decisions to final timeline."""

    def __init__(self, *, rough_cut_normalizer: RoughCutQualityNormalizer | None = None) -> None:
        self.rough_cut_normalizer = rough_cut_normalizer or RoughCutQualityNormalizer()
        self.baseline_policy = DeterministicBaselinePolicy()

    def compile(
        self,
        source_graph: CanonicalSourceGraph,
        decision_plan: DecisionPlan,
    ) -> tuple[list[FinalTimelineSegment], list[Blocker]]:
        blockers: list[Blocker] = []
        if decision_plan.blocked:
            return [], list(decision_plan.blockers)

        materialized = materialize_drop_and_split_decisions(source_graph, decision_plan)
        if materialized.blockers:
            return [], materialized.blockers

        units_by_id = materialized.units_by_id
        dropped_word_ids = set(materialized.dropped_word_ids)
        decision_ids_by_word = materialized.decision_ids_by_word
        dropped_word_ids.update({word_id for unit_id in materialized.drop_unit_ids for word_id in units_by_id[unit_id].word_ids})
        kept_words = [word for word in source_graph.words if word.word_id not in dropped_word_ids]
        source_order_blockers = self._source_order_blockers(kept_words)
        if source_order_blockers:
            return [], source_order_blockers
        word_to_unit_id = {
            word_id: unit.unit_id
            for unit in source_graph.edit_units
            for word_id in unit.word_ids
        }
        kept_words.sort(key=lambda word: (word.source_start_us, word.source_end_us, word.word_id))
        segments: list[FinalTimelineSegment] = []
        target_cursor = 0
        for group in self._groups(kept_words, word_to_unit_id):
            group_blockers = self._group_blockers(group)
            if group_blockers:
                blockers.extend(group_blockers)
                continue
            source_start = group[0].source_start_us
            source_end = group[-1].source_end_us
            duration = source_end - source_start
            if duration <= 0:
                blockers.append(
                    Blocker(
                        code="FINAL_SEGMENT_EMPTY_SOURCE_RANGE",
                        message="compiled final segment has empty source range",
                        layer="compiler",
                        context={"word_ids": [word.word_id for word in group]},
                    )
                )
                continue
            word_ids = [word.word_id for word in group]
            decision_ids = sorted({decision_id for word_id in word_ids for decision_id in decision_ids_by_word.get(word_id, [])})
            segments.append(
                FinalTimelineSegment(
                    segment_id=f"v21_seg_{len(segments) + 1:06d}",
                    source_material_id="",
                    source_segment_id=None,
                    source_start_us=source_start,
                    source_end_us=source_end,
                    target_start_us=target_cursor,
                    target_end_us=target_cursor + duration,
                    word_ids=word_ids,
                    text="".join(word.text for word in group),
                    decision_ids=decision_ids,
                )
            )
            target_cursor += duration
        if not segments and source_graph.words:
            blockers.append(Blocker("FINAL_TIMELINE_EMPTY", "compiler produced no final timeline segments", "compiler"))
        if blockers:
            return segments, blockers
        segments, source_window_blockers = self._split_segments_by_source_windows(segments, source_graph)
        if source_window_blockers:
            return segments, source_window_blockers
        segments, pre_emit_blockers = self._pre_emit_boundary_prefix_normalization(segments, decision_plan)
        segments, final_target_blockers = FinalTargetRepeatResolver().resolve(segments, decision_plan)
        segments, rough_cut_blockers = self.rough_cut_normalizer.normalize(
            segments,
            source_graph,
            decision_plan,
            emit_residual_blockers=False,
        )
        segments, modifier_blockers, modifier_changed = self._final_modifier_redundancy_semantic_pass(
            segments,
            source_graph,
            decision_plan,
        )
        if modifier_changed:
            segments, rough_cut_after_modifier_blockers = self.rough_cut_normalizer.normalize(
                segments,
                source_graph,
                decision_plan,
                emit_residual_blockers=False,
            )
            rough_cut_blockers.extend(rough_cut_after_modifier_blockers)
        segments, adjacent_duplicate_blockers = self._post_normalizer_adjacent_exact_duplicate_cleanup(segments, decision_plan)
        segments, suffix_prefix_blockers = self._final_cjk_boundary_suffix_prefix_overlap_cleanup(
            segments,
            source_graph,
            decision_plan,
        )
        segments, repeated_island_blockers = self._final_repeated_island_suffix_cleanup(
            segments,
            source_graph,
            decision_plan,
        )
        segments, final_rough_cut_blockers = self.rough_cut_normalizer.normalize(
            segments,
            source_graph,
            decision_plan,
        )
        segments, late_final_target_blockers = FinalTargetRepeatResolver().resolve(segments, decision_plan)
        if late_final_target_blockers:
            final_rough_after_late_target_blockers: list[Blocker] = []
        else:
            segments, final_rough_after_late_target_blockers = self.rough_cut_normalizer.normalize(
                segments,
                source_graph,
                decision_plan,
            )
        final_source_window_blockers = self._final_source_window_blockers(segments, source_graph)
        return (
            segments,
            combine_compiler_blockers(
                source_window_blockers,
                pre_emit_blockers,
                final_target_blockers,
                rough_cut_blockers,
                modifier_blockers,
                adjacent_duplicate_blockers,
                suffix_prefix_blockers,
                repeated_island_blockers,
                final_rough_cut_blockers,
                late_final_target_blockers,
                final_rough_after_late_target_blockers,
                final_source_window_blockers,
            ),
        )

    def _split_segments_by_source_windows(
        self,
        segments: list[FinalTimelineSegment],
        source_graph: CanonicalSourceGraph,
    ) -> tuple[list[FinalTimelineSegment], list[Blocker]]:
        windows = self._source_windows(source_graph)
        if not windows:
            return segments, []
        word_lookup = {word.word_id: word for word in source_graph.words}
        split_segments: list[FinalTimelineSegment] = []
        blockers: list[Blocker] = []
        for segment in segments:
            if self._range_window_count(windows, segment.source_start_us, segment.source_end_us) == 1:
                split_segments.append(segment)
                continue
            grouped: list[list[str]] = []
            current_window: tuple[int, int] | None = None
            for word_id in segment.word_ids:
                word = word_lookup.get(word_id)
                if word is None:
                    continue
                word_window = self._window_for_range(windows, int(word.source_start_us), int(word.source_end_us))
                if word_window is None:
                    grouped = []
                    break
                if current_window != word_window:
                    grouped.append([])
                    current_window = word_window
                grouped[-1].append(word_id)
            if blockers:
                continue
            grouped = [group for group in grouped if group]
            if len(grouped) <= 1:
                blockers.append(
                    Blocker(
                        "V21_FINAL_SEGMENT_CROSSES_PRIMARY_SOURCE_WINDOW",
                        "final segment crosses primary video source windows but cannot be split on word boundaries",
                        "compiler",
                        context={"segment_id": segment.segment_id, "word_ids": segment.word_ids},
                    )
                )
                continue
            for group in grouped:
                words = [word_lookup[word_id] for word_id in group if word_id in word_lookup]
                if not words:
                    continue
                split_segments.append(
                    replace(
                        segment,
                        source_start_us=min(word.source_start_us for word in words),
                        source_end_us=max(word.source_end_us for word in words),
                        target_start_us=0,
                        target_end_us=0,
                        word_ids=list(group),
                        text="".join(word.text for word in words),
                    )
                )
        if blockers:
            return split_segments, blockers
        return self._repack_segments(split_segments), []

    def _final_source_window_blockers(
        self,
        segments: list[FinalTimelineSegment],
        source_graph: CanonicalSourceGraph,
    ) -> list[Blocker]:
        windows = self._source_windows(source_graph)
        if not windows:
            return list()
        blockers: list[Blocker] = []
        for segment in segments:
            start = int(segment.clip_source_start_us if segment.clip_source_start_us is not None else segment.source_start_us)
            end = int(segment.clip_source_end_us if segment.clip_source_end_us is not None else segment.source_end_us)
            count = self._range_window_count(windows, start, end)
            if count == 0:
                blockers.append(
                    Blocker(
                        "V21_FINAL_SEGMENT_SOURCE_WINDOW_UNRESOLVED",
                        "final segment clip range is not covered by a primary source window",
                        "compiler",
                        context={"segment_id": segment.segment_id, "clip_source_start_us": start, "clip_source_end_us": end},
                    )
                )
            elif count > 1:
                blockers.append(
                    Blocker(
                        "V21_FINAL_SEGMENT_SOURCE_WINDOW_AMBIGUOUS",
                        "final segment clip range is covered by multiple primary source windows",
                        "compiler",
                        context={"segment_id": segment.segment_id, "clip_source_start_us": start, "clip_source_end_us": end},
                    )
                )
        return blockers

    def _source_windows(self, source_graph: CanonicalSourceGraph) -> list[tuple[int, int]]:
        return source_windows(source_graph)

    def _window_for_range(self, windows: list[tuple[int, int]], start: int, end: int) -> tuple[int, int] | None:
        return window_for_range(windows, start, end)

    def _range_window_count(self, windows: list[tuple[int, int]], start: int, end: int) -> int:
        return range_window_count(windows, start, end)

    def _repack_segments(self, segments: list[FinalTimelineSegment]) -> list[FinalTimelineSegment]:
        return repack_segments(segments)

    def _repack_target_timeline(self, segments: list[FinalTimelineSegment]) -> list[FinalTimelineSegment]:
        return repack_target_timeline(segments)

    def _groups(self, words, word_to_unit_id: dict[str, str]):
        yield from groups(words, word_to_unit_id)

    def _source_order_blockers(self, words) -> list[Blocker]:
        return source_order_blockers(words)

    def _group_blockers(self, group) -> list[Blocker]:
        return group_blockers(group)

def _bind_final_timeline_compiler_helpers() -> None:
    dependencies = globals()
    boundary_cleanup_helpers.configure_compiler_dependencies(dependencies)
    suffix_cleanup_helpers.configure_compiler_dependencies(dependencies)
    modifier_semantic_pass_helpers.configure_compiler_dependencies(dependencies)
    FinalTimelineCompiler._pre_emit_boundary_prefix_normalization = boundary_cleanup_helpers._pre_emit_boundary_prefix_normalization  # type: ignore[method-assign]
    FinalTimelineCompiler._safe_pre_emit_boundary_prefix_drop = boundary_cleanup_helpers._safe_pre_emit_boundary_prefix_drop  # type: ignore[method-assign]
    FinalTimelineCompiler._post_normalizer_adjacent_exact_duplicate_cleanup = boundary_cleanup_helpers._post_normalizer_adjacent_exact_duplicate_cleanup  # type: ignore[method-assign]
    FinalTimelineCompiler._final_cjk_boundary_suffix_prefix_overlap_cleanup = boundary_cleanup_helpers._final_cjk_boundary_suffix_prefix_overlap_cleanup  # type: ignore[method-assign]
    FinalTimelineCompiler._boundary_suffix_prefix_overlap = boundary_cleanup_helpers._boundary_suffix_prefix_overlap  # type: ignore[method-assign]
    FinalTimelineCompiler._trailing_word_ids_for_overlap = boundary_cleanup_helpers._trailing_word_ids_for_overlap  # type: ignore[method-assign]
    FinalTimelineCompiler._final_repeated_island_suffix_cleanup = suffix_cleanup_helpers._final_repeated_island_suffix_cleanup  # type: ignore[method-assign]
    FinalTimelineCompiler._drop_repeated_suffix_islands_by_subtitle = suffix_cleanup_helpers._drop_repeated_suffix_islands_by_subtitle  # type: ignore[method-assign]
    FinalTimelineCompiler._drop_repeated_suffix_island = suffix_cleanup_helpers._drop_repeated_suffix_island  # type: ignore[method-assign]
    FinalTimelineCompiler._repeated_suffix_island_start = suffix_cleanup_helpers._repeated_suffix_island_start  # type: ignore[method-assign]
    FinalTimelineCompiler._final_modifier_redundancy_semantic_pass = modifier_semantic_pass_helpers._final_modifier_redundancy_semantic_pass  # type: ignore[method-assign]
    FinalTimelineCompiler._existing_modifier_payload_cluster_id = modifier_semantic_pass_helpers._existing_modifier_payload_cluster_id  # type: ignore[method-assign]
    FinalTimelineCompiler._final_modifier_candidates = modifier_semantic_pass_helpers._final_modifier_candidates  # type: ignore[method-assign]
    FinalTimelineCompiler._modifier_cluster_id = modifier_semantic_pass_helpers._modifier_cluster_id  # type: ignore[method-assign]
    FinalTimelineCompiler._semantic_decision_row = modifier_semantic_pass_helpers._semantic_decision_row  # type: ignore[method-assign]
    FinalTimelineCompiler._deterministic_baseline_enabled = modifier_semantic_pass_helpers._deterministic_baseline_enabled  # type: ignore[method-assign]
    FinalTimelineCompiler._append_modifier_semantic_request = modifier_semantic_pass_helpers._append_modifier_semantic_request  # type: ignore[method-assign]
    FinalTimelineCompiler._drop_redundant_modifier_from_segment = modifier_semantic_pass_helpers._drop_redundant_modifier_from_segment  # type: ignore[method-assign]
    FinalTimelineCompiler._word_ids_for_char_span = modifier_semantic_pass_helpers._word_ids_for_char_span  # type: ignore[method-assign]
    FinalTimelineCompiler._set_plan_list = modifier_semantic_pass_helpers._set_plan_list  # type: ignore[method-assign]


_bind_final_timeline_compiler_helpers()
