from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from aroll_subtitle_style_integrity_gate import _fingerprint, subtitle_style_safety_issues, text_content_schema_issues
from aroll_v21.ir.models import Blocker, CanonicalSourceGraph, CaptionRenderUnit
from aroll_v21.writer.subtitle_identity_resolver import SubtitleIdentityResolver
from aroll_v21.writer.text_material_clone import clone_caption_text_material


def _material_id(segment: dict[str, Any]) -> str:
    return str(segment.get("material_id") or segment.get("materialId") or "")


def _caption_like(material: dict[str, Any], segment: dict[str, Any]) -> bool:
    marker = " ".join(
        str(value or "")
        for value in (
            material.get("role"),
            material.get("type"),
            material.get("name"),
            segment.get("type"),
            segment.get("name"),
        )
    ).lower()
    return any(token in marker for token in ("caption", "subtitle", "text")) or bool(material.get("content"))


def _blacklisted_text_template(material: dict[str, Any], segment: dict[str, Any]) -> bool:
    marker = " ".join(
        str(value or "")
        for value in (
            material.get("role"),
            material.get("type"),
            material.get("name"),
            material.get("category"),
            segment.get("type"),
            segment.get("name"),
            segment.get("category"),
        )
    ).lower()
    return any(token in marker for token in ("title", "callout", "emphasis", "sticker", "headline"))


def rewrite_caption_material_text(material: dict[str, Any], text: str) -> dict[str, Any]:
    return clone_caption_text_material(material, str(material.get("id") or "caption"), text)


VOLATILE_TEMPLATE_KEYS = {
    "id",
    "uid",
    "uuid",
    "material_id",
    "materialId",
    "text",
    "recognize_text",
    "current_words",
    "words",
    "word",
    "subtitle_keywords",
    "subtitle_keyword",
    "keywords",
    "keyword",
    "keyword_ranges",
    "keyword_range",
    "extra_material_refs",
    "caption_id",
    "subtitle_uid",
    "source_subtitle_uid",
    "target_timerange",
    "source_timerange",
    "created_at",
    "updated_at",
    "create_time",
    "update_time",
    "order",
    "index",
    "render_index",
    "name",
}

VOLATILE_FIELDS_IGNORED = [
    "base_content.text",
    "caption uid",
    "content.text",
    "current_words",
    "keyword ranges",
    "material_id",
    "recognize_text",
    "render_index",
    "segment_id",
    "style_ranges.length",
    "subtitle_keywords",
    "words",
]


def _stable_content_payload(value: Any, *, dynamic_content: bool = False) -> Any:
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return "<invalid_text_content_json>"
    elif isinstance(value, dict):
        payload = value
    else:
        return "<invalid_text_content_schema>"
    if dynamic_content:
        return _stable_content_schema_payload(payload)
    return _stable_style_payload(payload, in_content=True)


def _stable_content_schema_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep content/base_content schema shape without text- or keyword-span data."""

    keys = sorted(str(key) for key in payload.keys() if key not in VOLATILE_TEMPLATE_KEYS)
    return {
        "keys": keys,
        "styles": "dynamic_caption_styles" if isinstance(payload.get("styles"), list) else type(payload.get("styles")).__name__,
    }


def _stable_style_payload(obj: Any, *, in_content: bool = False) -> Any:
    return _stable_style_payload_inner(obj, in_content=in_content, schema_only=False)


def _stable_style_payload_inner(obj: Any, *, in_content: bool = False, schema_only: bool = False) -> Any:
    if isinstance(obj, dict):
        clean: dict[str, Any] = {}
        for key, value in obj.items():
            if key in VOLATILE_TEMPLATE_KEYS:
                continue
            if key in {"content", "base_content"}:
                clean[key] = _stable_content_payload(value, dynamic_content=(key == "content"))
                continue
            if in_content and key == "range":
                clean[key] = "<normalized_range>"
                continue
            clean[key] = _stable_style_payload_inner(value, in_content=in_content, schema_only=schema_only)
        return clean
    if isinstance(obj, list):
        normalized = [_stable_style_payload_inner(item, in_content=in_content, schema_only=schema_only) for item in obj]
        if in_content:
            unique = {
                json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                for item in normalized
            }
            return sorted(unique)
        return normalized
    if schema_only:
        return type(obj).__name__
    return obj


def caption_template_fingerprint(material: dict[str, Any], segment: dict[str, Any]) -> tuple[str, str, str]:
    material_payload = _stable_style_payload(material)
    segment_payload = _stable_style_payload(segment)
    material_hash = hashlib.sha256(json.dumps(material_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    segment_hash = hashlib.sha256(json.dumps(segment_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"{material_hash}:{segment_hash}", material_hash, segment_hash


class CaptionTemplateDetector:
    def __init__(self, subtitle_identity_resolver: SubtitleIdentityResolver | None = None) -> None:
        self.subtitle_identity_resolver = subtitle_identity_resolver or SubtitleIdentityResolver()

    def detect(
        self,
        source_graph: CanonicalSourceGraph,
        captions: list[CaptionRenderUnit] | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any]]:
        material_by_id = {str(row.get("id") or ""): row for row in source_graph.text_materials}
        subtitle_material_ids = self.subtitle_identity_resolver.material_ids_for_captions(source_graph, captions)
        candidates: list[dict[str, Any]] = []
        rejection_summary = {
            "not_subtitle_track": 0,
            "giant_style": 0,
            "callout_style": 0,
            "title_like": 0,
            "content_schema_unsafe": 0,
            "missing_segment_binding": 0,
            "fingerprint_ambiguous": 0,
        }
        title_like_reasons = {
            "font_size_too_large": 0,
            "screen_occupancy_too_large": 0,
            "position_center_title_like": 0,
            "bottom_subtitle_position": 0,
            "subtitle_bound_position_risk_downgraded": 0,
            "scale_too_large": 0,
            "unknown": 0,
        }
        sample_rejections: list[dict[str, Any]] = []

        def note_title_like(issues: list[str] | None = None) -> None:
            bucket = self._title_like_reason(issues or [])
            title_like_reasons[bucket] += 1

        def reject(material: dict[str, Any], segment: dict[str, Any], reason: str, issues: list[str] | None = None) -> None:
            if reason in rejection_summary:
                rejection_summary[reason] += 1
            if reason == "title_like":
                note_title_like(issues)
            if len(sample_rejections) < 20:
                sample_rejections.append(
                    {
                        "material_id": str(material.get("id") or ""),
                        "segment_id": str(segment.get("id") or ""),
                        "reason": reason,
                        "issues": issues or [],
                    }
                )

        def consider(material: dict[str, Any], segment: dict[str, Any]) -> None:
            material_id = str(material.get("id") or "")
            subtitle_related = bool(material_id and material_id in subtitle_material_ids)
            if subtitle_material_ids and not subtitle_related:
                reject(material, segment, "not_subtitle_track")
                return
            if not subtitle_related and not _caption_like(material, segment):
                reject(material, segment, "not_subtitle_track")
                return
            blacklist_reason = self._blacklist_reason(material, segment)
            if blacklist_reason == "callout_style":
                reject(material, segment, blacklist_reason)
                return
            if blacklist_reason == "title_like":
                position_reason = self._position_title_like_reason(material, segment)
                if not subtitle_related:
                    reject(material, segment, blacklist_reason, [position_reason])
                    return
                note_title_like([position_reason])
                title_like_reasons["subtitle_bound_position_risk_downgraded"] += 1
            content_issues = text_content_schema_issues(material)
            if content_issues:
                reject(material, segment, "content_schema_unsafe", content_issues)
                return
            style_issues = subtitle_style_safety_issues(material, segment)
            if style_issues:
                for issue in style_issues:
                    if issue in {
                        "FONT_SIZE_EXCEEDS_SAFE_LIMIT",
                        "SCALE_EXCEEDS_SAFE_LIMIT",
                        "SCREEN_OCCUPANCY_EXCEEDS_SAFE_LIMIT",
                    }:
                        note_title_like([issue])
                reject(material, segment, "giant_style", style_issues)
                return
            fingerprint, material_fp, segment_fp = caption_template_fingerprint(material, segment)
            candidates.append(
                {
                    "material": material,
                    "segment": segment,
                    "fingerprint": fingerprint,
                    "material_fingerprint": material_fp,
                    "segment_fingerprint": segment_fp,
                    "subtitle_related": subtitle_related,
                    "title_like_risk": blacklist_reason == "title_like",
                }
            )

        if source_graph.text_segments:
            seen_segment_material_ids: set[str] = set()
            for segment in source_graph.text_segments:
                material = material_by_id.get(_material_id(segment))
                if not material:
                    reject({"id": _material_id(segment)}, segment, "missing_segment_binding")
                    continue
                seen_segment_material_ids.add(str(material.get("id") or ""))
                consider(material, segment)
            for material in source_graph.text_materials:
                material_id = str(material.get("id") or "")
                if material_id in seen_segment_material_ids or material_id not in subtitle_material_ids:
                    continue
                reject(material, {}, "missing_segment_binding")
        else:
            for material in source_graph.text_materials:
                segment: dict[str, Any] = {}
                consider(material, segment)

        groups: dict[str, list[dict[str, Any]]] = {}
        for candidate in candidates:
            groups.setdefault(str(candidate["fingerprint"]), []).append(candidate)

        report = {
            "candidate_count": len(candidates),
            "candidate_material_ids": [str(row["material"].get("id") or "") for row in candidates],
            "fingerprint_group_count": len(groups),
            "stable_fingerprint_group_count": len(groups),
            "fingerprint_group_sizes": {fingerprint: len(rows) for fingerprint, rows in groups.items()},
            "volatile_fields_ignored": VOLATILE_FIELDS_IGNORED,
            "fingerprint_debug_samples": [
                {
                    "material_id": str(row["material"].get("id") or ""),
                    "segment_id": str(row["segment"].get("id") or ""),
                    "fingerprint": str(row["fingerprint"]),
                    "material_fingerprint": str(row["material_fingerprint"]),
                    "segment_fingerprint": str(row["segment_fingerprint"]),
                }
                for row in candidates[:5]
            ],
            "rejected_count": sum(rejection_summary.values()),
            "rejection_summary": rejection_summary,
            "title_like_reasons": title_like_reasons,
            "sample_rejections": sample_rejections,
            "canonical_caption_template_id": "",
            "representative_material_id": "",
            "fingerprint": "",
            "selection_reason": "",
            "no_writer_fallback": True,
            "writer_fallback_count": 0,
            "blockers": [],
        }
        if not candidates:
            report["blockers"].append(
                {
                    "code": "CAPTION_TEMPLATE_NOT_FOUND",
                    "candidate_count": len(candidates),
                    "fingerprint_group_count": len(groups),
                }
            )
            return None, None, report
        if len(groups) != 1:
            report["rejection_summary"]["fingerprint_ambiguous"] = len(groups)
            report["blockers"].append(
                {
                    "code": "CAPTION_TEMPLATE_AMBIGUOUS",
                    "candidate_count": len(candidates),
                    "fingerprint_group_count": len(groups),
                }
            )
            return None, None, report
        fingerprint, group = next(iter(groups.items()))
        representative = group[0]
        material = deepcopy(representative["material"])
        segment = deepcopy(representative["segment"])
        report["canonical_caption_template_id"] = str(material.get("id") or "")
        report["representative_material_id"] = str(material.get("id") or "")
        report["fingerprint"] = fingerprint
        report["canonical_caption_template_fingerprint"] = fingerprint
        report["material_fingerprint"] = representative["material_fingerprint"]
        report["segment_fingerprint"] = representative["segment_fingerprint"]
        report["selection_reason"] = "single_safe_fingerprint_group"
        return material, segment, report

    def _blacklist_reason(self, material: dict[str, Any], segment: dict[str, Any]) -> str:
        marker = " ".join(
            str(value or "")
            for value in (
                material.get("role"),
                material.get("type"),
                material.get("name"),
                material.get("category"),
                segment.get("type"),
                segment.get("name"),
                segment.get("category"),
            )
        ).lower()
        if any(token in marker for token in ("callout", "sticker")):
            return "callout_style"
        if any(token in marker for token in ("title", "emphasis", "headline")):
            return "title_like"
        return ""

    def _title_like_reason(self, issues: list[str]) -> str:
        issue_set = {str(issue) for issue in issues}
        if "FONT_SIZE_EXCEEDS_SAFE_LIMIT" in issue_set:
            return "font_size_too_large"
        if "SCREEN_OCCUPANCY_EXCEEDS_SAFE_LIMIT" in issue_set:
            return "screen_occupancy_too_large"
        if "SCALE_EXCEEDS_SAFE_LIMIT" in issue_set:
            return "scale_too_large"
        if "BOTTOM_SUBTITLE_POSITION" in issue_set:
            return "bottom_subtitle_position"
        if "POSITION_CENTER_TITLE_LIKE" in issue_set or "POSITION_EXCEEDS_SAFE_LIMIT" in issue_set:
            return "position_center_title_like"
        return "unknown"

    def _position_title_like_reason(self, material: dict[str, Any], segment: dict[str, Any]) -> str:
        y_values = self._transform_y_values(material) + self._transform_y_values(segment)
        if any(value <= -0.45 for value in y_values):
            return "BOTTOM_SUBTITLE_POSITION"
        if any(value >= -0.15 for value in y_values):
            return "POSITION_CENTER_TITLE_LIKE"
        return "POSITION_CENTER_TITLE_LIKE"

    def _transform_y_values(self, obj: Any) -> list[float]:
        values: list[float] = []
        if isinstance(obj, dict):
            transform = obj.get("transform")
            if isinstance(transform, dict) and isinstance(transform.get("y"), (int, float)):
                values.append(float(transform["y"]))
            clip = obj.get("clip")
            if isinstance(clip, dict):
                values.extend(self._transform_y_values(clip))
            for key, value in obj.items():
                if key == "transform" or key == "clip":
                    continue
                if isinstance(value, (dict, list)):
                    values.extend(self._transform_y_values(value))
        elif isinstance(obj, list):
            for item in obj:
                values.extend(self._transform_y_values(item))
        return values


class CaptionMaterialWriter:
    def __init__(self, template_detector: CaptionTemplateDetector | None = None) -> None:
        self.template_detector = template_detector or CaptionTemplateDetector()

    def build_write_plan(
        self,
        source_graph: CanonicalSourceGraph,
        captions: list[CaptionRenderUnit],
    ) -> tuple[dict[str, Any], list[Blocker]]:
        template_material, template_segment, template_report = self.template_detector.detect(source_graph, captions)
        blockers: list[Blocker] = []
        if template_material is None or template_segment is None:
            for row in template_report.get("blockers") or []:
                blockers.append(
                    Blocker(
                        code=str(row.get("code") or "CAPTION_TEMPLATE_UNAVAILABLE"),
                        message="canonical caption template could not be selected without fallback",
                        layer="writer",
                        context=row,
                    )
                )
            return {
                "template_report": template_report,
                "materials": [],
                "segments": [],
                "no_writer_fallback": True,
                "writer_fallback_count": 0,
            }, blockers

        materials: list[dict[str, Any]] = []
        segments: list[dict[str, Any]] = []
        template_id = str(template_material.get("id") or "")
        _template_group_fingerprint, template_fingerprint, _segment_fingerprint = caption_template_fingerprint(template_material, template_segment)
        for index, caption in enumerate(captions, start=1):
            material_id = f"v21_caption_material_{index:06d}"
            material = rewrite_caption_material_text(template_material | {"id": material_id}, caption.text)
            segment = deepcopy(template_segment)
            segment["id"] = f"v21_caption_segment_{index:06d}"
            segment["material_id"] = material_id
            segment["target_timerange"] = {
                "start": caption.target_start_us,
                "duration": caption.target_end_us - caption.target_start_us,
            }
            materials.append(material)
            segments.append(segment)
        plan = {
            "canonical_caption_template_id": template_id,
            "canonical_caption_template": {
                "template_id": template_id,
                "fingerprint": template_report.get("fingerprint") or "",
                "representative_material_id": template_report.get("representative_material_id") or template_id,
                "candidate_count": int(template_report.get("candidate_count") or 0),
                "fingerprint_group_count": int(template_report.get("fingerprint_group_count") or 0),
                "rejected_count": int(template_report.get("rejected_count") or 0),
                "rejection_summary": template_report.get("rejection_summary") or {},
                "title_like_reasons": template_report.get("title_like_reasons") or {},
                "sample_rejections": template_report.get("sample_rejections") or [],
                "selection_reason": str(template_report.get("selection_reason") or ""),
                "material": template_material,
                "segment": template_segment,
                "material_fingerprint": template_fingerprint,
            },
            "template_report": template_report,
            "caption_count": len(captions),
            "materials": materials,
            "segments": segments,
            "no_writer_fallback": True,
            "writer_fallback_count": 0,
            "output_material_fingerprints": [_fingerprint(material) for material in materials],
            "writer_mode": "plan_only",
        }
        return plan, blockers
