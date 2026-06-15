from __future__ import annotations

import json
import math
import statistics
from array import array
from pathlib import Path
from typing import Any

from aroll_safe_gap_cutter import FRAME_US, SAMPLE_RATE, SafeGapCutter
from aroll_speed_mapping import display_to_material_delta, material_to_display_delta


MIN_PAUSE_US = 140_000
HARD_PAUSE_US = 220_000
TARGET_KEEP_PAUSE_US = 220_000


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _load_samples(raw_path: Path) -> array:
    samples = array("h")
    samples.frombytes(raw_path.read_bytes())
    return samples


def _frame_db(samples: array, start_us: int, end_us: int) -> float:
    start_sample = max(0, int(start_us * SAMPLE_RATE / 1_000_000))
    end_sample = min(len(samples), int(end_us * SAMPLE_RATE / 1_000_000))
    if end_sample <= start_sample:
        return -96.0
    frame = samples[start_sample:end_sample]
    rms = math.sqrt(sum(int(x) * int(x) for x in frame) / len(frame))
    return 20 * math.log10(max(1.0, rms) / 32768.0)


def build_virtual_audio_frames(clips: list[dict[str, Any]], raw_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    samples = _load_samples(raw_path)
    frames: list[dict[str, Any]] = []
    for clip in sorted(clips, key=lambda row: int(row.get("target_start_us") or 0)):
        source_start = int(clip.get("source_timeline_start_us") or clip["source_start_us"])
        source_end = int(clip.get("source_timeline_end_us") or clip["source_end_us"])
        material_start = int(clip.get("material_start_us") or source_start)
        material_end = int(clip.get("material_end_us") or source_end)
        speed = float(clip.get("speed") or 1.0)
        target_start = int(clip["target_start_us"])
        target_duration = int(clip.get("target_duration_us") or material_to_display_delta(material_end - material_start, speed))
        target_pos = 0
        while target_pos < target_duration:
            target_frame_end = min(target_duration, target_pos + FRAME_US)
            pos = material_start + display_to_material_delta(target_pos, speed)
            frame_end = min(material_end, material_start + display_to_material_delta(target_frame_end, speed))
            frames.append(
                {
                    "target_start_us": target_start + target_pos,
                    "target_end_us": target_start + target_frame_end,
                    "source_start_us": source_start + target_pos,
                    "source_end_us": source_start + target_frame_end,
                    "source_timeline_start_us": source_start + target_pos,
                    "source_timeline_end_us": source_start + target_frame_end,
                    "material_start_us": pos,
                    "material_end_us": frame_end,
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
    return frames, {"threshold_db": threshold, "db_p30": p30, "frame_count": len(frames)}


def words_inside_plan(words: list[dict[str, Any]], subtitle_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in subtitle_plan:
        indices = {int(item) for item in group.get("source_subtitle_indices") or []}
        source_start = int(group.get("source_start_us") or 0)
        source_end = int(group.get("source_end_us") or 0)
        for word in words:
            if int(word.get("subtitle_index") or -1) not in indices:
                continue
            start = int(word.get("start_us") or 0)
            end = int(word.get("end_us") or start)
            if end <= source_start or start >= source_end:
                continue
            rows.append(word | {"fragment_id": group.get("fragment_id"), "fragment_text": group.get("fragment_text")})
    rows.sort(key=lambda row: int(row.get("start_us") or 0))
    return rows


def map_source_to_target(source_us: int, clips: list[dict[str, Any]]) -> tuple[int | None, dict[str, Any] | None]:
    for clip in clips:
        source_start = int(clip["source_start_us"])
        source_end = int(clip["source_end_us"])
        if source_start <= source_us <= source_end:
            return int(clip["target_start_us"]) + (source_us - source_start), clip
    return None, None


def high_energy_ratio(frames: list[dict[str, Any]], start_us: int, end_us: int, threshold_db: float) -> float:
    selected = [
        row for row in frames
        if int(row["target_end_us"]) > start_us and int(row["target_start_us"]) < end_us
    ]
    if not selected:
        return 0.0
    high = sum(1 for row in selected if float(row["db"]) > threshold_db)
    return high / len(selected)


def target_to_source(target_us: int, frames: list[dict[str, Any]]) -> tuple[int | None, dict[str, Any] | None]:
    for frame in frames:
        start = int(frame["target_start_us"])
        end = int(frame["target_end_us"])
        if start <= target_us <= end:
            return int(frame["source_start_us"]) + (target_us - start), frame
    return None, None


def nearest_words(mapped_words: list[dict[str, Any]], start_us: int, end_us: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    left = [row for row in mapped_words if int(row.get("target_end_us") or 0) <= start_us]
    right = [row for row in mapped_words if int(row.get("target_start_us") or 0) >= end_us]
    left_word = max(left, key=lambda row: int(row.get("target_end_us") or 0)) if left else None
    right_word = min(right, key=lambda row: int(row.get("target_start_us") or 0)) if right else None
    return left_word, right_word


def detect_audio_silence_islands(frames: list[dict[str, Any]], threshold_db: float) -> list[dict[str, Any]]:
    islands: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for frame in frames:
        silent = float(frame["db"]) <= threshold_db
        if silent and current is None:
            current = {
                "target_start_us": int(frame["target_start_us"]),
                "target_end_us": int(frame["target_end_us"]),
                "mapped_source_start_us": int(frame["source_start_us"]),
                "mapped_source_end_us": int(frame["source_end_us"]),
                "source_clip_id_left": frame.get("clip_id"),
                "source_clip_id_right": frame.get("clip_id"),
                "frame_intervals": [
                    {
                        "clip_id": frame.get("clip_id"),
                        "source_start_us": int(frame["source_start_us"]),
                        "source_end_us": int(frame["source_end_us"]),
                    }
                ],
                "min_db": float(frame["db"]),
                "max_db": float(frame["db"]),
                "db_values": [float(frame["db"])],
            }
        elif silent and current is not None:
            current["target_end_us"] = int(frame["target_end_us"])
            current["mapped_source_end_us"] = int(frame["source_end_us"])
            current["source_clip_id_right"] = frame.get("clip_id")
            current["frame_intervals"].append(
                {
                    "clip_id": frame.get("clip_id"),
                    "source_start_us": int(frame["source_start_us"]),
                    "source_end_us": int(frame["source_end_us"]),
                }
            )
            current["min_db"] = min(float(current["min_db"]), float(frame["db"]))
            current["max_db"] = max(float(current["max_db"]), float(frame["db"]))
            current["db_values"].append(float(frame["db"]))
        elif current is not None:
            duration = int(current["target_end_us"]) - int(current["target_start_us"])
            if duration >= MIN_PAUSE_US:
                values = current.pop("db_values")
                current["duration_us"] = duration
                current["avg_db"] = sum(values) / len(values)
                islands.append(current)
            current = None
    if current is not None:
        duration = int(current["target_end_us"]) - int(current["target_start_us"])
        if duration >= MIN_PAUSE_US:
            values = current.pop("db_values")
            current["duration_us"] = duration
            current["avg_db"] = sum(values) / len(values)
            islands.append(current)
    return islands


def _pause_type(left_word: dict[str, Any], right_word: dict[str, Any], left_clip: dict[str, Any], right_clip: dict[str, Any]) -> str:
    if str(left_clip.get("clip_id")) != str(right_clip.get("clip_id")):
        return "inter_clip"
    if str(left_word.get("fragment_id")) != str(right_word.get("fragment_id")):
        return "intra_clip"
    if str(left_word.get("subtitle_uid")) == str(right_word.get("subtitle_uid")):
        return "intra_subtitle_group"
    return "intra_subtitle_group"


def audit_postwrite_audio(
    clips: list[dict[str, Any]],
    subtitle_plan: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
    cutter: SafeGapCutter,
) -> tuple[dict[str, Any], str]:
    frames, frame_report = build_virtual_audio_frames(clips, cutter.raw_path)
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
        left_text = str((left_word or {}).get("word_text") or "")
        right_text = str((right_word or {}).get("word_text") or "")
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
        recommended = "cut" if duration >= MIN_PAUSE_US and ratio < 0.30 else "manual_review"
        pause_id = f"pa_{len(pauses) + 1:03d}"
        pauses.append(
            {
                "pause_id": pause_id,
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
                "left_text": left_text,
                "right_text": right_text,
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
    # Also keep word-gap diagnostics not already covered by an audio silence island.
    for left, right in zip(mapped_words, mapped_words[1:]):
        start = int(left["target_end_us"])
        end = int(right["target_start_us"])
        duration = end - start
        if duration < MIN_PAUSE_US:
            continue
        covered = any(
            not (int(row["target_end_us"]) <= start or int(row["target_start_us"]) >= end)
            for row in pauses
        )
        if covered:
            continue
        left_clip = next((clip for clip in clips if str(clip.get("clip_id")) == str(left.get("clip_id"))), {})
        right_clip = next((clip for clip in clips if str(clip.get("clip_id")) == str(right.get("clip_id"))), {})
        ratio = high_energy_ratio(frames, start, end, float(frame_report["threshold_db"]))
        pause_type = _pause_type(left, right, left_clip, right_clip) if left_clip and right_clip else "unknown"
        recommended = "cut" if duration >= MIN_PAUSE_US and ratio < 0.30 else ("manual_review" if duration >= HARD_PAUSE_US else "keep")
        if pause_type == "within_word_region":
            recommended = "manual_review"
        pause_id = f"pa_{len(pauses) + 1:03d}"
        pauses.append(
            {
                "pause_id": pause_id,
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
    type_counts = {key: 0 for key in ["inter_clip", "intra_clip", "intra_subtitle_group", "within_word_region", "unknown"]}
    for row in pauses:
        key = str(row.get("pause_type") or "unknown")
        type_counts[key] = type_counts.get(key, 0) + 1
    hard = [row for row in pauses if int(row["duration_us"]) >= HARD_PAUSE_US]
    cut_rows = [row for row in pauses if row.get("recommended_action") == "cut"]
    report = {
        "virtual_final_audio_generated": False,
        "virtual_final_audio_scanned": True,
        "audio_mode": "in_memory_virtual_timeline",
        "audio_path": str(cutter.video_path),
        "raw_path": str(cutter.raw_path),
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
        "# Post-write Audio Pause Review",
        "",
        f"- virtual_final_audio_scanned: true",
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


def compact_source_intervals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        clip_id = str(row.get("clip_id") or "")
        start = int(row.get("source_start_us") or 0)
        end = int(row.get("source_end_us") or start)
        if not clip_id or end <= start:
            continue
        if out and str(out[-1].get("clip_id")) == clip_id and int(out[-1]["source_end_us"]) >= start - FRAME_US:
            out[-1]["source_end_us"] = max(int(out[-1]["source_end_us"]), end)
        else:
            out.append({"clip_id": clip_id, "source_start_us": start, "source_end_us": end})
    return out


def pause_stats_after_cut(plan: list[dict[str, Any]], pauses: list[dict[str, Any]]) -> dict[str, Any]:
    before = [int(row["duration_us"]) for row in pauses if int(row.get("duration_us") or 0) >= MIN_PAUSE_US]
    after = []
    cut_by_pause = {str(row.get("target_pause_id")): row for row in plan}
    for pause in pauses:
        duration = int(pause.get("duration_us") or 0)
        if duration < MIN_PAUSE_US:
            continue
        cut = cut_by_pause.get(str(pause.get("pause_id")))
        after.append(int(cut.get("kept_pause_us") or duration) if cut else duration)
    return {
        "average_pause_before_ms": round(statistics.mean(before) / 1000, 3) if before else 0,
        "average_pause_after_ms": round(statistics.mean(after) / 1000, 3) if after else 0,
    }
