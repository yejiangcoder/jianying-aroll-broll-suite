from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EffectPolicyResult:
    safe: bool
    report: dict[str, Any] = field(default_factory=dict)
    blocker_code: str = ""
    blocker_message: str = ""


class EffectTrackPolicy:
    def inspect(
        self,
        draft_data: dict[str, Any],
        *,
        final_duration_us: int,
        allow_preserve_unsupported_effect_tracks: bool = False,
    ) -> EffectPolicyResult:
        effect_tracks = [
            track
            for track in draft_data.get("tracks") or []
            if isinstance(track, dict) and self._is_effect_track(track)
        ]
        embedded_report = self._embedded_effect_report(draft_data)
        embedded = bool(embedded_report.get("segment_embedded_effects_preserved"))
        report: dict[str, Any] = {
            "segment_embedded_effects_preserved": bool(embedded),
            "effect_policy_safe": True,
            "filter_track_detected": bool(effect_tracks),
            "effect_track_count": len(effect_tracks),
            "global_filter_effect_remapped": False,
            "unsupported_effect_track_count": 0,
            "allow_preserve_unsupported_effect_tracks": bool(allow_preserve_unsupported_effect_tracks),
            "effect_track_samples": [],
            **embedded_report,
        }
        if not effect_tracks:
            return EffectPolicyResult(True, report)

        unsupported: list[dict[str, Any]] = []
        global_count = 0
        for track in effect_tracks:
            for segment in track.get("segments") or []:
                if not isinstance(segment, dict):
                    continue
                sample = {
                    "track_id": str(track.get("id") or ""),
                    "segment_id": str(segment.get("id") or ""),
                    "classification": "",
                }
                if self._is_global_full_cover(segment, final_duration_us):
                    global_count += 1
                    sample["classification"] = "global_full_cover"
                else:
                    sample["classification"] = "timed_or_complex"
                    unsupported.append(sample)
                if len(report["effect_track_samples"]) < 10:
                    report["effect_track_samples"].append(sample)
        report["global_filter_effect_remapped"] = global_count > 0 and not unsupported
        report["unsupported_effect_track_count"] = len(unsupported)
        if unsupported and not allow_preserve_unsupported_effect_tracks:
            report["effect_policy_safe"] = False
            return EffectPolicyResult(
                False,
                report,
                blocker_code="V21_WRITEBACK_UNSUPPORTED_COMPLEX_EFFECT_TRACK",
                blocker_message="timed or complex filter/effect tracks are not safe to preserve by default",
            )
        return EffectPolicyResult(True, report)

    def _is_effect_track(self, track: dict[str, Any]) -> bool:
        text = str(track.get("type") or track.get("track_type") or track.get("name") or "").lower()
        return any(token in text for token in ("filter", "effect", "beauty", "adjust"))

    def _segment_embedded_effects_present(self, draft_data: dict[str, Any]) -> bool:
        return bool(self._embedded_effect_report(draft_data).get("segment_embedded_effects_preserved"))

    def _embedded_effect_report(self, draft_data: dict[str, Any]) -> dict[str, Any]:
        materials = draft_data.get("materials") if isinstance(draft_data.get("materials"), dict) else {}
        effect_ids = {
            str(row.get("id") or row.get("material_id") or row.get("materialId") or "")
            for row in materials.get("effects") or []
            if isinstance(row, dict)
        }
        material_color_count = len([row for row in materials.get("material_colors") or [] if isinstance(row, dict)])
        realtime_denoise_count = len([row for row in materials.get("realtime_denoises") or [] if isinstance(row, dict)])
        beauty_video_material_count = 0
        for row in materials.get("videos") or []:
            if not isinstance(row, dict):
                continue
            if self._video_material_has_beauty(row):
                beauty_video_material_count += 1
        effect_material_ref_count = 0
        beauty_material_ref_count = 0
        extra_material_refs_scanned = 0
        segment_key_effect_count = 0
        for track in draft_data.get("tracks") or []:
            if not isinstance(track, dict) or "video" not in str(track.get("type") or track.get("track_type") or "").lower():
                continue
            for segment in track.get("segments") or []:
                if not isinstance(segment, dict):
                    continue
                keys = {str(key).lower() for key in segment}
                if keys & {"beauty", "filters", "effects", "adjusts", "adjustments"}:
                    segment_key_effect_count += 1
                refs = self._collect_ref_ids(segment.get("extra_material_refs"))
                refs.update(self._collect_ref_ids(segment.get("referenced_materials")))
                refs.update(self._collect_ref_ids(segment.get("material_refs")))
                extra_material_refs_scanned += len(refs)
                effect_material_ref_count += len(effect_ids & refs)
                beauty_material_ref_count += len([ref for ref in refs if "beauty" in ref.lower() or "face" in ref.lower()])
        embedded = any(
            count > 0
            for count in (
                effect_material_ref_count,
                beauty_material_ref_count,
                beauty_video_material_count,
                realtime_denoise_count,
                material_color_count,
                segment_key_effect_count,
            )
        )
        return {
            "segment_embedded_effects_preserved": embedded,
            "effect_material_ref_count": effect_material_ref_count,
            "beauty_material_ref_count": beauty_material_ref_count,
            "beauty_video_material_count": beauty_video_material_count,
            "realtime_denoise_count": realtime_denoise_count,
            "material_color_count": material_color_count,
            "extra_material_refs_scanned": extra_material_refs_scanned,
            "segment_key_effect_count": segment_key_effect_count,
        }

    def _collect_ref_ids(self, value: Any) -> set[str]:
        refs: set[str] = set()
        if isinstance(value, str):
            if value.strip():
                refs.add(value.strip())
        elif isinstance(value, dict):
            for key in ("id", "material_id", "materialId", "ref_id", "refId", "effect_id", "effectId"):
                found = value.get(key)
                if isinstance(found, str) and found.strip():
                    refs.add(found.strip())
            for nested in value.values():
                if isinstance(nested, (dict, list)):
                    refs.update(self._collect_ref_ids(nested))
        elif isinstance(value, list):
            for item in value:
                refs.update(self._collect_ref_ids(item))
        return refs

    def _video_material_has_beauty(self, row: dict[str, Any]) -> bool:
        for key in (
            "beauty_face_preset_infos",
            "beauty_body_preset_id",
            "extra_type_option",
            "cartoon_path",
        ):
            value = row.get(key)
            if value not in (None, "", [], {}):
                return True
        return False

    def _is_global_full_cover(self, segment: dict[str, Any], final_duration_us: int) -> bool:
        timerange = segment.get("target_timerange") or segment.get("timerange")
        if not isinstance(timerange, dict):
            return bool(segment.get("is_global") or segment.get("global"))
        start = int(timerange.get("start") or 0)
        duration = int(timerange.get("duration") or 0)
        end = int(timerange.get("end") or (start + duration if duration else 0))
        return start <= 0 and end >= max(0, int(final_duration_us) - 1_000)
