from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any


FONT_KEYS = {"font_size", "fontsize", "fontSize", "text_size", "textSize", "size"}
SAFE_MAX_FONT_SIZE = 80.0
SAFE_MAX_SCALE = 3.0
SAFE_MAX_ABS_POSITION = 2.0
SAFE_MAX_SCREEN_OCCUPANCY = 0.45


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


def _occupancy_values(obj: Any) -> list[float]:
    values: list[float] = []
    width_keys = ("width", "w", "box_width", "boxWidth")
    height_keys = ("height", "h", "box_height", "boxHeight")
    canvas_width_keys = ("canvas_width", "canvasWidth", "project_width", "projectWidth")
    canvas_height_keys = ("canvas_height", "canvasHeight", "project_height", "projectHeight")
    ratio_keys = {"occupancy", "screen_occupancy", "screenOccupancy", "canvas_ratio", "canvasRatio"}
    for node in _walk(obj):
        for key, value in node.items():
            if key in ratio_keys and isinstance(value, (int, float)):
                ratio = float(value)
                if ratio > 1.0 and ratio <= 100.0:
                    ratio /= 100.0
                if ratio >= 0:
                    values.append(ratio)
        width = next((float(node[key]) for key in width_keys if isinstance(node.get(key), (int, float))), None)
        height = next((float(node[key]) for key in height_keys if isinstance(node.get(key), (int, float))), None)
        if width is None or height is None or width <= 0 or height <= 0:
            continue
        canvas_width = next((float(node[key]) for key in canvas_width_keys if isinstance(node.get(key), (int, float))), None)
        canvas_height = next((float(node[key]) for key in canvas_height_keys if isinstance(node.get(key), (int, float))), None)
        if canvas_width and canvas_height and canvas_width > 0 and canvas_height > 0:
            values.append((width * height) / (canvas_width * canvas_height))
        elif width <= 1.2 and height <= 1.2:
            values.append(width * height)
    return values


def _scrub_content_payload_for_template(value: Any) -> Any:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return "<invalid_text_content_json>"
    elif isinstance(value, dict):
        parsed = value
    else:
        return "<invalid_text_content_schema>"
    return _scrub_for_template(parsed, in_text_content=True)


def _scrub_for_template(obj: Any, *, in_text_content: bool = False) -> Any:
    if isinstance(obj, dict):
        clean: dict[str, Any] = {}
        for key, value in obj.items():
            if key in {
                "id",
                "material_id",
                "target_timerange",
                "source_timerange",
                "text",
                "recognize_text",
                "name",
            }:
                continue
            if key in {"content", "base_content"}:
                clean[key] = _scrub_content_payload_for_template(value)
                continue
            if in_text_content and key == "range":
                continue
            clean[key] = _scrub_for_template(value, in_text_content=in_text_content)
        return clean
    if isinstance(obj, list):
        return [_scrub_for_template(item, in_text_content=in_text_content) for item in obj]
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
        "font_sizes": _numbers_for_keys(material, FONT_KEYS) + _numbers_for_keys(segment, FONT_KEYS),
        "scale_values": _scale_values(material) + _scale_values(segment),
        "position_values": _position_values(material) + _position_values(segment),
        "occupancy_values": _occupancy_values(material) + _occupancy_values(segment),
        "material_template_fingerprint": _fingerprint(material),
        "segment_template_fingerprint": _fingerprint(segment),
        "has_clip_transform": bool((segment.get("clip") or {}).get("transform") or (material.get("clip") or {}).get("transform")),
    }


def _parse_text_content_payload(value: Any) -> tuple[dict[str, Any] | None, str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None, "TEXT_CONTENT_NOT_JSON"
    elif isinstance(value, dict):
        parsed = value
    else:
        return None, "TEXT_CONTENT_SCHEMA_MISMATCH"
    if not isinstance(parsed, dict):
        return None, "TEXT_CONTENT_SCHEMA_MISMATCH"
    return parsed, ""


def text_content_schema_issues(material: dict[str, Any], required_keys: set[str] | None = None) -> list[str]:
    issues: list[str] = []
    required_keys = required_keys or set()
    for key in ("content", "base_content"):
        if key not in material:
            if key in required_keys:
                issues.append("TEXT_CONTENT_SCHEMA_MISMATCH")
            continue
        payload, error = _parse_text_content_payload(material.get(key))
        if error:
            issues.append(error)
            continue
        if payload is None:
            issues.append("TEXT_CONTENT_SCHEMA_MISMATCH")
            continue
        if "text" not in payload or not isinstance(payload.get("text"), str):
            issues.append("TEXT_CONTENT_SCHEMA_MISMATCH")
        styles = payload.get("styles")
        if not isinstance(styles, list) or not styles:
            issues.append("TEXT_CONTENT_MISSING_STYLES")
    return list(dict.fromkeys(issues))


def _max(values: list[float], default: float = 0.0) -> float:
    return max(values) if values else default


def subtitle_style_safety_issues(material: dict[str, Any], segment: dict[str, Any]) -> list[str]:
    refs = _style_refs(material, segment)
    issues: list[str] = []
    if _max(refs["font_sizes"]) > SAFE_MAX_FONT_SIZE:
        issues.append("FONT_SIZE_EXCEEDS_SAFE_LIMIT")
    if _max(refs["scale_values"], 1.0) > SAFE_MAX_SCALE:
        issues.append("SCALE_EXCEEDS_SAFE_LIMIT")
    if any(abs(value) > SAFE_MAX_ABS_POSITION for value in refs["position_values"]):
        issues.append("POSITION_EXCEEDS_SAFE_LIMIT")
    if _max(refs["occupancy_values"]) > SAFE_MAX_SCREEN_OCCUPANCY:
        issues.append("SCREEN_OCCUPANCY_EXCEEDS_SAFE_LIMIT")
    issues.extend(text_content_schema_issues(material))
    return issues


def is_safe_subtitle_style(material: dict[str, Any], segment: dict[str, Any]) -> bool:
    return not subtitle_style_safety_issues(material, segment)


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
    source_content_keys: set[str] = set()
    for row in source_subtitles:
        source_material = row.get("material") or {}
        for key in ("content", "base_content"):
            if key in source_material and not text_content_schema_issues({key: source_material.get(key)}):
                source_content_keys.add(key)

    material_by_id = {str(row.get("id") or ""): row for row in final_text_materials}
    baseline_max_font = _max(source_font_values)
    baseline_max_scale = _max(source_scale_values, 1.0)
    max_font_size = 0.0
    max_scale = 0.0
    outliers: list[dict[str, Any]] = []
    invalid_template_count = 0
    transform_outlier_count = 0
    position_outlier_count = 0
    style_safety_violation_count = 0
    template_fingerprint_mismatch_count = 0
    caption_track_template_mismatch_count = 0
    text_content_schema_violation_count = 0

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
        content_issues = text_content_schema_issues(material, required_keys=source_content_keys)
        safety_issues = list(dict.fromkeys(subtitle_style_safety_issues(material, segment) + content_issues))
        if safety_issues:
            style_safety_violation_count += 1
            for issue in safety_issues:
                if issue not in reasons:
                    reasons.append(issue)
        if content_issues:
            text_content_schema_violation_count += 1
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
                    "max_screen_occupancy": _max(refs["occupancy_values"]),
                    "reasons": reasons,
                }
            )

    report = {
        "subtitle_style_outlier_count": len(outliers),
        "transform_outlier_count": transform_outlier_count,
        "position_outlier_count": position_outlier_count,
        "style_safety_violation_count": style_safety_violation_count,
        "template_fingerprint_mismatch_count": template_fingerprint_mismatch_count,
        "caption_track_template_mismatch_count": caption_track_template_mismatch_count,
        "text_content_schema_violation_count": text_content_schema_violation_count,
        "max_font_size": max_font_size,
        "max_scale": max_scale,
        "invalid_text_template_count": invalid_template_count,
        "style_integrity_gate_passed": len(outliers) == 0,
        "baseline_max_font_size": baseline_max_font,
        "baseline_max_scale": baseline_max_scale,
        "font_limit": font_limit,
        "scale_limit": scale_limit,
        "safe_max_font_size": SAFE_MAX_FONT_SIZE,
        "safe_max_scale": SAFE_MAX_SCALE,
        "safe_max_abs_position": SAFE_MAX_ABS_POSITION,
        "safe_max_screen_occupancy": SAFE_MAX_SCREEN_OCCUPANCY,
        "outliers": outliers[:50],
    }
    if output_path:
        write_json(output_path, report)
    return report
