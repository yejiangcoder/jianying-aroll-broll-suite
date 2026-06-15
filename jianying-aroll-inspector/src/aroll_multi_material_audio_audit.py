from __future__ import annotations

import json
import math
from array import array
from copy import deepcopy
from pathlib import Path
from typing import Any

from aroll_inspect import segment_end, segment_start, timerange_duration, timerange_start
from aroll_postwrite_audio_audit import (
    _frame_db,
    _load_samples,
    _pause_type,
    compact_source_intervals,
    detect_audio_silence_islands,
    high_energy_ratio,
    nearest_words,
    words_inside_plan,
)
from aroll_safe_gap_cutter import FRAME_US, SafeGapCutter
from aroll_speed_mapping import (
    display_to_material_delta,
    ensure_clip_time_fields,
    material_to_display_delta,
    source_timeline_to_material_time,
)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _material_lookup(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for material in ((data.get("materials") or {}).get("videos") or []):
        mid = str(material.get("id") or "")
        if not mid:
            continue
        out[mid] = {
            "material_id": mid,
            "source_material_id": mid,
            "source_material_path": str(material.get("path") or ""),
            "source_material_name": str(material.get("material_name") or Path(str(material.get("path") or "")).name),
            "source_material_duration_us": int(material.get("duration") or 0),
        }
    return out


def annotate_edl_with_materials(
    old_video_segments: list[dict[str, Any]],
    edl: list[dict[str, Any]],
    data: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    materials = _material_lookup(data)
    annotated: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    clips_by_material: dict[str, int] = {}
    for clip in sorted(edl, key=lambda row: int(row.get("target_start_us") or 0)):
        cut_start = int(clip.get("source_timeline_start_us") or clip.get("source_start_us") or clip.get("cut_start_us") or 0)
        cut_end = int(clip.get("source_timeline_end_us") or clip.get("source_end_us") or clip.get("cut_end_us") or cut_start)
        target_base = int(clip.get("target_start_us") or 0)
        piece_index = 0
        for old_segment in old_video_segments:
            old_target_start = segment_start(old_segment)
            old_target_end = segment_end(old_segment)
            overlap_start = max(cut_start, old_target_start)
            overlap_end = min(cut_end, old_target_end)
            if overlap_end <= overlap_start:
                continue
            material_id = str(old_segment.get("material_id") or "")
            material = materials.get(material_id, {})
            if not material.get("source_material_path"):
                missing.append({"clip_id": clip.get("clip_id"), "material_id": material_id, "reason": "material path missing"})
            old_source_start = timerange_start(old_segment.get("source_timerange") or {})
            old_source_duration = timerange_duration(old_segment.get("source_timerange") or {})
            old_target_duration = timerange_duration(old_segment.get("target_timerange") or {})
            speed = float(clip.get("speed") or (old_source_duration / old_target_duration if old_target_duration > 0 else 1.0))
            local_start = source_timeline_to_material_time(overlap_start, old_target_start, old_source_start, speed)
            local_duration = display_to_material_delta(overlap_end - overlap_start, speed)
            local_end = local_start + local_duration
            piece = deepcopy(clip)
            piece_index += 1
            if piece_index > 1 or overlap_start != cut_start or overlap_end != cut_end:
                piece["clip_id"] = f"{clip.get('clip_id')}_m{piece_index:02d}"
                piece["parent_clip_id"] = clip.get("clip_id")
            piece["source_start_us"] = overlap_start
            piece["source_end_us"] = overlap_end
            piece["cut_start_us"] = overlap_start
            piece["cut_end_us"] = overlap_end
            piece["target_start_us"] = target_base + (overlap_start - cut_start)
            piece["target_duration_us"] = overlap_end - overlap_start
            piece.update(material)
            piece["source_segment_id"] = old_segment.get("id")
            piece["speed"] = speed
            piece["source_timeline_start_us"] = overlap_start
            piece["source_timeline_end_us"] = overlap_end
            piece["material_start_us"] = local_start
            piece["material_end_us"] = local_end
            piece["source_local_start_us"] = local_start
            piece["source_local_end_us"] = local_end
            ensure_clip_time_fields(piece, speed)
            annotated.append(piece)
            key = str(material.get("source_material_path") or material_id or "UNKNOWN")
            clips_by_material[key] = clips_by_material.get(key, 0) + 1
    annotated.sort(key=lambda row: int(row.get("target_start_us") or 0))
    material_paths = sorted({str(row.get("source_material_path") or "") for row in annotated if row.get("source_material_path")})
    report = {
        "source_material_count": len(material_paths),
        "source_materials": material_paths,
        "clips_missing_material_path": len(missing),
        "clips_by_material": clips_by_material,
        "audio_audit_valid_for_full_timeline": len(missing) == 0 and len(annotated) == len(edl) if len(material_paths) <= 1 else len(missing) == 0,
        "fatal_reasons": ["CLIPS_MISSING_SOURCE_MATERIAL_PATH"] if missing else [],
        "missing": missing,
        "input_clip_count": len(edl),
        "annotated_clip_count": len(annotated),
    }
    return annotated, report


def _load_material_samples(clips: list[dict[str, Any]], run_dir: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    cache: dict[str, dict[str, Any]] = {}
    missing: list[dict[str, Any]] = []
    for clip in clips:
        path = str(clip.get("source_material_path") or "")
        if not path:
            missing.append({"clip_id": clip.get("clip_id"), "reason": "missing source_material_path"})
            continue
        if path in cache:
            continue
        cutter = SafeGapCutter(path, run_dir / "audio_vad" / Path(path).stem)
        cache[path] = {
            "cutter": cutter,
            "samples": _load_samples(cutter.raw_path),
            "raw_path": str(cutter.raw_path),
            "resolved_path": str(cutter.video_path),
        }
    return cache, missing


def build_virtual_audio_frames_multi_material(
    clips: list[dict[str, Any]],
    run_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cache, missing = _load_material_samples(clips, run_dir)
    frames: list[dict[str, Any]] = []
    for clip in sorted(clips, key=lambda row: int(row.get("target_start_us") or 0)):
        path = str(clip.get("source_material_path") or "")
        material = cache.get(path)
        if material is None:
            continue
        samples = material["samples"]
        local_start = int(clip.get("material_start_us") or clip.get("source_local_start_us") or 0)
        local_end = int(clip.get("material_end_us") or clip.get("source_local_end_us") or local_start)
        global_start = int(clip.get("source_timeline_start_us") or clip.get("source_start_us") or 0)
        target_start = int(clip.get("target_start_us") or 0)
        speed = float(clip.get("speed") or 1.0)
        target_duration = int(clip.get("target_duration_us") or material_to_display_delta(local_end - local_start, speed))
        target_pos = 0
        while target_pos < target_duration:
            target_frame_end = min(target_duration, target_pos + FRAME_US)
            pos = local_start + display_to_material_delta(target_pos, speed)
            frame_end = min(local_end, local_start + display_to_material_delta(target_frame_end, speed))
            source_timeline_start = global_start + target_pos
            source_timeline_end = global_start + target_frame_end
            frames.append(
                {
                    "target_start_us": target_start + target_pos,
                    "target_end_us": target_start + target_frame_end,
                    "source_start_us": source_timeline_start,
                    "source_end_us": source_timeline_end,
                    "source_local_start_us": pos,
                    "source_local_end_us": frame_end,
                    "material_start_us": pos,
                    "material_end_us": frame_end,
                    "source_timeline_start_us": source_timeline_start,
                    "source_timeline_end_us": source_timeline_end,
                    "source_material_path": path,
                    "speed": speed,
                    "clip_id": clip.get("clip_id"),
                    "fragment_id": clip.get("fragment_id"),
                    "db": _frame_db(samples, pos, frame_end),
                }
            )
            target_pos = target_frame_end
    db_values = [float(row["db"]) for row in frames]
    if db_values:
        ordered = sorted(db_values)
        p30 = ordered[int(len(ordered) * 0.30)]
        threshold = min(-26.0, p30 + 7.0)
    else:
        p30 = -60.0
        threshold = -45.0
    return frames, {
        "threshold_db": threshold,
        "db_p30": p30,
        "frame_count": len(frames),
        "source_material_count": len(cache),
        "source_materials": [
            {"source_material_path": path, "raw_path": row["raw_path"], "resolved_path": row["resolved_path"]}
            for path, row in cache.items()
        ],
        "missing": missing,
    }


def map_source_to_target(source_us: int, clips: list[dict[str, Any]]) -> tuple[int | None, dict[str, Any] | None]:
    for clip in clips:
        source_start = int(clip["source_start_us"])
        source_end = int(clip["source_end_us"])
        if source_start <= source_us <= source_end:
            return int(clip["target_start_us"]) + (source_us - source_start), clip
    return None, None


def audit_postwrite_audio_multi_material(
    clips: list[dict[str, Any]],
    subtitle_plan: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
    run_dir: Path,
) -> tuple[dict[str, Any], str]:
    frames, frame_report = build_virtual_audio_frames_multi_material(clips, run_dir)
    words = words_inside_plan(word_timeline, subtitle_plan)
    mapped_words: list[dict[str, Any]] = []
    for word in words:
        target_start, clip_start = map_source_to_target(int(word["start_us"]), clips)
        target_end, clip_end = map_source_to_target(int(word["end_us"]), clips)
        if target_start is None or target_end is None or clip_start is None or clip_end is None:
            continue
        mapped_words.append(
            word | {
                "target_start_us": target_start,
                "target_end_us": max(target_start, target_end),
                "clip_id": clip_start.get("clip_id"),
                "clip_id_end": clip_end.get("clip_id"),
            }
        )
    pauses: list[dict[str, Any]] = []
    audio_islands = detect_audio_silence_islands(frames, float(frame_report["threshold_db"]))
    for island in audio_islands:
        start = int(island["target_start_us"])
        end = int(island["target_end_us"])
        duration = int(island["duration_us"])
        left_word, right_word = nearest_words(mapped_words, start, end)
        left_clip_id = str(island.get("source_clip_id_left") or "")
        right_clip_id = str(island.get("source_clip_id_right") or "")
        if left_clip_id != right_clip_id:
            pause_type = "inter_clip"
        elif left_word and right_word and str(left_word.get("fragment_id")) == str(right_word.get("fragment_id")):
            pause_type = "intra_subtitle_group"
        elif left_word and right_word:
            pause_type = "intra_clip"
        else:
            pause_type = "unknown"
        ratio = high_energy_ratio(frames, start, end, float(frame_report["threshold_db"]))
        recommended = "cut" if duration >= 140_000 and ratio < 0.30 else "manual_review"
        pauses.append(
            {
                "pause_id": f"pa_{len(pauses) + 1:03d}",
                "detection_source": "audio_silence_island",
                "target_start_us": start,
                "target_end_us": end,
                "duration_us": duration,
                "duration_ms": round(duration / 1000, 3),
                "source_clip_id_left": left_clip_id,
                "source_clip_id_right": right_clip_id,
                "mapped_source_start_us": int(island["mapped_source_start_us"]),
                "mapped_source_end_us": int(island["mapped_source_end_us"]),
                "source_intervals": compact_source_intervals(island.get("frame_intervals") or []),
                "pause_type": pause_type,
                "left_text": str((left_word or {}).get("word_text") or ""),
                "right_text": str((right_word or {}).get("word_text") or ""),
                "left_fragment_text": str((left_word or {}).get("fragment_text") or ""),
                "right_fragment_text": str((right_word or {}).get("fragment_text") or ""),
                "energy_db": round(float(island["min_db"]), 3),
                "speech_ratio": round(ratio, 4),
                "recommended_action": recommended,
                "reason": "audio low-energy silence island" if recommended == "cut" else "possible speech energy in island",
                "left_word": {
                    "word_id": (left_word or {}).get("word_id"),
                    "source_start_us": (left_word or {}).get("start_us"),
                    "source_end_us": (left_word or {}).get("end_us"),
                    "target_start_us": (left_word or {}).get("target_start_us"),
                    "target_end_us": (left_word or {}).get("target_end_us"),
                },
                "right_word": {
                    "word_id": (right_word or {}).get("word_id"),
                    "source_start_us": (right_word or {}).get("start_us"),
                    "source_end_us": (right_word or {}).get("end_us"),
                    "target_start_us": (right_word or {}).get("target_start_us"),
                    "target_end_us": (right_word or {}).get("target_end_us"),
                },
            }
        )
    for left, right in zip(mapped_words, mapped_words[1:]):
        start = int(left["target_end_us"])
        end = int(right["target_start_us"])
        duration = end - start
        if duration < 140_000:
            continue
        covered = any(not (int(row["target_end_us"]) <= start or int(row["target_start_us"]) >= end) for row in pauses)
        if covered:
            continue
        left_clip = next((clip for clip in clips if str(clip.get("clip_id")) == str(left.get("clip_id"))), {})
        right_clip = next((clip for clip in clips if str(clip.get("clip_id")) == str(right.get("clip_id"))), {})
        ratio = high_energy_ratio(frames, start, end, float(frame_report["threshold_db"]))
        pause_type = _pause_type(left, right, left_clip, right_clip) if left_clip and right_clip else "unknown"
        recommended = "cut" if duration >= 140_000 and ratio < 0.30 else ("manual_review" if duration >= 220_000 else "keep")
        pauses.append(
            {
                "pause_id": f"pa_{len(pauses) + 1:03d}",
                "detection_source": "word_gap",
                "target_start_us": start,
                "target_end_us": end,
                "duration_us": duration,
                "duration_ms": round(duration / 1000, 3),
                "source_clip_id_left": left.get("clip_id"),
                "source_clip_id_right": right.get("clip_id"),
                "mapped_source_start_us": int(left.get("end_us") or 0),
                "mapped_source_end_us": int(right.get("start_us") or 0),
                "pause_type": pause_type,
                "left_text": left.get("word_text") or "",
                "right_text": right.get("word_text") or "",
                "left_fragment_text": left.get("fragment_text") or "",
                "right_fragment_text": right.get("fragment_text") or "",
                "energy_db": round(min((float(row["db"]) for row in frames if int(row["target_end_us"]) > start and int(row["target_start_us"]) < end), default=-96.0), 3),
                "speech_ratio": round(ratio, 4),
                "recommended_action": recommended,
                "reason": "confirmed low-energy pause" if recommended == "cut" else "short pause or possible speech",
                "left_word": {
                    "word_id": left.get("word_id"),
                    "source_start_us": left.get("start_us"),
                    "source_end_us": left.get("end_us"),
                    "target_start_us": left.get("target_start_us"),
                    "target_end_us": left.get("target_end_us"),
                },
                "right_word": {
                    "word_id": right.get("word_id"),
                    "source_start_us": right.get("start_us"),
                    "source_end_us": right.get("end_us"),
                    "target_start_us": right.get("target_start_us"),
                    "target_end_us": right.get("target_end_us"),
                },
            }
        )
    type_counts: dict[str, int] = {}
    for row in pauses:
        key = str(row.get("pause_type") or "unknown")
        type_counts[key] = type_counts.get(key, 0) + 1
    hard = [row for row in pauses if int(row["duration_us"]) >= 220_000]
    cut_rows = [row for row in pauses if row.get("recommended_action") == "cut"]
    report = {
        "virtual_final_audio_generated": False,
        "virtual_final_audio_scanned": True,
        "audio_mode": "multi_material_in_memory_virtual_timeline",
        "frame_report": frame_report,
        "detected_pause_count": len(pauses),
        "pause_ge_140ms_count": len(pauses),
        "pause_ge_220ms_count": len(hard),
        "cut_recommended_count": len(cut_rows),
        "audio_silence_island_count": len(audio_islands),
        "type_counts": type_counts,
        "pauses": pauses,
        "top_10_pauses": sorted(pauses, key=lambda row: int(row["duration_us"]), reverse=True)[:10],
    }
    lines = [
        "# Multi-material Post-write Audio Pause Review",
        "",
        f"- virtual_final_audio_scanned: true",
        f"- source_material_count: {frame_report.get('source_material_count')}",
        f"- detected_pause_count: {report['detected_pause_count']}",
        f"- pause_ge_220ms_count: {report['pause_ge_220ms_count']}",
        f"- cut_recommended_count: {report['cut_recommended_count']}",
        f"- threshold_db: {round(float(frame_report['threshold_db']), 3)}",
        "",
        "## Top pauses",
    ]
    for row in report["top_10_pauses"]:
        lines.append(
            f"- {row['pause_id']} {row['duration_ms']}ms {row['pause_type']} "
            f"{row['left_text']} -> {row['right_text']} action={row['recommended_action']} speech_ratio={row['speech_ratio']}"
        )
    return report, "\n".join(lines) + "\n"
