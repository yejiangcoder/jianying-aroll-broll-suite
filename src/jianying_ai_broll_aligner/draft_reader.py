from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .models import SubtitleRow


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def decode_draft_with_command(input_path: Path, output_path: Path, command: list[str]) -> Path:
    """Run an external draft decoder.

    The package does not bundle proprietary binaries. Users may provide their
    own compatible local decoder command, for example:
    `decoder --decode input.json output.json`.
    """

    output_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [part.format(input=str(input_path), output=str(output_path)) for part in command],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stdout)
    return output_path


def subtitle_rows_from_draft_content(data: dict[str, Any]) -> list[SubtitleRow]:
    text_materials = {item.get("id"): item for item in data.get("materials", {}).get("texts", [])}
    text_tracks = [track for track in data.get("tracks", []) if track.get("type") == "text"]
    if not text_tracks:
        return []
    track = max(text_tracks, key=lambda row: len(row.get("segments", []) or []))
    rows: list[SubtitleRow] = []
    segments = sorted(
        track.get("segments", []) or [],
        key=lambda segment: int((segment.get("target_timerange") or {}).get("start") or 0),
    )
    for segment in segments:
        material = text_materials.get(segment.get("material_id"), {})
        text = material.get("recognize_text") or ""
        if not text:
            content = material.get("content")
            if isinstance(content, str):
                try:
                    text = json.loads(content).get("text") or ""
                except Exception:
                    text = ""
        timerange = segment.get("target_timerange") or {}
        start = int(timerange.get("start") or 0)
        duration = int(timerange.get("duration") or 0)
        if text and duration:
            rows.append(
                SubtitleRow(
                    index=len(rows) + 1,
                    text=text,
                    start_us=start,
                    end_us=start + duration,
                    source="draft_content",
                )
            )
    return rows

