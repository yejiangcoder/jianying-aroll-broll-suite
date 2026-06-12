from __future__ import annotations

import csv
import re
from pathlib import Path

from .match_broll_to_subtitles import match_broll_to_subtitles
from .models import BrollItem, ExecPlanItem, ImageAsset, SemanticPlanItem, SubtitleRow
from .parse_broll_design import parse_broll_design
from .parse_subtitles import parse_subtitles


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def image_id_from_name(path: Path) -> str:
    match = re.search(r"(?:^|[_-])AI[_-](\d+)(?:[_-]|$)", path.stem, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"(?:^|[_-])(\d{1,3})(?:[_-]|$)", path.stem)
    return match.group(1).zfill(2) if match else ""


def scan_image_assets(image_dir: Path) -> dict[str, ImageAsset]:
    assets: dict[str, ImageAsset] = {}
    for path in sorted(image_dir.iterdir() if image_dir.exists() else []):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        image_id = image_id_from_name(path)
        if image_id and image_id not in assets:
            assets[image_id] = ImageAsset(image_id=image_id, path=path)
    return assets


def build_semantic_plan(
    broll_items: list[BrollItem],
    assets: dict[str, ImageAsset],
    duration_sec: float,
) -> list[SemanticPlanItem]:
    rows: list[SemanticPlanItem] = []
    for item in broll_items:
        if item.image_id not in assets:
            raise FileNotFoundError(f"Missing image asset for ID {item.image_id}")
        asset = assets[item.image_id]
        rows.append(
            SemanticPlanItem(
                image_id=item.image_id,
                image_path=asset.path,
                image_title=item.image_title or asset.path.stem,
                target_quote=item.target_quote,
                visual_direction=item.visual_direction,
                duration_sec=duration_sec,
            )
        )
    return rows


def build_plans(
    broll_path: Path,
    subtitle_path: Path,
    image_dir: Path,
    duration_sec: float = 1.3,
    min_confidence: float = 0.50,
) -> tuple[list[SemanticPlanItem], list[ExecPlanItem], list[SubtitleRow]]:
    items = parse_broll_design(broll_path)
    assets = scan_image_assets(image_dir)
    subtitles = parse_subtitles(subtitle_path)
    semantic = build_semantic_plan(items, assets, duration_sec)
    exec_plan = match_broll_to_subtitles(items, assets, subtitles, duration_sec, min_confidence)
    return semantic, exec_plan, subtitles


def write_semantic_plan_csv(path: Path, rows: list[SemanticPlanItem]) -> None:
    fields = ["image_id", "image_path", "image_title", "target_quote", "visual_direction", "duration_sec"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "image_id": row.image_id,
                    "image_path": str(row.image_path),
                    "image_title": row.image_title,
                    "target_quote": row.target_quote,
                    "visual_direction": row.visual_direction,
                    "duration_sec": f"{row.duration_sec:.3f}",
                }
            )


def write_exec_plan_csv(path: Path, rows: list[ExecPlanItem]) -> None:
    fields = [
        "image_id",
        "image_path",
        "subtitle_index",
        "subtitle_text",
        "start_sec",
        "duration_sec",
        "target_quote",
        "match_method",
        "confidence",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "image_id": row.image_id,
                    "image_path": str(row.image_path),
                    "subtitle_index": row.subtitle_index,
                    "subtitle_text": row.subtitle_text,
                    "start_sec": f"{row.start_sec:.3f}",
                    "duration_sec": f"{row.duration_sec:.3f}",
                    "target_quote": row.target_quote,
                    "match_method": row.match_method,
                    "confidence": f"{row.confidence:.3f}",
                }
            )

