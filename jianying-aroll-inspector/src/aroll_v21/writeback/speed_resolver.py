from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


EPSILON = 0.0001
SUPPORTED_SPEEDS = (1.0, 1.2)


@dataclass(frozen=True)
class SpeedResolution:
    speed: float
    speed_source: str
    speed_confidence: float
    speed_safe: bool
    source_target_ratio: float | None
    speed_mapping_reason: str
    report: dict[str, Any] = field(default_factory=dict)


class SpeedResolutionError(RuntimeError):
    def __init__(self, code: str, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context or {}


class SpeedResolver:
    def __init__(self, draft_data: dict[str, Any] | None = None) -> None:
        self.draft_data = draft_data or {}

    def resolve(self, segment: dict[str, Any], draft_data: dict[str, Any] | None = None) -> SpeedResolution:
        draft_data = draft_data or self.draft_data or {}
        speed_ref_ids = self._referenced_speed_ids(segment)
        speed_ref_count = len(speed_ref_ids)
        matched_speed_rows = self._referenced_speed_rows(segment, draft_data)
        if self._has_curve_speed(segment) or self._referenced_speed_has_curve(segment, draft_data):
            raise SpeedResolutionError(
                "V21_WRITEBACK_UNSUPPORTED_SPEED_MAPPING",
                "curve speed mapping is not supported",
                {"reason": "curve_speed_detected", "segment_id": str(segment.get("id") or "")},
            )
        if self._has_reverse(segment):
            raise SpeedResolutionError(
                "V21_WRITEBACK_UNSUPPORTED_SPEED_MAPPING",
                "reverse video mapping is not supported",
                {"reason": "reverse_speed_detected", "segment_id": str(segment.get("id") or "")},
            )

        explicit = self._explicit_speed(segment, draft_data)
        ratio = self._source_target_ratio(segment)
        speed_report_stats = {
            "speed_material_ref_count": len(matched_speed_rows),
            "extra_material_refs_scanned": speed_ref_count,
            "unparseable_speed_count": 0,
        }
        if explicit is not None:
            speed, source = explicit
            self._assert_supported(speed, source, ratio)
            if ratio is not None and abs(speed - ratio) > 0.01:
                raise SpeedResolutionError(
                    "V21_WRITEBACK_UNSUPPORTED_SPEED_MAPPING",
                    "explicit speed does not match source/target timerange ratio",
                    {
                        "detected_speed": speed,
                        "speed_source": source,
                        "source_target_ratio": ratio,
                        "reason": "speed_ratio_mismatch",
                    },
                )
            return self._resolution(speed, source, 0.98, ratio, "constant speed read from draft schema", speed_report_stats)
        if speed_ref_count and not matched_speed_rows:
            raise SpeedResolutionError(
                "V21_WRITEBACK_SPEED_UNPARSEABLE",
                "video segment references speed materials but none can be resolved",
                {
                    "reason": "speed_ref_unresolved",
                    "segment_id": str(segment.get("id") or ""),
                    "speed_ref_ids": sorted(speed_ref_ids),
                    **speed_report_stats,
                    "unparseable_speed_count": speed_ref_count,
                },
            )
        if ratio is not None:
            self._assert_supported(ratio, "source_target_ratio", ratio)
            return self._resolution(
                ratio,
                "source_target_ratio",
                0.9,
                ratio,
                "constant speed inferred from source/target timerange ratio",
                speed_report_stats,
            )
        raise SpeedResolutionError(
            "V21_WRITEBACK_UNSUPPORTED_SPEED_MAPPING",
            "video speed could not be resolved without silently defaulting to 1.0",
            {"reason": "speed_missing_and_ratio_unavailable", "segment_id": str(segment.get("id") or "")},
        )

    def _resolution(
        self,
        speed: float,
        source: str,
        confidence: float,
        ratio: float | None,
        reason: str,
        stats: dict[str, Any] | None = None,
    ) -> SpeedResolution:
        stats = stats or {}
        return SpeedResolution(
            speed=speed,
            speed_source=source,
            speed_confidence=confidence,
            speed_safe=True,
            source_target_ratio=ratio,
            speed_mapping_reason=reason,
            report={
                "detected_speed": speed,
                "speed_source": source,
                "speed_confidence": confidence,
                "speed_safe": True,
                "source_target_ratio": ratio,
                "speed_mapping_reason": reason,
                "speed_material_ref_count": int(stats.get("speed_material_ref_count") or 0),
                "extra_material_refs_scanned": int(stats.get("extra_material_refs_scanned") or 0),
                "unparseable_speed_count": int(stats.get("unparseable_speed_count") or 0),
            },
        )

    def _explicit_speed(self, segment: dict[str, Any], draft_data: dict[str, Any]) -> tuple[float, str] | None:
        for key in ("speed", "speed_ratio", "source_speed"):
            if segment.get(key) is not None:
                return self._parse_speed(segment.get(key), f"segment.{key}"), f"segment.{key}"
        extra = segment.get("extra")
        if isinstance(extra, dict):
            for key in ("speed", "speed_ratio"):
                if extra.get(key) is not None:
                    return self._parse_speed(extra.get(key), f"segment.extra.{key}"), f"segment.extra.{key}"
        referenced_rows = self._referenced_speed_rows(segment, draft_data)
        for speed_row, source in referenced_rows:
            for key in ("speed", "speed_ratio", "source_speed", "value", "speed_value"):
                if speed_row.get(key) is not None:
                    return self._parse_speed(
                        speed_row.get(key),
                        f"{source}.{key}",
                        code="V21_WRITEBACK_SPEED_UNPARSEABLE",
                    ), f"{source}.{key}"
        ref_ids = self._referenced_speed_ids(segment)
        if ref_ids and not referenced_rows:
            raise SpeedResolutionError(
                "V21_WRITEBACK_SPEED_UNPARSEABLE",
                "video segment references speed materials but none can be resolved",
                {
                    "reason": "speed_ref_unresolved",
                    "segment_id": str(segment.get("id") or ""),
                    "speed_ref_ids": sorted(ref_ids),
                    "speed_material_ref_count": 0,
                    "extra_material_refs_scanned": len(ref_ids),
                    "unparseable_speed_count": len(ref_ids),
                },
            )
        if referenced_rows:
            raise SpeedResolutionError(
                "V21_WRITEBACK_SPEED_UNPARSEABLE",
                "referenced speed material has no parseable constant speed value",
                {
                    "reason": "referenced_speed_missing_value",
                    "segment_id": str(segment.get("id") or ""),
                    "speed_material_ref_count": len(referenced_rows),
                    "extra_material_refs_scanned": len(self._referenced_speed_ids(segment)),
                    "unparseable_speed_count": len(referenced_rows),
                },
            )
        material = self._material_for_segment(segment, draft_data)
        if material:
            for key in ("speed", "speed_ratio", "source_speed"):
                if material.get(key) is not None:
                    return self._parse_speed(material.get(key), f"material.{key}"), f"material.{key}"
        return None

    def _referenced_speed_rows(self, segment: dict[str, Any], draft_data: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
        ref_ids = self._referenced_speed_ids(segment)
        materials = draft_data.get("materials") if isinstance(draft_data.get("materials"), dict) else {}
        rows: list[tuple[dict[str, Any], str]] = []
        for key in ("speeds", "speed"):
            for row in materials.get(key) or []:
                if not isinstance(row, dict):
                    continue
                row_id = str(row.get("id") or row.get("material_id") or row.get("materialId") or "")
                if ref_ids and row_id in ref_ids:
                    rows.append((row, f"materials.{key}"))
        return rows

    def _referenced_speed_ids(self, segment: dict[str, Any]) -> set[str]:
        ref_ids: set[str] = set()
        for key in ("referenced_materials", "references", "material_refs", "extra_material_refs"):
            self._collect_ref_ids(segment.get(key), ref_ids)
        return {value for value in ref_ids if value}

    def _collect_ref_ids(self, value: Any, ref_ids: set[str]) -> None:
        if isinstance(value, str):
            if value.strip():
                ref_ids.add(value.strip())
            return
        if isinstance(value, dict):
            for key in ("id", "material_id", "materialId", "ref_id", "refId", "speed_id", "speedId"):
                found = value.get(key)
                if isinstance(found, str) and found.strip():
                    ref_ids.add(found.strip())
            for nested in value.values():
                if isinstance(nested, (dict, list)):
                    self._collect_ref_ids(nested, ref_ids)
            return
        if isinstance(value, list):
            for item in value:
                self._collect_ref_ids(item, ref_ids)

    def _referenced_speed_has_curve(self, segment: dict[str, Any], draft_data: dict[str, Any]) -> bool:
        return any(self._has_curve_speed(row) for row, _source in self._referenced_speed_rows(segment, draft_data))

    def _material_for_segment(self, segment: dict[str, Any], draft_data: dict[str, Any]) -> dict[str, Any]:
        resolved = segment.get("_resolved_current_material_template")
        if isinstance(resolved, dict):
            return resolved
        material_id = str(segment.get("material_id") or segment.get("materialId") or "")
        if not material_id:
            return {}
        materials = draft_data.get("materials") if isinstance(draft_data.get("materials"), dict) else {}
        for key in ("videos", "video"):
            for row in materials.get(key) or []:
                if isinstance(row, dict) and str(row.get("id") or row.get("material_id") or "") == material_id:
                    return row
        return {}

    def _parse_speed(self, value: Any, source: str, *, code: str = "V21_WRITEBACK_UNSUPPORTED_SPEED_MAPPING") -> float:
        try:
            speed = float(value)
        except (TypeError, ValueError) as exc:
            raise SpeedResolutionError(
                code,
                "video speed value is not parseable",
                {
                    "speed_source": source,
                    "value": str(value),
                    "reason": "unparseable_speed",
                    "unparseable_speed_count": 1,
                },
            ) from exc
        if abs(speed) <= EPSILON:
            raise SpeedResolutionError(
                "V21_WRITEBACK_UNSUPPORTED_SPEED_MAPPING",
                "video speed value is zero",
                {"speed_source": source, "value": str(value), "reason": "zero_speed"},
            )
        return speed

    def _assert_supported(self, speed: float, source: str, ratio: float | None) -> None:
        if not any(abs(speed - supported) <= 0.01 for supported in SUPPORTED_SPEEDS):
            raise SpeedResolutionError(
                "V21_WRITEBACK_UNSUPPORTED_SPEED_MAPPING",
                "only constant 1.0x and 1.2x speed are supported",
                {"detected_speed": speed, "speed_source": source, "source_target_ratio": ratio},
            )

    def _source_target_ratio(self, segment: dict[str, Any]) -> float | None:
        source_duration = self._timerange_duration(segment.get("source_timerange"))
        target_duration = self._timerange_duration(segment.get("target_timerange"))
        if source_duration <= 0 or target_duration <= 0:
            return None
        return round(source_duration / target_duration, 4)

    def _timerange_duration(self, value: Any) -> int:
        return int(value.get("duration") or 0) if isinstance(value, dict) else 0

    def _has_curve_speed(self, obj: Any) -> bool:
        if isinstance(obj, dict):
            for key, value in obj.items():
                key_text = str(key).lower()
                if ("curve" in key_text and "speed" in key_text) or key_text in {"speed_curve", "curve_speed"}:
                    if value not in (None, False, "", [], {}):
                        return True
                if isinstance(value, (dict, list)) and self._has_curve_speed(value):
                    return True
        if isinstance(obj, list):
            return any(self._has_curve_speed(item) for item in obj)
        return False

    def _has_reverse(self, obj: Any) -> bool:
        if isinstance(obj, dict):
            for key, value in obj.items():
                key_text = str(key).lower()
                if key_text in {"reverse", "is_reverse", "reversed"} and bool(value):
                    return True
                if isinstance(value, (dict, list)) and self._has_reverse(value):
                    return True
        if isinstance(obj, list):
            return any(self._has_reverse(item) for item in obj)
        return False
