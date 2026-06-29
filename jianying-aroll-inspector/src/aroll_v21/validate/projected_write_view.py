from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Iterator

from aroll_v21.ir.models import (
    BlockerReport,
    CanonicalSourceGraph,
    CaptionRenderUnit,
    DecisionPlan,
    FinalTimelineSegment,
    RunReport,
)
from aroll_v21.writeback import video_projection as video_projection_helpers
from aroll_v21.writeback.video_write_plan_projector import SafeHandlePolicy


class ProjectedWriteViewError(RuntimeError):
    def __init__(self, code: str, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context or {}


@dataclass(frozen=True)
class ProjectedWriteView:
    final_timeline: list[FinalTimelineSegment]
    captions: list[CaptionRenderUnit]
    material_write_plan: dict[str, Any]
    report: dict[str, Any]


class _ProjectionAdapter:
    _gapless_caption_video_projection_plan = video_projection_helpers._gapless_caption_video_projection_plan
    _caption_final_segment_ids = video_projection_helpers._caption_final_segment_ids
    _final_segment_video_projection_groups = video_projection_helpers._final_segment_video_projection_groups
    _gapless_projection_group_handles = video_projection_helpers._gapless_projection_group_handles
    _caption_ids_for_word_group = video_projection_helpers._caption_ids_for_word_group
    _apply_caption_ranges_for_projected_segment = video_projection_helpers._apply_caption_ranges_for_projected_segment
    _project_caption_word_span_to_group = video_projection_helpers._project_caption_word_span_to_group
    _merge_caption_target_range = video_projection_helpers._merge_caption_target_range

    def _ranges_overlap(self, left_start: int, left_end: int, right_start: int, right_end: int) -> bool:
        return int(left_start) < int(right_end) and int(left_end) > int(right_start)


@contextmanager
def _projection_dependencies() -> Iterator[None]:
    keys = ("FinalTimelineSegment", "CaptionRenderUnit", "RunReport", "WritebackError")
    previous = {key: getattr(video_projection_helpers, key, None) for key in keys}
    missing = {key for key in keys if not hasattr(video_projection_helpers, key)}
    video_projection_helpers.configure_writeback_dependencies(
        {
            "FinalTimelineSegment": FinalTimelineSegment,
            "CaptionRenderUnit": CaptionRenderUnit,
            "RunReport": RunReport,
            "WritebackError": ProjectedWriteViewError,
        }
    )
    try:
        yield
    finally:
        for key in keys:
            if key in missing:
                video_projection_helpers.__dict__.pop(key, None)
            else:
                video_projection_helpers.__dict__[key] = previous[key]


def build_projected_write_view(
    *,
    source_graph: CanonicalSourceGraph,
    decision_plan: DecisionPlan | None,
    final_timeline: list[FinalTimelineSegment],
    captions: list[CaptionRenderUnit],
    material_write_plan: dict[str, Any],
) -> ProjectedWriteView:
    run_report = RunReport(
        status="ok",
        source_graph=source_graph,
        repeat_clusters=[],
        decision_plan=decision_plan,
        final_timeline=list(final_timeline),
        captions=list(captions),
        material_write_plan=deepcopy(material_write_plan),
        validator_report={},
        postwrite_report={},
        blocker_report=BlockerReport(blocked=False, blockers=[]),
    )
    with _projection_dependencies():
        projection = _ProjectionAdapter()._gapless_caption_video_projection_plan(run_report)
    safe_handle_policy = SafeHandlePolicy()
    projected_timeline = []
    for segment in list(projection.get("video_units") or []):
        handle_projection = safe_handle_policy.project(segment)
        projected_timeline.append(
            replace(
                segment,
                source_start_us=int(handle_projection.source_start_us),
                source_end_us=int(handle_projection.source_end_us),
                target_start_us=int(handle_projection.target_start_us),
                target_end_us=int(handle_projection.target_end_us),
                clip_source_start_us=int(handle_projection.source_start_us),
                clip_source_end_us=int(handle_projection.source_end_us),
                lead_handle_us=int(handle_projection.lead_applied_us),
                tail_handle_us=int(handle_projection.tail_applied_us),
            )
        )
    caption_ranges = {
        str(caption_id): row
        for caption_id, row in dict(projection.get("caption_target_ranges") or {}).items()
        if isinstance(row, dict)
    }
    projected_captions = [
        replace(
            caption,
            target_start_us=int(caption_ranges[str(caption.caption_id)]["target_start_us"]),
            target_end_us=int(caption_ranges[str(caption.caption_id)]["target_end_us"]),
        )
        for caption in captions
        if str(caption.caption_id) in caption_ranges
    ]
    projected_material_write_plan = deepcopy(material_write_plan)
    projected_segments = list(projected_material_write_plan.get("segments") or [])
    for caption, segment in zip(projected_captions, projected_segments):
        segment["target_timerange"] = {
            "start": int(caption.target_start_us),
            "duration": max(0, int(caption.target_end_us) - int(caption.target_start_us)),
        }
    projected_material_write_plan["segments"] = projected_segments
    report = {
        "prewrite_projected_write_view_applied": True,
        "prewrite_projection_video_write_plan_gapless": bool(projection.get("video_write_plan_gapless")),
        "prewrite_projection_final_timeline_count": len(projected_timeline),
        "prewrite_projection_caption_count": len(projected_captions),
        "prewrite_projection_caption_repacked_count": int(projection.get("caption_repacked_count") or 0),
        "prewrite_projection_short_video_segment_count": sum(
            1
            for segment in projected_timeline
            if int(segment.target_end_us) - int(segment.target_start_us) < 300_000
        ),
        "prewrite_projection_short_caption_count": sum(
            1
            for caption in projected_captions
            if int(caption.target_end_us) - int(caption.target_start_us) < 300_000
        ),
    }
    return ProjectedWriteView(
        final_timeline=projected_timeline,
        captions=projected_captions,
        material_write_plan=projected_material_write_plan,
        report=report,
    )
