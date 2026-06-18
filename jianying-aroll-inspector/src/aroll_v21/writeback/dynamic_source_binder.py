from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aroll_v21.ingest.real_draft_adapter import RealDraftIngestResult
from aroll_v21.ir.models import CanonicalSourceGraph, FinalTimelineSegment
from aroll_v21.writeback.source_segment_template_resolver import (
    SOURCE_TEMPLATE_REPORT_DEFAULTS,
    SourceSegmentTemplateResolution,
    SourceSegmentTemplateResolver,
)


@dataclass(frozen=True)
class CurrentDraftInventory:
    draft_dir: str = ""
    active_timeline_id: str = ""
    timeline_dir: str = ""
    draft_content_path: str = ""
    template_path: str = ""
    video_segments: list[dict[str, Any]] = field(default_factory=list)
    video_materials: list[dict[str, Any]] = field(default_factory=list)
    draft_data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_real_draft_result(cls, result: RealDraftIngestResult, *, draft_dir: Path | None = None) -> "CurrentDraftInventory":
        metadata = result.metadata or {}
        return cls(
            draft_dir=str(draft_dir or metadata.get("draft_dir") or ""),
            active_timeline_id=str(metadata.get("timeline_id") or ""),
            timeline_dir=str(metadata.get("timeline_dir") or ""),
            draft_content_path=str(metadata.get("draft_content_path") or ""),
            template_path=str(metadata.get("template_path") or ""),
            video_segments=list(result.source_segments or []),
            video_materials=list(result.source_materials or []),
            draft_data=dict(result.draft_data or {}),
        )


class DynamicSourceBinder:
    """Bind logical final timeline source times to current-draft video templates."""

    def __init__(self, inventory: CurrentDraftInventory) -> None:
        self.inventory = inventory
        self._resolver = SourceSegmentTemplateResolver(
            current_source_segments=inventory.video_segments,
            current_source_materials=inventory.video_materials,
            current_draft_data=inventory.draft_data,
        )

    def bind(
        self,
        final_timeline: list[FinalTimelineSegment],
        source_graph: CanonicalSourceGraph | None,
    ) -> SourceSegmentTemplateResolution:
        return self._resolver.resolve(final_timeline, source_graph)

    def candidate_index_report(self) -> dict[str, Any]:
        report = dict(SOURCE_TEMPLATE_REPORT_DEFAULTS)
        report.update(self._resolver.candidate_index_report())
        return report
