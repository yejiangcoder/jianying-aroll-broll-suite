from __future__ import annotations

import json
import re
from pathlib import Path

from .models import MICROSECONDS, SubtitleRow


def parse_srt_time(value: str) -> int:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", value.strip())
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {value}")
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    return ((hours * 3600 + minutes * 60 + seconds) * 1000 + millis) * 1000


def parse_srt(path: Path) -> list[SubtitleRow]:
    text = path.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\r?\n\r?\n+", text.strip())
    rows: list[SubtitleRow] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        time_line = next((line for line in lines if "-->" in line), "")
        if not time_line:
            continue
        start_text, end_text = [part.strip().split()[0] for part in time_line.split("-->", 1)]
        body = " ".join(line for line in lines if line != time_line and not line.isdigit()).strip()
        if not body:
            continue
        rows.append(
            SubtitleRow(
                index=len(rows) + 1,
                text=body,
                start_us=parse_srt_time(start_text),
                end_us=parse_srt_time(end_text),
                source=str(path),
            )
        )
    return rows


def parse_jianying_attachment(path: Path) -> list[SubtitleRow]:
    data = json.loads(path.read_text(encoding="utf-8"))
    script = data.get("script_video", data)
    raw_rows: list[tuple[int, int, str]] = []
    for part in script.get("parts", []) or []:
        part_start = int(part.get("target_start_time") or 0)
        for sentence in part.get("sentences", []) or []:
            text = (sentence.get("text") or sentence.get("origin_text") or "").strip()
            words = sentence.get("words") or []
            if not text:
                text = "".join((word.get("text") or word.get("origin_text") or "") for word in words).strip()
            starts: list[int] = []
            ends: list[int] = []
            for word in words:
                timerange = word.get("time_range") or {}
                start = int(timerange.get("start") or 0)
                duration = int(timerange.get("duration") or 0)
                if duration:
                    starts.append(part_start + start)
                    ends.append(part_start + start + duration)
            if text and starts and ends:
                raw_rows.append((min(starts), max(ends), text))
    raw_rows.sort(key=lambda row: (row[0], row[1]))
    return [
        SubtitleRow(index=index, text=text, start_us=start, end_us=end, source=str(path))
        for index, (start, end, text) in enumerate(raw_rows, start=1)
    ]


def parse_subtitles(path: Path) -> list[SubtitleRow]:
    suffix = path.suffix.lower()
    if suffix == ".srt":
        return parse_srt(path)
    if suffix == ".json":
        return parse_jianying_attachment(path)
    raise ValueError(f"Unsupported subtitle source: {path}")


def format_srt_time(us: int) -> str:
    millis = max(0, round(us / 1000))
    hours = millis // 3_600_000
    millis %= 3_600_000
    minutes = millis // 60_000
    millis %= 60_000
    seconds = millis // 1000
    millis %= 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

