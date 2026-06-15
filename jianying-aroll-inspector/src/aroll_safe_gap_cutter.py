from __future__ import annotations

import math
import os
import shutil
import statistics
import subprocess
from array import array
from pathlib import Path
from typing import Any


CANDIDATE_GAP_THRESHOLD_US = 250_000
MIN_CONFIRMED_SILENCE_US = 160_000
TARGET_KEPT_GAP_US = 40_000
SPEECH_LEAD_PAD_US = 90_000
SPEECH_TAIL_PAD_US = 120_000
REPEAT_BOUNDARY_LEAD_PAD_US = 30_000
REPEAT_BOUNDARY_TAIL_PAD_US = 60_000
SAMPLE_RATE = 16_000
FRAME_US = 20_000


def find_media_path(path: str) -> Path:
    candidate = Path(path.replace("/", "\\"))
    if candidate.exists():
        return candidate
    name = candidate.name
    configured_roots = [
        Path(item)
        for item in os.environ.get("AROLL_MEDIA_SEARCH_ROOTS", "").split(";")
        if item.strip()
    ]
    default_roots = [Path(r"D:\wink\after"), Path(r"D:\video")]
    for root in [*configured_roots, *default_roots]:
        if not root.exists():
            continue
        matches = [match for match in root.rglob(name) if match.exists()]
        matches.sort(key=lambda item: str(item).lower())
        if matches:
            return matches[0]
    raise FileNotFoundError(path)


def ffmpeg_path() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    fallback = Path(r"D:\ffmpeg\ffmpeg-8.0.1-essentials_build\bin\ffmpeg.exe")
    if fallback.exists():
        return str(fallback)
    raise FileNotFoundError("ffmpeg")


def extract_pcm(video_path: Path, run_dir: Path) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    raw_path = run_dir / f"{video_path.stem}.s16le"
    if raw_path.exists() and raw_path.stat().st_size > 0:
        return raw_path
    cmd = [
        ffmpeg_path(),
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "s16le",
        str(raw_path),
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return raw_path


def compute_silences(raw_path: Path) -> dict[str, Any]:
    samples = array("h")
    samples.frombytes(raw_path.read_bytes())
    frame_size = max(1, int(SAMPLE_RATE * FRAME_US / 1_000_000))
    db_rows: list[float] = []
    for start in range(0, len(samples), frame_size):
        frame = samples[start : start + frame_size]
        if not frame:
            continue
        rms = math.sqrt(sum(int(x) * int(x) for x in frame) / len(frame))
        db = 20 * math.log10(max(1.0, rms) / 32768.0)
        db_rows.append(db)
    if not db_rows:
        return {"threshold_db": -60.0, "silences": []}
    ordered = sorted(db_rows)
    p20 = ordered[int(len(ordered) * 0.2)]
    threshold = min(-28.0, p20 + 6.0)
    silences: list[dict[str, int]] = []
    current_start: int | None = None
    for idx, db in enumerate(db_rows):
        frame_start = idx * FRAME_US
        frame_end = frame_start + FRAME_US
        silent = db <= threshold
        if silent and current_start is None:
            current_start = frame_start
        if not silent and current_start is not None:
            if frame_start - current_start >= 100_000:
                silences.append({"start_us": current_start, "end_us": frame_start, "duration_us": frame_start - current_start})
            current_start = None
        if idx == len(db_rows) - 1 and current_start is not None:
            if frame_end - current_start >= 100_000:
                silences.append({"start_us": current_start, "end_us": frame_end, "duration_us": frame_end - current_start})
    return {
        "threshold_db": threshold,
        "db_p20": p20,
        "db_p50": statistics.median(db_rows),
        "silences": silences,
    }


class SafeGapCutter:
    def __init__(self, video_path: str, run_dir: Path) -> None:
        self.video_path = find_media_path(video_path)
        self.raw_path = extract_pcm(self.video_path, run_dir)
        self.report = compute_silences(self.raw_path)
        self.silences = self.report["silences"]

    def confirmed_silence_us(self, start_us: int, end_us: int) -> int:
        if end_us <= start_us:
            return 0
        total = 0
        for row in self.silences:
            overlap_start = max(start_us, int(row["start_us"]))
            overlap_end = min(end_us, int(row["end_us"]))
            if overlap_end > overlap_start:
                total += overlap_end - overlap_start
        return total

    def confirm(self, start_us: int, end_us: int, min_silence_us: int = MIN_CONFIRMED_SILENCE_US) -> tuple[bool, int]:
        total = self.confirmed_silence_us(start_us, end_us)
        return total >= min_silence_us, total


def build_safe_gap_plan(
    cutter: SafeGapCutter,
    boundaries: list[dict[str, Any]],
    phase4b_original_gap_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for boundary in boundaries:
        gap_start = int(boundary["silence_check_start_us"])
        gap_end = int(boundary["silence_check_end_us"])
        gap_duration = max(0, gap_end - gap_start)
        if gap_duration < CANDIDATE_GAP_THRESHOLD_US and boundary.get("boundary_type") != "repeat_drop_boundary":
            rejected.append(boundary | {"accepted": False, "reason": "gap below candidate threshold", "confirmed_silence_us": 0})
            continue
        ok, confirmed = cutter.confirm(gap_start, gap_end)
        row = boundary | {
            "gap_duration_us": gap_duration,
            "confirmed_silence_us": confirmed,
            "accepted": ok,
            "target_kept_gap_us": TARGET_KEPT_GAP_US,
        }
        if ok:
            accepted.append(row)
        else:
            rejected.append(row | {"reason": "VAD/audio did not confirm enough silence"})
    summary = {
        "phase4b_original_gap_cut_count": phase4b_original_gap_count,
        "safe_gap_candidate_count": len(boundaries),
        "vad_confirmed_count": len(accepted),
        "rejected_high_risk_count": len(rejected),
        "estimated_removed_gap_us": sum(max(0, int(row.get("cut_end_us", 0)) - int(row.get("cut_start_us", 0))) for row in accepted),
        "audio_path": str(cutter.video_path),
        "raw_path": str(cutter.raw_path),
        "threshold_db": cutter.report.get("threshold_db"),
    }
    return accepted, rejected, summary
