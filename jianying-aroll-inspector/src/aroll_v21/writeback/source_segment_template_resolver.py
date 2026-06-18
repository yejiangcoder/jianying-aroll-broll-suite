from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aroll_v21.ir.models import Blocker, CanonicalSourceGraph, FinalTimelineSegment


SOURCE_TEMPLATE_REPORT_DEFAULTS: dict[str, Any] = {
    "source_segment_template_exact_match_count": 0,
    "source_segment_template_rebind_count": 0,
    "source_segment_template_missing_count": 0,
    "source_segment_template_ambiguous_count": 0,
    "source_segment_template_rebound": False,
    "source_segment_template_rebind_samples": [],
    "resolved_template_map_count": 0,
    "current_draft_video_track_count": 0,
    "current_draft_video_segment_count": 0,
    "current_draft_video_material_count": 0,
    "current_source_template_candidate_count": 0,
    "current_source_template_candidate_samples": [],
    "primary_video_track_id": "",
    "primary_video_candidate_count": 0,
    "primary_video_track_candidate_count": 0,
    "primary_video_selection_reason": "",
    "invalid_duration_field_count": 0,
    "invalid_duration_fields": [],
    "rejected_duration_values": [],
    "rebind_rejection_reasons": {
        "media_identity_mismatch": 0,
        "source_range_not_covered": 0,
        "duration_mismatch": 0,
        "duration_unparseable": 0,
        "ambiguous": 0,
    },
}
EMPTY_SOURCE_TEMPLATE_CANDIDATES: list[dict[str, Any]] = []
EMPTY_SOURCE_TEMPLATE_MATCHES: list["SourceTemplateCandidateMatch"] = []
NO_SOURCE_RANGE: tuple[int, int] | None = None
NO_DURATION_US: int | None = None
NO_IDENTITY_MATCH: str | None = None


@dataclass(frozen=True)
class SourceTemplateCandidateMatch:
    template: dict[str, Any]
    match_strength: str
    match_reason: str


@dataclass(frozen=True)
class SourceSegmentTemplateResolution:
    success: bool
    templates_by_final_segment_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    resolved_templates: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[Blocker] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)


class SourceSegmentTemplateResolver:
    """Bind logical V21 source-time ranges against the current draft primary video."""

    def __init__(
        self,
        *,
        current_source_segments: list[dict[str, Any]],
        current_source_materials: list[dict[str, Any]],
        current_draft_data: dict[str, Any] | None = None,
    ) -> None:
        self.current_draft_data = current_draft_data or {}
        self.duration_parse_report = {
            "invalid_duration_field_count": 0,
            "invalid_duration_fields": [],
            "rejected_duration_values": [],
        }
        draft_video_materials = self._draft_video_materials(self.current_draft_data)
        draft_video_segments = self._draft_video_segments(self.current_draft_data)
        self.current_material_by_id = self._material_index([*current_source_materials, *draft_video_materials])
        self.all_source_template_candidates = self._source_template_candidates(current_source_segments, draft_video_segments)
        self.primary_blocker: Blocker | None = None
        self.primary_video_track_id = ""
        self.current_source_segments = self._primary_video_candidates(self.all_source_template_candidates)
        self.current_draft_video_track_count = self._draft_video_track_count(self.current_draft_data)
        self.current_draft_video_segment_count = len(draft_video_segments)
        self.current_draft_video_material_count = len({self._material_id(row) or str(row.get("id") or "") for row in draft_video_materials})

    def resolve(
        self,
        final_timeline: list[FinalTimelineSegment],
        source_graph: CanonicalSourceGraph | None,
    ) -> SourceSegmentTemplateResolution:
        source_materials = [row for row in ((source_graph.source_materials if source_graph else []) or []) if isinstance(row, dict)]
        report = self.candidate_index_report()
        report["source_segment_template_exact_match_count"] = 0
        report["source_segment_template_rebind_count"] = 0
        report["source_segment_template_missing_count"] = 0
        report["source_segment_template_ambiguous_count"] = 0
        report["source_segment_template_rebound"] = False
        report["source_segment_template_rebind_samples"] = []
        report["rebind_rejection_reasons"] = dict(SOURCE_TEMPLATE_REPORT_DEFAULTS["rebind_rejection_reasons"])
        report["resolved_template_map"] = {}
        report["resolved_template_map_count"] = 0
        templates_by_final_id: dict[str, dict[str, Any]] = {}
        resolved_template_map: dict[str, dict[str, Any]] = {}
        resolved_templates: list[dict[str, Any]] = []
        blockers: list[Blocker] = []
        if self.duration_parse_report["invalid_duration_field_count"]:
            report.update(self.duration_parse_report)
        if self.primary_blocker is not None:
            report["source_segment_template_available"] = False
            blocker = self.primary_blocker
            return SourceSegmentTemplateResolution(
                success=False,
                templates_by_final_segment_id=templates_by_final_id,
                resolved_templates=resolved_templates,
                blockers=[Blocker(blocker.code, blocker.message, blocker.layer, blocker.severity, report | blocker.context)],
                report=report | blocker.context,
            )
        if not self.current_source_segments:
            report["source_segment_template_available"] = False
            blockers.append(
                Blocker(
                    code="V21_DYNAMIC_BINDING_CANDIDATE_INDEX_EMPTY",
                    message="current draft has no source video segment templates available for V21 writeback",
                    layer="writeback",
                    context=report
                    | {
                        "reason": "current draft source template candidate index is empty",
                    },
                )
            )
            return SourceSegmentTemplateResolution(
                success=False,
                templates_by_final_segment_id=templates_by_final_id,
                resolved_templates=resolved_templates,
                blockers=blockers,
                report=report,
            )

        for segment in final_timeline:
            logical_source_segment_id = str(getattr(segment, "source_segment_id", None) or "")
            if logical_source_segment_id:
                blockers.append(
                    Blocker(
                        code="V21_DYNAMIC_BINDING_FORBIDS_LOGICAL_SOURCE_SEGMENT_ID",
                        message="logical final_timeline must not carry source_segment_id as binding truth",
                        layer="writeback",
                        context={
                            "segment_id": segment.segment_id,
                            "source_segment_id": logical_source_segment_id,
                            "reason": "dynamic binding only accepts source time ranges and current draft inventory",
                        },
                    )
                )
                continue

            candidates = self._rebind_candidates(
                segment,
                source_materials=source_materials,
                report=report,
            )
            if report.get("duration_unparseable_required"):
                report["source_segment_template_missing_count"] += 1
                blockers.append(
                    Blocker(
                        code="V21_DYNAMIC_BINDING_DURATION_UNPARSEABLE",
                        message="dynamic binding requires a parseable source duration but current draft duration is invalid",
                        layer="writeback",
                        context={
                            "segment_id": segment.segment_id,
                            "source_start_us": int(segment.source_start_us),
                            "source_end_us": int(segment.source_end_us),
                            "invalid_duration_fields": report.get("invalid_duration_fields") or [],
                            "rejected_duration_values": report.get("rejected_duration_values") or [],
                        },
                    )
                )
                continue
            if not candidates:
                report["source_segment_template_missing_count"] += 1
                blockers.append(
                    self._missing_blocker(
                        segment,
                        logical_source_segment_id,
                        candidate_samples=[],
                        reason="no current draft source segment template matches media identity + source range",
                    )
                )
                continue
            if len(candidates) > 1:
                report["source_segment_template_ambiguous_count"] += 1
                report["rebind_rejection_reasons"]["ambiguous"] += 1
                blockers.append(
                    self._ambiguous_blocker(
                        segment,
                        logical_source_segment_id,
                        candidate_samples=[self._candidate_sample(candidate.template) for candidate in candidates[:10]],
                    )
                )
                continue

            (match,) = candidates
            rebound = match.template
            report["source_segment_template_rebind_count"] += 1
            report["source_segment_template_rebound"] = True
            sample = {
                "old_source_segment_id": logical_source_segment_id,
                "new_source_segment_id": str(rebound.get("id") or ""),
                "match_strength": match.match_strength,
                "match_reason": match.match_reason,
                "source_material_id": str(segment.source_material_id or ""),
                "new_source_material_id": self._material_id(rebound),
                "source_start_us": int(segment.source_start_us),
                "source_end_us": int(segment.source_end_us),
            }
            report.setdefault("source_segment_template_rebind_samples", []).append(sample)
            templates_by_final_id[segment.segment_id] = rebound
            resolved_template_map[segment.segment_id] = self._binding_record(
                segment,
                rebound,
                match.match_strength,
                0.65 if match.match_strength == "weak_unique_primary_video" else 0.95,
            )
            resolved_templates.append(rebound)

        if blockers:
            report["source_segment_template_available"] = False
            report["resolved_template_map"] = resolved_template_map
            report["resolved_template_map_count"] = len(resolved_template_map)
            return SourceSegmentTemplateResolution(
                success=False,
                templates_by_final_segment_id=templates_by_final_id,
                resolved_templates=resolved_templates,
                blockers=blockers,
                report=report,
            )
        report["source_segment_template_available"] = True
        report["resolved_template_map"] = resolved_template_map
        report["resolved_template_map_count"] = len(resolved_template_map)
        return SourceSegmentTemplateResolution(
            success=True,
            templates_by_final_segment_id=templates_by_final_id,
            resolved_templates=resolved_templates,
            blockers=[],
            report=report,
        )

    def candidate_index_report(self) -> dict[str, Any]:
        report = dict(SOURCE_TEMPLATE_REPORT_DEFAULTS)
        report["source_segment_template_rebind_samples"] = []
        report["current_source_template_candidate_samples"] = []
        report["invalid_duration_fields"] = []
        report["rejected_duration_values"] = []
        report["rebind_rejection_reasons"] = dict(SOURCE_TEMPLATE_REPORT_DEFAULTS["rebind_rejection_reasons"])
        report["current_draft_video_track_count"] = self.current_draft_video_track_count
        report["current_draft_video_segment_count"] = self.current_draft_video_segment_count
        report["current_draft_video_material_count"] = self.current_draft_video_material_count
        report["current_source_template_candidate_count"] = len(self.all_source_template_candidates)
        report["current_source_template_candidate_samples"] = [
            self._candidate_sample(candidate)
            for candidate in self.all_source_template_candidates[:10]
        ]
        report["primary_video_track_id"] = self.primary_video_track_id
        report["primary_video_candidate_count"] = len(self.current_source_segments)
        report["primary_video_track_candidate_count"] = len(
            {str(row.get("track_id") or "") for row in self.all_source_template_candidates if str(row.get("track_id") or "")}
        )
        report["invalid_duration_field_count"] = int(self.duration_parse_report["invalid_duration_field_count"])
        report["invalid_duration_fields"] = list(self.duration_parse_report["invalid_duration_fields"])
        report["rejected_duration_values"] = list(self.duration_parse_report["rejected_duration_values"])
        return report

    def _rebind_candidates(
        self,
        segment: FinalTimelineSegment,
        *,
        source_materials: list[dict[str, Any]],
        report: dict[str, Any],
    ) -> list[SourceTemplateCandidateMatch]:
        requested_material = source_materials[0] if len(source_materials) == 1 else {}
        requested_identity = self._media_identity(segment_row={}, material_row=requested_material)
        range_candidates: list[tuple[dict[str, Any], dict[str, Any], dict[str, set[str] | int | None]]] = []
        for current in self.current_source_segments:
            current_material = self.current_material_by_id.get(self._material_id(current)) or {}
            if not self._range_compatible(segment, current, current_material, report):
                report["rebind_rejection_reasons"]["source_range_not_covered"] += 1
                continue
            current_identity = self._media_identity(segment_row=current, material_row=current_material)
            range_candidates.append((current, current_material, current_identity))
        if not range_candidates:
            return list(EMPTY_SOURCE_TEMPLATE_MATCHES)

        candidates: list[SourceTemplateCandidateMatch] = []
        media_identity_was_explicit = self._has_explicit_media_identity(requested_identity)
        explicit_media_mismatch = False
        for current, _current_material, current_identity in range_candidates:
            identity_match = self._identity_match(requested_identity, current_identity)
            if identity_match == "duration_mismatch":
                explicit_media_mismatch = True
                report["rebind_rejection_reasons"]["duration_mismatch"] += 1
                continue
            if identity_match is None:
                if media_identity_was_explicit and self._has_explicit_media_identity(current_identity):
                    explicit_media_mismatch = True
                    report["rebind_rejection_reasons"]["media_identity_mismatch"] += 1
                continue
            candidates.append(
                SourceTemplateCandidateMatch(
                    template=current,
                    match_strength=identity_match,
                    match_reason=f"{identity_match} media identity + source time range",
                )
            )
        if candidates:
            return candidates
        if len(range_candidates) == 1 and not explicit_media_mismatch:
            (range_candidate,) = range_candidates
            current, _current_material, _current_identity = range_candidate
            return list(
                (
                    SourceTemplateCandidateMatch(
                        template=current,
                        match_strength="weak_unique_primary_video",
                        match_reason="single current primary video template covers final source range",
                    ),
                )
            )
        if not explicit_media_mismatch:
            report["rebind_rejection_reasons"]["ambiguous"] += 1
            return [
                SourceTemplateCandidateMatch(
                    template=current,
                    match_strength="weak_ambiguous",
                    match_reason="multiple current video templates cover final source range",
                )
                for current, _current_material, _current_identity in range_candidates
            ]
        return list(EMPTY_SOURCE_TEMPLATE_MATCHES)

    def _range_compatible(
        self,
        segment: FinalTimelineSegment,
        current_segment: dict[str, Any],
        current_material: dict[str, Any],
        report: dict[str, Any],
    ) -> bool:
        start, end = self._segment_source_range(segment)
        current_range = self._timeline_source_range(current_segment)
        if current_range is not None:
            candidate_start, candidate_end = current_range
            return start >= candidate_start and end <= candidate_end
        duration = self._duration_us(current_material) or self._duration_us(current_segment)
        if duration is None:
            if self.duration_parse_report["invalid_duration_field_count"]:
                report["duration_unparseable_required"] = True
                report["rebind_rejection_reasons"]["duration_unparseable"] += 1
            return False
        return start >= 0 and end <= duration

    def _segment_source_range(self, segment: FinalTimelineSegment) -> tuple[int, int]:
        start = int(segment.clip_source_start_us if segment.clip_source_start_us is not None else segment.source_start_us)
        end = int(segment.clip_source_end_us if segment.clip_source_end_us is not None else segment.source_end_us)
        return start, end

    def _timeline_source_range(self, row: dict[str, Any]) -> tuple[int, int] | None:
        for key in ("target_timerange", "source_timerange"):
            value = row.get(key)
            if isinstance(value, dict):
                start = int(value.get("start") or 0)
                duration = int(value.get("duration") or 0)
                end = int(value.get("end") or (start + duration if duration else 0))
                if end > start:
                    return start, end
        start_values = [row.get("source_start_us"), row.get("start_us")]
        end_values = [row.get("source_end_us"), row.get("end_us")]
        for start_value in start_values:
            for end_value in end_values:
                if start_value is None or end_value is None:
                    continue
                start = int(start_value)
                end = int(end_value)
                if end > start:
                    return start, end
        return NO_SOURCE_RANGE

    def _media_identity(self, *, segment_row: dict[str, Any], material_row: dict[str, Any]) -> dict[str, set[str] | int | None]:
        strong_paths: set[str] = set()
        basenames: set[str] = set()
        for row in (segment_row, material_row):
            for key in (
                "path",
                "file_path",
                "local_path",
                "source_path",
                "video_path",
                "uri",
                "url",
                "name",
                "file_name",
                "filename",
                "material_name",
            ):
                value = row.get(key)
                if not isinstance(value, str) or not value.strip():
                    continue
                normalized = value.strip().replace("\\", "/").lower()
                if "/" in normalized or ":" in normalized:
                    strong_paths.add(normalized)
                basename = Path(normalized).name
                if basename:
                    basenames.add(basename)
        duration = self._duration_us(segment_row) or self._duration_us(material_row)
        return {"strong_paths": strong_paths, "basenames": basenames, "duration_us": duration}

    def _identity_match(self, requested: dict[str, set[str] | int | None], current: dict[str, set[str] | int | None]) -> str | None:
        requested_paths = requested["strong_paths"]
        current_paths = current["strong_paths"]
        if isinstance(requested_paths, set) and isinstance(current_paths, set) and requested_paths and current_paths:
            return "strong" if requested_paths.intersection(current_paths) else NO_IDENTITY_MATCH
        requested_names = requested["basenames"]
        current_names = current["basenames"]
        requested_duration = requested["duration_us"]
        current_duration = current["duration_us"]
        if isinstance(requested_names, set) and isinstance(current_names, set) and requested_names and current_names:
            if not requested_names.intersection(current_names):
                return NO_IDENTITY_MATCH
            if isinstance(requested_duration, int) and isinstance(current_duration, int):
                return "medium" if requested_duration == current_duration else "duration_mismatch"
            return "medium"
        return NO_IDENTITY_MATCH

    def _can_use_weak_unique_primary_video(
        self,
        requested: dict[str, set[str] | int | None],
        current: dict[str, set[str] | int | None],
    ) -> bool:
        if len(self.current_source_segments) != 1:
            return False
        requested_paths = requested["strong_paths"]
        current_paths = current["strong_paths"]
        if isinstance(requested_paths, set) and isinstance(current_paths, set) and requested_paths and current_paths:
            return False
        requested_names = requested["basenames"]
        current_names = current["basenames"]
        if isinstance(requested_names, set) and isinstance(current_names, set) and requested_names and current_names:
            if not requested_names.intersection(current_names):
                return False
            requested_duration = requested["duration_us"]
            current_duration = current["duration_us"]
            if isinstance(requested_duration, int) and isinstance(current_duration, int) and requested_duration != current_duration:
                return False
        return True

    def _has_explicit_media_identity(self, identity: dict[str, set[str] | int | None]) -> bool:
        paths = identity["strong_paths"]
        names = identity["basenames"]
        return bool((isinstance(paths, set) and paths) or (isinstance(names, set) and names))

    def _duration_us(self, row: dict[str, Any]) -> int | None:
        for key in (
            "duration_us",
            "source_duration_us",
            "media_duration_us",
            "duration",
            "source_duration",
            "media_duration",
        ):
            value = row.get(key)
            if value is None:
                continue
            try:
                duration = int(value)
            except (TypeError, ValueError):
                self._record_invalid_duration(row, key, value)
                continue
            if duration > 0:
                return duration
        return NO_DURATION_US

    def _material_index(self, materials: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for row in materials:
            if not isinstance(row, dict):
                continue
            for key in ("source_material_id", "material_id", "materialId", "id"):
                value = str(row.get(key) or "")
                if value:
                    index[value] = row
        return index

    def _material_id(self, row: dict[str, Any]) -> str:
        return str(row.get("source_material_id") or row.get("material_id") or row.get("materialId") or "")

    def _draft_video_materials(self, draft_data: dict[str, Any]) -> list[dict[str, Any]]:
        materials = draft_data.get("materials") if isinstance(draft_data.get("materials"), dict) else {}
        rows: list[dict[str, Any]] = []
        for key in ("videos", "video"):
            for material in materials.get(key) or []:
                if not isinstance(material, dict):
                    continue
                row = dict(material)
                row.setdefault("source_material_id", str(row.get("id") or row.get("material_id") or row.get("materialId") or ""))
                row.setdefault("type", "video")
                rows.append(row)
        return rows

    def _draft_video_track_count(self, draft_data: dict[str, Any]) -> int:
        count = 0
        for track in draft_data.get("tracks") or []:
            if isinstance(track, dict) and self._is_video_track(track):
                count += 1
        return count

    def _draft_video_segments(self, draft_data: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for track in draft_data.get("tracks") or []:
            if not isinstance(track, dict) or not self._is_video_track(track):
                continue
            for segment in track.get("segments") or []:
                if not isinstance(segment, dict):
                    continue
                row = dict(segment)
                row.setdefault("track_id", str(track.get("id") or ""))
                row.setdefault("track_type", str(track.get("type") or track.get("track_type") or "video"))
                rows.append(row)
        return rows

    def _source_template_candidates(
        self,
        current_source_segments: list[dict[str, Any]],
        draft_video_segments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in [*current_source_segments, *draft_video_segments]:
            if not isinstance(row, dict):
                continue
            if not self._is_video_segment(row):
                continue
            candidate = dict(row)
            candidate_id = str(candidate.get("id") or "")
            material_id = self._material_id(candidate)
            if not material_id or material_id not in self.current_material_by_id:
                continue
            material = self.current_material_by_id.get(material_id) or {}
            if not self._is_source_backed_video_material(material):
                continue
            key = candidate_id or f"{material_id}:{len(candidates)}"
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
        return candidates

    def _primary_video_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not candidates:
            self.primary_blocker = Blocker(
                "V21_DYNAMIC_BINDING_PRIMARY_VIDEO_MISSING",
                "current draft has no source-backed primary video track candidates",
                "writeback",
                context={"reason": "no source-backed video segment with material binding"},
            )
            return []
        by_track: dict[str, list[dict[str, Any]]] = {}
        for candidate in candidates:
            track_id = str(candidate.get("track_id") or "")
            if not track_id:
                continue
            by_track.setdefault(track_id, []).append(candidate)
        if not by_track:
            self.primary_blocker = Blocker(
                "V21_DYNAMIC_BINDING_PRIMARY_VIDEO_MISSING",
                "current draft video candidates do not include track ids",
                "writeback",
                context={"reason": "video template candidates missing track_id"},
            )
            return []
        scored: list[tuple[int, int, str, list[dict[str, Any]]]] = []
        for track_id, rows in by_track.items():
            material_ids = {self._material_id(row) for row in rows if self._material_id(row)}
            coverage = sum(self._candidate_coverage_us(row) for row in rows)
            single_material_bonus = 1 if len(material_ids) == 1 else 0
            scored.append((coverage, single_material_bonus, track_id, rows))
        max_coverage = max(item[0] for item in scored)
        winners = [item for item in scored if item[0] == max_coverage]
        if len(winners) > 1:
            self.primary_blocker = Blocker(
                "V21_DYNAMIC_BINDING_PRIMARY_VIDEO_AMBIGUOUS",
                "multiple video tracks are equally plausible primary source tracks",
                "writeback",
                context={
                    "candidate_track_ids": sorted(item[2] for item in winners),
                    "candidate_count": len(winners),
                    "reason": "multiple source-backed video tracks have equal coverage",
                },
            )
            return []
        _coverage, _single_bonus, track_id, rows = winners[0]
        self.primary_video_track_id = track_id
        return rows

    def _candidate_coverage_us(self, candidate: dict[str, Any]) -> int:
        source_range = self._timeline_source_range(candidate)
        if source_range is not None:
            return max(0, source_range[1] - source_range[0])
        material = self.current_material_by_id.get(self._material_id(candidate)) or {}
        return int(self._duration_us(material) or self._duration_us(candidate) or 0)

    def _is_source_backed_video_material(self, material: dict[str, Any]) -> bool:
        material_type = str(material.get("type") or material.get("material_type") or "").lower()
        if any(token in material_type for token in ("image", "photo", "sticker", "generated")):
            return False
        return "video" in material_type or not material_type

    def _is_video_track(self, track: dict[str, Any]) -> bool:
        track_type = str(track.get("type") or track.get("track_type") or "").lower()
        return "video" in track_type

    def _is_video_segment(self, segment: dict[str, Any]) -> bool:
        track_type = str(segment.get("track_type") or segment.get("type") or "").lower()
        if "audio" in track_type:
            return False
        if "video" in track_type:
            return True
        material_id = self._material_id(segment)
        material = self.current_material_by_id.get(material_id) or {}
        material_type = str(material.get("type") or material.get("material_type") or "").lower()
        return "video" in material_type or (bool(material_id) and not material_type)

    def _record_invalid_duration(self, row: dict[str, Any], key: str, value: Any) -> None:
        self.duration_parse_report["invalid_duration_field_count"] = int(self.duration_parse_report["invalid_duration_field_count"]) + 1
        fields = self.duration_parse_report["invalid_duration_fields"]
        rejected = self.duration_parse_report["rejected_duration_values"]
        if isinstance(fields, list):
            fields.append({"field": key, "row_id": str(row.get("id") or row.get("source_material_id") or row.get("material_id") or "")})
        if isinstance(rejected, list):
            rejected.append({"field": key, "value": str(value)})

    def _candidate_sample(self, candidate: dict[str, Any]) -> dict[str, Any]:
        source_range = self._timeline_source_range(candidate)
        media_path = ""
        current_material = self.current_material_by_id.get(self._material_id(candidate)) or {}
        for row in (candidate, current_material):
            for key in ("path", "file_path", "local_path", "source_path", "video_path", "uri", "url", "name", "file_name", "filename"):
                value = row.get(key)
                if isinstance(value, str) and value.strip():
                    media_path = value.strip()
                    break
            if media_path:
                break
        return {
            "source_segment_id": str(candidate.get("id") or ""),
            "source_material_id": self._material_id(candidate),
            "media_path": media_path,
            "source_range": list(source_range) if source_range is not None else [],
            "target_range": list(self._target_range(candidate) or source_range or []),
        }

    def _binding_record(
        self,
        segment: FinalTimelineSegment,
        template: dict[str, Any],
        match_strategy: str,
        match_confidence: float,
    ) -> dict[str, Any]:
        material_id = self._material_id(template)
        material = self.current_material_by_id.get(material_id) or {}
        source_start, source_end = self._segment_source_range(segment)
        template_target_range = self._target_range(template)
        template_material_range = self._material_source_range(template)
        return {
            "final_segment_id": segment.segment_id,
            "current_source_segment_id": str(template.get("id") or ""),
            "current_source_material_id": material_id,
            "current_video_track_id": str(template.get("track_id") or ""),
            "current_video_segment_template": dict(template),
            "current_material_template": dict(material),
            "source_start_us": source_start,
            "source_end_us": source_end,
            "template_target_start_us": template_target_range[0] if template_target_range else None,
            "template_target_end_us": template_target_range[1] if template_target_range else None,
            "template_material_source_start_us": template_material_range[0] if template_material_range else None,
            "template_material_source_end_us": template_material_range[1] if template_material_range else None,
            "speed": template.get("speed") or template.get("speed_ratio") or template.get("source_speed"),
            "match_strategy": match_strategy,
            "match_confidence": match_confidence,
        }

    def _target_range(self, row: dict[str, Any]) -> tuple[int, int] | None:
        value = row.get("target_timerange")
        if not isinstance(value, dict):
            return None
        start = int(value.get("start") or 0)
        duration = int(value.get("duration") or 0)
        end = int(value.get("end") or (start + duration if duration else 0))
        return (start, end) if end > start else None

    def _material_source_range(self, row: dict[str, Any]) -> tuple[int, int] | None:
        value = row.get("source_timerange")
        if not isinstance(value, dict):
            return None
        start = int(value.get("start") or 0)
        duration = int(value.get("duration") or 0)
        end = int(value.get("end") or (start + duration if duration else 0))
        return (start, end) if end > start else None

    def _missing_blocker(
        self,
        segment: FinalTimelineSegment,
        requested_id: str,
        *,
        candidate_samples: list[dict[str, Any]],
        reason: str,
    ) -> Blocker:
        return Blocker(
            code="V21_DYNAMIC_BINDING_MISSING",
            message="could not dynamically bind final timeline segment to a current draft source template",
            layer="writeback",
            context={
                "missing_source_segment_id": requested_id,
                "source_material_id": str(segment.source_material_id or ""),
                "source_start_us": int(segment.source_start_us),
                "source_end_us": int(segment.source_end_us),
                "candidate_count": len(candidate_samples),
                "candidate_samples": candidate_samples,
                "reason": reason,
            },
        )

    def _ambiguous_blocker(
        self,
        segment: FinalTimelineSegment,
        requested_id: str,
        *,
        candidate_samples: list[dict[str, Any]],
    ) -> Blocker:
        return Blocker(
            code="V21_DYNAMIC_BINDING_AMBIGUOUS",
            message="multiple current draft source templates can bind final timeline segment",
            layer="writeback",
            context={
                "missing_source_segment_id": requested_id,
                "source_material_id": str(segment.source_material_id or ""),
                "source_start_us": int(segment.source_start_us),
                "source_end_us": int(segment.source_end_us),
                "candidate_count": len(candidate_samples),
                "candidate_samples": candidate_samples,
                "reason": "multiple current draft source segment template candidates",
            },
        )
