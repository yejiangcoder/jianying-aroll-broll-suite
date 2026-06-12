from __future__ import annotations

import csv
import re
from pathlib import Path

from .models import BrollItem


def normalize_image_id(value: str | int) -> str:
    match = re.search(r"\d+", str(value or ""))
    if not match:
        return ""
    return match.group(0).zfill(2)


def clean_cell(value: str) -> str:
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1].strip()
    return value.strip(" ")


def parse_markdown_table(lines: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for raw in lines:
        line = raw.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [clean_cell(cell) for cell in line.strip("|").split("|")]
        if not cells:
            continue
        if all(set(cell.replace(" ", "")) <= {"-"} for cell in cells):
            continue
        lowered = [cell.lower().replace(" ", "_") for cell in cells]
        if "index" in lowered and ("target_quote" in lowered or "type" in lowered):
            header = lowered
            continue
        if header and len(cells) >= len(header):
            rows.append(dict(zip(header, cells)))
    return rows


def parse_block_entries(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    pattern = re.compile(r"(?ms)^【(?P<id>\d+)】\s*(?P<body>.*?)(?=^【\d+】|\Z)")
    for match in pattern.finditer(text):
        body = match.group("body")
        fields: dict[str, str] = {"index": normalize_image_id(match.group("id"))}
        for line in body.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower().replace(" ", "_")
            fields[key] = clean_cell(value)
        if fields.get("type", "").lower() in {"ai image", "ai_image", "ai"} and fields.get("target_quote"):
            rows.append(fields)
    return rows


def parse_broll_design(path: Path) -> list[BrollItem]:
    text = path.read_text(encoding="utf-8")
    source_rows = parse_markdown_table(text.splitlines()) + parse_block_entries(text)
    items: dict[str, BrollItem] = {}
    for row in source_rows:
        item_type = (row.get("type") or row.get("broll_type") or "").lower().replace(" ", "_")
        if item_type not in {"ai_image", "ai"}:
            continue
        image_id = normalize_image_id(row.get("index") or row.get("id") or row.get("image_id") or "")
        target_quote = clean_cell(row.get("target_quote") or row.get("target_sentence") or row.get("quote") or "")
        if not image_id or not target_quote:
            continue
        items[image_id] = BrollItem(
            image_id=image_id,
            target_quote=target_quote,
            visual_direction=clean_cell(row.get("visual_direction") or row.get("prompt") or ""),
            image_title=clean_cell(row.get("image_title") or row.get("title") or ""),
        )
    return [items[key] for key in sorted(items, key=lambda value: int(value))]


def write_semantic_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = ["image_id", "image_path", "image_title", "target_quote", "visual_direction", "duration_sec"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

