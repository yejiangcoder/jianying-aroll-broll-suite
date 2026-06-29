from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from aroll_text_normalize import normalize_text
from aroll_v21.ir.models import CanonicalSourceGraph, CaptionRenderUnit, FinalTimelineSegment
from aroll_v21.quality.final_caption_visible_repeat import build_final_caption_visible_repeat_gate
from aroll_v21.quality.final_visible_repair.context import FinalVisibleRepairContext
from aroll_v21.quality.final_visible_repair.pipeline import FinalVisibleRepairState
from aroll_v21.quality.final_visible_repair.report import _action
from aroll_v21.quality.final_visible_repair.result import _RepairStep
from aroll_v21.quality.final_visible_repair.rules.word_span_edit import _drop_or_trim_caption_words
from aroll_v21.quality.final_visible_repair.timeline_utils import (
    caption_by_id as _caption_by_id,
    ordered_captions as _ordered_captions,
)
from aroll_v21.quality.pre_visible_semantic_junk_candidate_detector import (
    MIN_HIGH_CONFIDENCE as PRE_VISIBLE_SEMANTIC_JUNK_MIN_HIGH_CONFIDENCE,
    build_pre_visible_semantic_junk_candidate_report,
)


MAX_ISOLATED_SHORT_FRAGMENT_CHARS = 4


MAX_ISOLATED_SHORT_FRAGMENT_DURATION_US = 1_200_000


MIN_ISOLATED_SHORT_FRAGMENT_SOURCE_GAP_US = 300_000
MAX_COMMAND_TAIL_SOURCE_GAP_US = 700_000


MIN_ISOLATED_SHORT_FRAGMENT_NEIGHBOR_CHARS = 5
ACTION_ASPECT_TAILS = ("着", "了", "过")
DEPENDENT_OBJECT_HEAD_PREFIXES = tuple("个件条张节款台辆本套部名位份颗枚只")
LOW_INFORMATION_FRAGMENT_TAILS = ("的", "就", "是", "在", "把", "给", "去", "来", "这个", "那个")
COMMAND_OR_DIRECTIVE_MARKERS = (
    "立刻",
    "马上",
    "赶紧",
    "赶快",
    "别",
    "不要",
    "给我",
    "给",
    "把",
    "滚",
)
COMMAND_COMPLETION_TAILS = ("了", "掉", "完", "走", "开", "下去", "起来")
REACTION_TAIL_MARKERS = ("哼", "呵", "哈", "笑", "笑一声", "冷笑", "骂一句", "说一句")
EXPRESSIVE_SHORT_TAILS = ("了", "嘛", "啊", "呀", "吧")


def _caption_ids_with_dangling_boundary_candidates(captions: list[CaptionRenderUnit]) -> set[str]:
    gate = build_final_caption_visible_repeat_gate(captions)
    ids: set[str] = set()
    for candidate in list(gate.get("dangling_prefix_suffix_candidates") or []):
        for key in ("caption_id", "related_caption_id"):
            value = str(candidate.get(key) or "")
            if value:
                ids.add(value)
        for value in list(candidate.get("affected_caption_ids") or []):
            if value:
                ids.add(str(value))
    return ids


def _caption_source_range(
    caption: CaptionRenderUnit,
    source_graph: CanonicalSourceGraph,
) -> tuple[int, int] | None:
    words_by_id = {word.word_id: word for word in source_graph.words}
    words = [words_by_id[word_id] for word_id in caption.word_ids if word_id in words_by_id]
    if not words or len(words) != len(caption.word_ids):
        no_range: tuple[int, int] | None = None
        return no_range
    start_us = min(int(getattr(word, "source_start_us", 0) or 0) for word in words)
    end_us = max(int(getattr(word, "source_end_us", 0) or 0) for word in words)
    if end_us <= start_us:
        no_range: tuple[int, int] | None = None
        return no_range
    return start_us, end_us


@dataclass(frozen=True)
class PreVisibleSemanticJunkCandidateRule:
    repair_pre_visible_semantic_junk_candidate: Callable[..., _RepairStep | None]
    name: str = "pre_visible_semantic_junk_candidate"

    def try_repair(
        self,
        *,
        context: FinalVisibleRepairContext,
        state: FinalVisibleRepairState,
        pass_index: int,
    ) -> _RepairStep | None:
        return self.repair_pre_visible_semantic_junk_candidate(
            final_timeline=state.final_timeline,
            captions=state.captions,
            source_graph=context.source_graph,
            pass_index=pass_index,
        )


@dataclass(frozen=True)
class IsolatedSemanticJunkCaptionRule:
    repair_isolated_semantic_junk_caption: Callable[..., _RepairStep | None]
    name: str = "isolated_semantic_junk_caption"

    def try_repair(
        self,
        *,
        context: FinalVisibleRepairContext,
        state: FinalVisibleRepairState,
        pass_index: int,
    ) -> _RepairStep | None:
        return self.repair_isolated_semantic_junk_caption(
            final_timeline=state.final_timeline,
            captions=state.captions,
            source_graph=context.source_graph,
            pass_index=pass_index,
        )


def _repair_pre_visible_semantic_junk_candidate(
    *,
    final_timeline: list[FinalTimelineSegment],
    captions: list[CaptionRenderUnit],
    source_graph: CanonicalSourceGraph,
    pass_index: int,
) -> _RepairStep | None:
    report = build_pre_visible_semantic_junk_candidate_report(captions, source_graph)
    for candidate in list(report.get("pre_visible_semantic_junk_candidates") or []):
        if not _is_deterministic_pre_visible_semantic_junk_drop(candidate):
            continue
        caption_ids = [str(value) for value in list(candidate.get("target_caption_ids") or []) if str(value)]
        if len(caption_ids) != 1:
            continue
        caption = _caption_by_id(captions, caption_ids[0])
        if caption is None:
            continue
        target_word_ids = [str(value) for value in list(candidate.get("target_word_ids") or []) if str(value)]
        if target_word_ids and list(caption.word_ids) != target_word_ids:
            continue
        dropped = _drop_or_trim_caption_words(final_timeline, captions, source_graph, caption)
        if dropped is None:
            continue
        repaired_timeline, dropped_segment_ids, trimmed_segment_ids = dropped
        decision = (
            "drop_high_confidence_semantic_junk_segment"
            if dropped_segment_ids
            else "trim_high_confidence_semantic_junk_words"
        )
        return _RepairStep(
            final_timeline=repaired_timeline,
            captions=captions,
            timeline_changed=True,
            action=_action(
                "pre_visible_semantic_junk_candidate",
                decision,
                pass_index,
                {
                    "caption_id": caption.caption_id,
                    "related_caption_id": str(candidate.get("candidate_id") or ""),
                    "reason": str(candidate.get("type") or ""),
                    "overlap_text": str(candidate.get("visible_text") or ""),
                },
                affected_caption_ids=[caption.caption_id],
                candidate_id=str(candidate.get("candidate_id") or ""),
                candidate_type=str(candidate.get("type") or ""),
                proposed_action=str(candidate.get("proposed_action") or ""),
                local_confidence=float(candidate.get("local_confidence") or 0.0),
                provider_required=bool(candidate.get("provider_required")),
                safety_tags=list(candidate.get("safety_tags") or []),
                evidence=dict(candidate.get("evidence") or {}),
                dropped_segment_ids=dropped_segment_ids,
                trimmed_segment_ids=trimmed_segment_ids,
                dropped_word_ids=list(caption.word_ids),
                dropped_text=str(caption.text or ""),
                native_words_text=str(candidate.get("native_words_text") or ""),
            ),
        )
    no_step: _RepairStep | None = None
    return no_step


def _is_deterministic_pre_visible_semantic_junk_drop(candidate: dict[str, Any]) -> bool:
    if str(candidate.get("proposed_action") or "") != "drop_fragment":
        return False
    if bool(candidate.get("provider_required")):
        return False
    if float(candidate.get("local_confidence") or 0.0) < PRE_VISIBLE_SEMANTIC_JUNK_MIN_HIGH_CONFIDENCE:
        return False
    if str(candidate.get("type") or "") not in {
        "aborted_restart",
        "adjacent_reordered_semantic_restart",
        "adjacent_suffix_semantic_recurrence",
        "lookahead_contained_short_fragment",
        "lookahead_nominal_restart_fragment",
        "prefix_restart",
        "standalone_topic_prefix_restart",
    }:
        return False
    safety_tags = {str(value) for value in list(candidate.get("safety_tags") or [])}
    return "drop_audio_and_caption_together" in safety_tags


def _repair_isolated_semantic_junk_caption(
    *,
    final_timeline: list[FinalTimelineSegment],
    captions: list[CaptionRenderUnit],
    source_graph: CanonicalSourceGraph,
    pass_index: int,
) -> _RepairStep | None:
    ordered = _ordered_captions(captions)
    if len(ordered) < 3:
        no_step: _RepairStep | None = None
        return no_step
    dangling_caption_ids = _caption_ids_with_dangling_boundary_candidates(ordered)
    for index, caption in enumerate(ordered):
        if index == 0 or index == len(ordered) - 1:
            continue
        if caption.caption_id in dangling_caption_ids:
            continue
        if not _is_isolated_short_source_gap_fragment(ordered, index, source_graph):
            continue
        text = normalize_text(str(caption.text or ""))
        dropped = _drop_or_trim_caption_words(final_timeline, captions, source_graph, caption)
        if dropped is None:
            continue
        repaired_timeline, dropped_segment_ids, trimmed_segment_ids = dropped
        decision = "drop_isolated_junk_segment" if dropped_segment_ids else "trim_isolated_junk_words"
        return _RepairStep(
            final_timeline=repaired_timeline,
            captions=captions,
            timeline_changed=True,
            action=_action(
                "isolated_semantic_junk_caption",
                decision,
                pass_index,
                {
                    "caption_id": caption.caption_id,
                    "related_caption_id": caption.caption_id,
                    "reason": "isolated_semantic_junk_caption",
                    "overlap_text": text,
                },
                affected_caption_ids=[caption.caption_id],
                dropped_segment_ids=dropped_segment_ids,
                trimmed_segment_ids=trimmed_segment_ids,
                dropped_word_ids=list(caption.word_ids),
                junk_text=str(caption.text or ""),
            ),
        )
    no_step: _RepairStep | None = None
    return no_step


def _is_isolated_short_source_gap_fragment(
    ordered: list[CaptionRenderUnit],
    index: int,
    source_graph: CanonicalSourceGraph,
) -> bool:
    caption = ordered[index]
    text = normalize_text(str(caption.text or ""))
    if not (2 <= len(text) <= MAX_ISOLATED_SHORT_FRAGMENT_CHARS):
        return False
    if not text or not all("\u4e00" <= char <= "\u9fff" for char in text):
        return False
    if len(text) > 3 and not _looks_like_low_information_isolated_fragment(text):
        return False
    duration_us = int(caption.target_end_us) - int(caption.target_start_us)
    if duration_us <= 0 or duration_us > MAX_ISOLATED_SHORT_FRAGMENT_DURATION_US:
        return False
    previous = ordered[index - 1]
    next_caption = ordered[index + 1]
    previous_text = normalize_text(str(previous.text or ""))
    next_text = normalize_text(str(next_caption.text or ""))
    if _looks_like_action_fragment_before_dependent_object(text, next_text):
        return False
    if len(previous_text) < MIN_ISOLATED_SHORT_FRAGMENT_NEIGHBOR_CHARS:
        return False
    if len(next_text) < MIN_ISOLATED_SHORT_FRAGMENT_NEIGHBOR_CHARS:
        return False
    if text in previous_text or text in next_text or previous_text.endswith(text) or next_text.startswith(text):
        return False
    previous_range = _caption_source_range(previous, source_graph)
    current_range = _caption_source_range(caption, source_graph)
    next_range = _caption_source_range(next_caption, source_graph)
    if previous_range is None or current_range is None or next_range is None:
        return False
    previous_gap_us = current_range[0] - previous_range[1]
    next_gap_us = next_range[0] - current_range[1]
    if _looks_like_dependent_tail_after_command(previous_text, text, previous_gap_us):
        return False
    if _looks_like_expressive_tail_after_reaction(previous_text, text, previous_gap_us):
        return False
    return (
        previous_gap_us >= MIN_ISOLATED_SHORT_FRAGMENT_SOURCE_GAP_US
        and next_gap_us >= MIN_ISOLATED_SHORT_FRAGMENT_SOURCE_GAP_US
    )


def _looks_like_action_fragment_before_dependent_object(text: str, next_text: str) -> bool:
    if len(text) < 2 or not next_text:
        return False
    if not text.endswith(ACTION_ASPECT_TAILS):
        return False
    return next_text[0] in DEPENDENT_OBJECT_HEAD_PREFIXES


def _looks_like_low_information_isolated_fragment(text: str) -> bool:
    return any(text.endswith(tail) for tail in LOW_INFORMATION_FRAGMENT_TAILS)


def _looks_like_dependent_tail_after_command(previous_text: str, text: str, previous_gap_us: int) -> bool:
    if previous_gap_us < 0 or previous_gap_us > MAX_COMMAND_TAIL_SOURCE_GAP_US:
        return False
    if not (2 <= len(text) <= MAX_ISOLATED_SHORT_FRAGMENT_CHARS):
        return False
    if _looks_like_low_information_isolated_fragment(text):
        return False
    if any(text.endswith(tail) for tail in LOW_INFORMATION_FRAGMENT_TAILS):
        return False
    if not previous_text:
        return False
    if not any(marker in previous_text for marker in COMMAND_OR_DIRECTIVE_MARKERS):
        return False
    return previous_text.endswith(COMMAND_COMPLETION_TAILS)


def _looks_like_expressive_tail_after_reaction(previous_text: str, text: str, previous_gap_us: int) -> bool:
    if previous_gap_us < 0 or previous_gap_us > MAX_COMMAND_TAIL_SOURCE_GAP_US:
        return False
    if not (2 <= len(text) <= MAX_ISOLATED_SHORT_FRAGMENT_CHARS):
        return False
    if not text.endswith(EXPRESSIVE_SHORT_TAILS):
        return False
    if not previous_text:
        return False
    tail_context = previous_text[-8:]
    return any(marker in tail_context for marker in REACTION_TAIL_MARKERS)
