from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any


FONT_KEYS = {"font_size", "fontsize", "fontSize", "text_size", "textSize", "size"}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item)


def _numbers_for_keys(obj: Any, keys: set[str]) -> list[float]:
    values: list[float] = []
    for node in _walk(obj):
        for key, value in node.items():
            if key in keys and isinstance(value, (int, float)):
                values.append(float(value))
    return values


def _scale_values(obj: Any) -> list[float]:
    values: list[float] = []
    for node in _walk(obj):
        for key, value in node.items():
            if key in {"scale", "uniform_scale"} and isinstance(value, dict):
                for axis in ("x", "y", "value"):
                    axis_value = value.get(axis)
                    if isinstance(axis_value, (int, float)):
                        values.append(abs(float(axis_value)))
            elif key in {"scale_x", "scale_y", "scaleX", "scaleY"} and isinstance(value, (int, float)):
                values.append(abs(float(value)))
    return values


def _position_values(obj: Any) -> list[float]:
    values: list[float] = []
    for node in _walk(obj):
        for key, value in node.items():
            if key in {"position", "pos", "anchor"} and isinstance(value, dict):
                for axis in ("x", "y", "z"):
                    axis_value = value.get(axis)
                    if isinstance(axis_value, (int, float)):
                        values.append(float(axis_value))
            elif key in {"x", "y", "pos_x", "pos_y", "position_x", "position_y", "offset_x", "offset_y"} and isinstance(value, (int, float)):
                values.append(float(value))
    return values


def _scrub_for_template(obj: Any) -> Any:
    if isinstance(obj, dict):
        clean: dict[str, Any] = {}
        for key, value in obj.items():
            if key in {
                "id",
                "material_id",
                "target_timerange",
                "source_timerange",
                "content",
                "text",
                "recognize_text",
                "name",
            }:
                continue
            clean[key] = _scrub_for_template(value)
        return clean
    if isinstance(obj, list):
        return [_scrub_for_template(item) for item in obj]
    return obj


def _fingerprint(obj: Any) -> str:
    payload = json.dumps(_scrub_for_template(obj), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _style_refs(material: dict[str, Any], segment: dict[str, Any]) -> dict[str, Any]:
    return {
        "material_id": material.get("id"),
        "style_id": material.get("style_id") or material.get("styleId") or material.get("preset_id"),
        "segment_type": segment.get("type"),
        "track_render_index": segment.get("render_index"),
        "font_sizes": _numbers_for_keys(material, FONT_KEYS),
        "scale_values": _scale_values(material) + _scale_values(segment),
        "position_values": _position_values(material) + _position_values(segment),
        "material_template_fingerprint": _fingerprint(material),
        "segment_template_fingerprint": _fingerprint(segment),
        "has_clip_transform": bool((segment.get("clip") or {}).get("transform") or (material.get("clip") or {}).get("transform")),
    }


def _max(values: list[float], default: float = 0.0) -> float:
    return max(values) if values else default


def audit_subtitle_style_integrity(
    source_subtitles: list[dict[str, Any]],
    final_text_segments: list[dict[str, Any]],
    final_text_materials: list[dict[str, Any]],
    *,
    output_path: Path | None = None,
) -> dict[str, Any]:
    source_refs = [
        _style_refs(row.get("material") or {}, row.get("segment") or {})
        for row in source_subtitles
    ]
    source_font_values = [value for ref in source_refs for value in ref["font_sizes"]]
    source_scale_values = [value for ref in source_refs for value in ref["scale_values"]]
    source_style_ids = {str(ref.get("style_id") or "") for ref in source_refs}
    source_segment_types = {str(ref.get("segment_type") or "") for ref in source_refs}
    source_material_fingerprints = {str(ref.get("material_template_fingerprint") or "") for ref in source_refs}
    source_segment_fingerprints = {str(ref.get("segment_template_fingerprint") or "") for ref in source_refs}
    source_position_values = [value for ref in source_refs for value in ref["position_values"]]

    material_by_id = {str(row.get("id") or ""): row for row in final_text_materials}
    baseline_max_font = _max(source_font_values)
    baseline_max_scale = _max(source_scale_values, 1.0)
    max_font_size = 0.0
    max_scale = 0.0
    outliers: list[dict[str, Any]] = []
    invalid_template_count = 0
    transform_outlier_count = 0
    position_outlier_count = 0
    template_fingerprint_mismatch_count = 0
    caption_track_template_mismatch_count = 0

    font_limit = max(80.0, baseline_max_font * 1.5) if baseline_max_font else 120.0
    scale_limit = max(3.0, baseline_max_scale * 1.5)
    baseline_min_position = min(source_position_values) if source_position_values else -2.0
    baseline_max_position = max(source_position_values) if source_position_values else 2.0
    position_margin = max(0.25, (baseline_max_position - baseline_min_position) * 0.25)
    for segment in final_text_segments:
        material_id = str(segment.get("material_id") or "")
        material = material_by_id.get(material_id, {})
        refs = _style_refs(material, segment)
        seg_font = _max(refs["font_sizes"])
        seg_scale = _max(refs["scale_values"], 1.0)
        max_font_size = max(max_font_size, seg_font)
        max_scale = max(max_scale, seg_scale)
        reasons: list[str] = []
        style_id = str(refs.get("style_id") or "")
        seg_type = str(refs.get("segment_type") or "")
        material_fp = str(refs.get("material_template_fingerprint") or "")
        segment_fp = str(refs.get("segment_template_fingerprint") or "")
        if source_style_ids and style_id and style_id not in source_style_ids:
            reasons.append("STYLE_ID_NOT_FROM_SOURCE_SUBTITLE_SET")
        if source_segment_types and seg_type and seg_type not in source_segment_types:
            reasons.append("SEGMENT_TYPE_NOT_FROM_SOURCE_SUBTITLE_SET")
        if source_material_fingerprints and material_fp and material_fp not in source_material_fingerprints:
            reasons.append("MATERIAL_TEMPLATE_FINGERPRINT_MISMATCH")
            template_fingerprint_mismatch_count += 1
        if source_segment_fingerprints and segment_fp and segment_fp not in source_segment_fingerprints:
            reasons.append("SEGMENT_TEMPLATE_FINGERPRINT_MISMATCH")
            caption_track_template_mismatch_count += 1
        if seg_font > font_limit:
            reasons.append("FONT_SIZE_OUTLIER")
        if seg_scale > scale_limit:
            reasons.append("SCALE_OUTLIER")
            transform_outlier_count += 1
        positions = refs["position_values"]
        if positions and any(value < baseline_min_position - position_margin or value > baseline_max_position + position_margin for value in positions):
            reasons.append("POSITION_OUTLIER")
            position_outlier_count += 1
        if not material:
            reasons.append("TEXT_MATERIAL_NOT_FOUND")
        if reasons:
            invalid_template_count += 1
            outliers.append(
                {
                    "text_segment_id": segment.get("id"),
                    "text_material_id": material_id,
                    "style_id": style_id,
                    "segment_type": seg_type,
                    "font_size": seg_font,
                    "scale": seg_scale,
                    "reasons": reasons,
                }
            )

    report = {
        "subtitle_style_outlier_count": len(outliers),
        "transform_outlier_count": transform_outlier_count,
        "position_outlier_count": position_outlier_count,
        "template_fingerprint_mismatch_count": template_fingerprint_mismatch_count,
        "caption_track_template_mismatch_count": caption_track_template_mismatch_count,
        "max_font_size": max_font_size,
        "max_scale": max_scale,
        "invalid_text_template_count": invalid_template_count,
        "style_integrity_gate_passed": len(outliers) == 0,
        "baseline_max_font_size": baseline_max_font,
        "baseline_max_scale": baseline_max_scale,
        "font_limit": font_limit,
        "scale_limit": scale_limit,
        "outliers": outliers[:50],
    }
    if output_path:
        write_json(output_path, report)
    return report
