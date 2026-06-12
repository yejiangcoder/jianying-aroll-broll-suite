from __future__ import annotations

import copy
import hashlib
import uuid
from pathlib import Path
from typing import Any

from .models import ExecPlanItem, MICROSECONDS


TRACK_NAME = "AI_BROLL"


def new_id() -> str:
    return str(uuid.uuid4()).upper()


def image_dimensions(path: Path) -> tuple[int, int]:
    if path.suffix.lower() == ".png":
        with path.open("rb") as handle:
            header = handle.read(24)
        if header[:8] == b"\x89PNG\r\n\x1a\n":
            return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")
    return 1920, 1080


def ensure_material_lists(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    materials = data.setdefault("materials", {})
    for key in ["videos", "speeds", "canvases", "placeholder_infos", "material_animations", "sound_channel_mappings"]:
        materials.setdefault(key, [])
    return materials


def photo_material(path: Path, material_id: str, duration_us: int) -> dict[str, Any]:
    width, height = image_dimensions(path)
    material_hash = hashlib.md5(str(path).encode("utf-8")).hexdigest()
    return {
        "id": material_id,
        "type": "photo",
        "duration": max(duration_us, 1),
        "path": str(path).replace("\\", "/"),
        "material_id": material_hash,
        "material_name": path.name,
        "width": width,
        "height": height,
        "has_audio": False,
        "crop": {},
        "stable": {"time_range": {}},
    }


def speed_material(speed_id: str) -> dict[str, Any]:
    return {"id": speed_id, "type": "speed", "speed": 1.0, "mode": 0}


def photo_segment(row: ExecPlanItem, material_id: str, speed_id: str, track_render_index: int) -> dict[str, Any]:
    start_us = int(round(row.start_sec * MICROSECONDS))
    duration_us = int(round(row.duration_sec * MICROSECONDS))
    return {
        "id": new_id(),
        "material_id": material_id,
        "extra_material_refs": [speed_id],
        "source_timerange": {"start": 0, "duration": duration_us},
        "target_timerange": {"start": start_us, "duration": duration_us},
        "render_timerange": {},
        "clip": {"scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": 0.0}, "flip": {}},
        "uniform_scale": {},
        "render_index": 12000,
        "track_render_index": track_render_index,
        "source": "segmentsourcenormal",
    }


def remove_existing_track(data: dict[str, Any], track_name: str = TRACK_NAME) -> None:
    tracks = data.get("tracks", []) or []
    removed_material_ids = {
        segment.get("material_id")
        for track in tracks
        if track.get("name") == track_name
        for segment in track.get("segments", []) or []
        if segment.get("material_id")
    }
    data["tracks"] = [track for track in tracks if track.get("name") != track_name]
    if removed_material_ids:
        videos = data.get("materials", {}).get("videos", []) or []
        data["materials"]["videos"] = [item for item in videos if item.get("id") not in removed_material_ids]


def append_ai_broll_track(
    draft_content: dict[str, Any],
    exec_plan: list[ExecPlanItem],
    track_name: str = TRACK_NAME,
    track_render_index: int = 12000,
    replace_existing: bool = True,
) -> dict[str, Any]:
    data = copy.deepcopy(draft_content)
    materials = ensure_material_lists(data)
    if replace_existing:
        remove_existing_track(data, track_name)

    track = {"id": new_id(), "type": "video", "flag": 2, "segments": [], "name": track_name}
    for row in sorted(exec_plan, key=lambda item: (item.start_sec, item.image_id)):
        material_id = new_id()
        speed_id = new_id()
        duration_us = int(round(row.duration_sec * MICROSECONDS))
        materials["videos"].append(photo_material(row.image_path, material_id, duration_us))
        materials["speeds"].append(speed_material(speed_id))
        track["segments"].append(photo_segment(row, material_id, speed_id, track_render_index))
    data.setdefault("tracks", []).append(track)
    return data

