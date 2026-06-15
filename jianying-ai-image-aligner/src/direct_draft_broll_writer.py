from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from runtime_paths import get_runs_dir


SEC = 1_000_000
DEFAULT_JY_DRAFTC = Path(
    r"D:\video tools\jianying-ai-image-aligner\vendor\jy-draftc-bin\jy-draftc-amd64-windows\jy-draftc.exe"
)
DEFAULT_RUNTIME = get_runs_dir()
PHOTO_DURATION_US = 1_300_000
AI_TRACK_NAME = "AI_BROLL"
MIN_MATCH_CONFIDENCE = 0.45


def guid() -> str:
    return str(uuid.uuid4()).upper()


def normalize_image_id(value: str) -> str:
    match = re.search(r"\d+", str(value or ""))
    if not match:
        return ""
    digits = match.group(0)
    return digits.zfill(2) if len(digits) < 2 else digits


def image_id_sort_key(image_id: str) -> tuple[int, str]:
    return (int(normalize_image_id(image_id) or 0), normalize_image_id(image_id))


def image_id_from_filename(path: Path) -> str:
    match = re.search(r"(?:^|_)AI_(\d+)(?:_|$)", path.stem)
    return normalize_image_id(match.group(1)) if match else ""


def parse_id_list(value: str) -> set[str]:
    ids = set()
    for part in re.split(r"[,，\s]+", value or ""):
        image_id = normalize_image_id(part)
        if image_id:
            ids.add(image_id)
    return ids


def read_json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), "utf-8")


def clean_text(text: str) -> str:
    return (text or "").strip().strip("“”\"' ")


def norm_text(text: str) -> str:
    text = (text or "").lower()
    table = str.maketrans(
        "，。！？；：、“”‘’（）【】《》—…·　,.!?;:\"'()[]<>-",
        " " * len("，。！？；：、“”‘’（）【】《》—…·　,.!?;:\"'()[]<>-"),
    )
    text = text.translate(table)
    text = re.sub(r"\s+", "", text)
    text = text.replace("国南", "国男").replace("0", "零")
    return text


def text_score(target: str, candidate: str) -> float:
    a = norm_text(target)
    b = norm_text(candidate)
    return text_score_norm(a, b)


def text_score_norm(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b:
        return min(0.99, 0.88 + len(a) / max(1, len(b)) * 0.11)
    if b in a and len(b) >= 4:
        return min(0.90, 0.65 + len(b) / max(1, len(a)) * 0.25)
    seq = difflib.SequenceMatcher(None, a, b).ratio()
    overlap = len(set(a) & set(b)) / max(1, len(set(a) | set(b)))
    dice = dice_score(a, b)
    return max(seq * 0.55 + overlap * 0.25 + dice * 0.20, overlap * 0.78, dice * 0.82)


def bigrams(value: str) -> set[str]:
    if not value:
        return set()
    if len(value) == 1:
        return {value}
    return {value[i : i + 2] for i in range(len(value) - 1)}


def dice_score(a: str, b: str) -> float:
    left = bigrams(a)
    right = bigrams(b)
    if not left or not right:
        return 0.0
    return 2 * len(left & right) / max(1, len(left) + len(right))


def match_method_for_norm(target_norm: str, candidate_norm: str) -> str:
    if not target_norm or not candidate_norm:
        return "empty"
    if target_norm == candidate_norm:
        return "exact"
    if target_norm in candidate_norm:
        return "target_contains"
    if candidate_norm in target_norm and len(candidate_norm) >= 4:
        return "candidate_contains"
    return "normalized_fuzzy"


def match_method_rank(method: str) -> int:
    return {
        "exact": 4,
        "target_contains": 3,
        "candidate_contains": 2,
        "normalized_fuzzy": 1,
        "empty": 0,
    }.get(method, 0)


def normalized_image_files(image_dir: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in sorted(image_dir.glob("*.png")):
        image_id = image_id_from_filename(path)
        if image_id and image_id not in files:
            files[image_id] = path
    return dict(sorted(files.items(), key=lambda item: image_id_sort_key(item[0])))


def find_image(image_dir: Path, image_id: str, files: dict[str, Path] | None = None) -> Path:
    image_id = normalize_image_id(image_id)
    files = files or normalized_image_files(image_dir)
    if image_id not in files:
        raise FileNotFoundError(f"缺少 AI 图片 {image_id}: {image_dir}")
    return files[image_id]


def broll_table_ai_ids(broll_path: Path) -> list[str]:
    ids = []
    for line in broll_path.read_text("utf-8").splitlines():
        if not line.startswith("|") or "AI静态图" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and cells[0] not in {"序号", "---"}:
            image_id = normalize_image_id(cells[0])
            if image_id:
                ids.append(image_id)
    return sorted(set(ids), key=image_id_sort_key)


def broll_static_list_ids(broll_path: Path) -> list[str]:
    text = broll_path.read_text("utf-8")
    ids = []
    for match in re.finditer(r"(?ms)^【(\d+)】\s*(.*?)(?=^【\d+】|^#\s*\d+\.|\Z)", text):
        body = match.group(2)
        if "画面名称：" in body and "台词落点：" in body:
            ids.append(normalize_image_id(match.group(1)))
    return sorted(set(ids), key=image_id_sort_key)


def parse_broll_items(broll_path: Path, image_dir: Path) -> list[dict[str, Any]]:
    text = broll_path.read_text("utf-8")
    image_files = normalized_image_files(image_dir)
    by_id: dict[str, dict[str, Any]] = {}

    def add_item(image_id: str, target_text: str, image_name: str, source: str, prompt: str = "") -> None:
        target_text = clean_text(target_text)
        if not image_id or not target_text:
            return
        try:
            path = find_image(image_dir, image_id, image_files)
        except FileNotFoundError:
            return
        old = by_id.get(image_id)
        if old and old.get("source") == "ai_static_list":
            return
        by_id[image_id] = {
            "image_id": image_id,
            "image_path": path,
            "image_name": clean_text(image_name) or path.stem,
            "target_text": target_text,
            "source": source,
            "prompt": prompt,
        }

    for line in text.splitlines():
        if not line.startswith("|") or "AI静态图" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 6 or cells[0] in {"序号", "---"}:
            continue
        image_id = normalize_image_id(cells[0])
        if not image_id:
            continue
        # Current and historical B-roll tables may contain either:
        # 序号/优先级/台词落点/B-roll类型/画面设计/音效
        # or 序号/优先级/对齐台词序号/对齐台词起句/台词落点/B-roll类型/...
        if len(cells) >= 8 and cells[5] == "AI静态图":
            target_text = cells[3] or cells[4]
            prompt = cells[6]
        else:
            target_text = cells[2]
            prompt = cells[4] if len(cells) > 4 else ""
        add_item(image_id, target_text, "", "broll_table", prompt)

    for match in re.finditer(r"(?ms)^【(\d+)】\s*(.*?)(?=^【\d+】|^#\s*\d+\.|\Z)", text):
        image_id = normalize_image_id(match.group(1))
        body = match.group(2)
        if "画面名称：" not in body:
            continue
        quote = re.search(r"^台词落点：(.+)$", body, flags=re.MULTILINE)
        align_quote = re.search(r"^对齐台词起句(?:（可选）)?：(.+)$", body, flags=re.MULTILINE)
        name = re.search(r"^画面名称：(.+)$", body, flags=re.MULTILINE)
        if not quote:
            continue
        prompt = ""
        prompt_match = re.search(r"^画面方向：(.+)$", body, flags=re.MULTILINE)
        if prompt_match:
            prompt = prompt_match.group(1)
        add_item(
            image_id,
            align_quote.group(1) if align_quote else quote.group(1),
            clean_text(name.group(1)) if name else "",
            "ai_static_list",
            prompt,
        )

    items = list(by_id.values())
    items.sort(key=lambda row: image_id_sort_key(row["image_id"]))
    return items


def active_timeline_id(draft_dir: Path) -> str:
    layout = read_json(draft_dir / "timeline_layout.json")
    return layout["activeTimeline"]


def resolve_timeline_id(draft_dir: Path, timeline_name: str = "") -> tuple[str, str]:
    layout = read_json(draft_dir / "timeline_layout.json")
    expected = clean_text(timeline_name)
    if not expected:
        return layout["activeTimeline"], "activeTimeline"
    aliases = {expected}
    if re.search(r"\d+$", expected):
        prefix = re.sub(r"\d+$", "", expected)
        number = int(re.search(r"\d+$", expected).group(0))
        aliases.add(f"{prefix}{number:02d}")
        aliases.add(f"{prefix}{number}")
    for dock in layout.get("dockItems", []):
        for timeline_id, name in zip(dock.get("timelineIds", []), dock.get("timelineNames", [])):
            if clean_text(name) in aliases:
                return timeline_id, clean_text(name)
    available = []
    for dock in layout.get("dockItems", []):
        available.extend(clean_text(name) for name in dock.get("timelineNames", []))
    raise RuntimeError(f"未找到指定草稿范围：{timeline_name}；可用范围：{available}")


def decrypt(jy_draftc: Path, encrypted: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(jy_draftc), "-d", str(encrypted), str(output)],
        cwd=str(jy_draftc.parent),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout)


def encrypt(jy_draftc: Path, plain: Path, encrypted: Path) -> None:
    result = subprocess.run(
        [str(jy_draftc), "-e", str(plain), str(encrypted)],
        cwd=str(jy_draftc.parent),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout)


def assert_timeline_content_id(data: dict[str, Any], expected_timeline_id: str, source: Path) -> None:
    actual = str(data.get("id") or "")
    if actual != expected_timeline_id:
        raise RuntimeError(
            "草稿时间线 ID 不一致，停止写入："
            f"source={source}, expected={expected_timeline_id}, actual={actual}"
        )


def project_timeline_ids(draft_dir: Path) -> set[str]:
    project_path = draft_dir / "Timelines" / "project.json"
    if not project_path.exists():
        return set()
    data = read_json(project_path)
    return {str(row.get("id") or "") for row in data.get("timelines", []) if row.get("id")}


def layout_timeline_ids(draft_dir: Path) -> list[str]:
    layout_path = draft_dir / "timeline_layout.json"
    if not layout_path.exists():
        return []
    data = read_json(layout_path)
    ids: list[str] = []
    for dock in data.get("dockItems", []):
        ids.extend(str(timeline_id) for timeline_id in dock.get("timelineIds", []) if timeline_id)
    return ids


def assert_layout_has_no_duplicate_timeline_ids(draft_dir: Path) -> None:
    ids = layout_timeline_ids(draft_dir)
    duplicates = sorted({timeline_id for timeline_id in ids if ids.count(timeline_id) > 1})
    if duplicates:
        raise RuntimeError(f"timeline_layout.json 里存在重复时间线窗口，停止写入：{duplicates}")


def assert_all_project_timeline_files_match_folder_ids(
    draft_dir: Path,
    jy_draftc: Path,
    out_dir: Path,
) -> None:
    project_ids = project_timeline_ids(draft_dir)
    if not project_ids:
        raise RuntimeError("Timelines/project.json 没有可用时间线 ID，停止写入")
    timelines_dir = draft_dir / "Timelines"
    for timeline_id in sorted(project_ids):
        content_path = timelines_dir / timeline_id / "draft_content.json"
        if not content_path.exists():
            raise RuntimeError(f"项目索引中的时间线缺少 draft_content.json：{timeline_id}")
        plain = out_dir / f"audit_{timeline_id}.dec.json"
        decrypt(jy_draftc, content_path, plain)
        data = read_json(plain)
        assert_timeline_content_id(data, timeline_id, content_path)


def root_mirrors_timeline_id(draft_dir: Path, jy_draftc: Path, out_dir: Path, timeline_id: str) -> bool:
    root_path = draft_dir / "draft_content.json"
    if not root_path.exists():
        return False
    plain = out_dir / "audit_root_before.dec.json"
    decrypt(jy_draftc, root_path, plain)
    data = read_json(plain)
    return str(data.get("id") or "") == timeline_id


def subtitle_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    text_materials = {m["id"]: m for m in data["materials"].get("texts", [])}
    text_tracks = [t for t in data.get("tracks", []) if t.get("type") == "text"]
    if not text_tracks:
        raise RuntimeError("草稿里没有 text track")
    track = max(text_tracks, key=lambda t: len(t.get("segments", [])))
    rows = []
    for index, segment in enumerate(
        sorted(track.get("segments", []), key=lambda s: int((s.get("target_timerange") or {}).get("start") or 0)),
        start=1,
    ):
        material = text_materials.get(segment.get("material_id"), {})
        text = material.get("recognize_text") or ""
        if not text:
            try:
                text = json.loads(material.get("content") or "{}").get("text") or ""
            except Exception:
                text = ""
        timerange = segment.get("target_timerange") or {}
        rows.append(
            {
                "subtitle_index": index,
                "subtitle_text": text,
                "start_us": int(timerange.get("start") or 0),
                "duration_us": int(timerange.get("duration") or 0),
            }
        )
    return rows


def build_subtitle_windows(rows: list[dict[str, Any]], max_window: int = 7) -> list[dict[str, Any]]:
    subtitle_windows: list[dict[str, Any]] = []
    for i in range(len(rows)):
        combined = ""
        for width in range(1, max_window + 1):
            if i + width > len(rows):
                break
            combined += rows[i + width - 1]["subtitle_text"]
            normalized = norm_text(combined)
            if not normalized:
                continue
            subtitle_windows.append(
                {
                    "row": rows[i],
                    "rows_span": rows[i : i + width],
                    "norm_pieces": [norm_text(row["subtitle_text"]) for row in rows[i : i + width]],
                    "start_index": i,
                    "end_index": i + width - 1,
                    "width": width,
                    "text": combined,
                    "norm_text": normalized,
                }
            )
    return subtitle_windows


def anchor_subtitle_window(window: dict[str, Any], target_norm: str, method: str) -> dict[str, Any]:
    if method not in {"exact", "target_contains"} or not target_norm:
        return window
    position = str(window["norm_text"]).find(target_norm)
    if position < 0:
        return window
    cursor = 0
    for offset, piece in enumerate(window.get("norm_pieces") or []):
        next_cursor = cursor + len(piece)
        if position < next_cursor or (piece and position == cursor):
            anchored = dict(window)
            anchored["row"] = window["rows_span"][offset]
            anchored["start_index"] = int(window["start_index"]) + offset
            anchored["anchor_offset"] = offset
            anchored["width"] = int(window["end_index"]) - int(anchored["start_index"]) + 1
            return anchored
        cursor = next_cursor
    return window


def match_item_to_subtitle_window(
    item: dict[str, Any],
    subtitle_windows: list[dict[str, Any]],
    min_start_index: int,
) -> dict[str, Any]:
    target_norm = norm_text(item["target_text"])
    for window in subtitle_windows:
        method = match_method_for_norm(target_norm, window["norm_text"])
        score = text_score_norm(target_norm, window["norm_text"])
        candidate = anchor_subtitle_window(window, target_norm, method)
        if int(candidate["start_index"]) < min_start_index:
            continue
        if method in {"exact", "target_contains"} and score >= 0.86:
            return {
                **candidate,
                "score": score,
                "method": method,
            }

    best: dict[str, Any] | None = None
    best_key: tuple[float, int, int, int] | None = None
    for window in subtitle_windows:
        method = match_method_for_norm(target_norm, window["norm_text"])
        score = text_score_norm(target_norm, window["norm_text"])
        candidate = anchor_subtitle_window(window, target_norm, method)
        if int(candidate["start_index"]) < min_start_index:
            continue
        key = (
            round(score, 6),
            match_method_rank(method),
            -int(candidate["width"]),
            -int(candidate["start_index"]),
        )
        if best_key is None or key > best_key:
            best_key = key
            best = {
                **candidate,
                "score": score,
                "method": method,
            }
    if best is None:
        raise RuntimeError(f"无法匹配图片 {item['image_id']}")
    return best


def map_items(items: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    subtitle_windows = build_subtitle_windows(rows)
    mapped = []
    min_start_index = 0
    for item in items:
        match = match_item_to_subtitle_window(item, subtitle_windows, min_start_index)
        row = match["row"]
        score = float(match["score"])
        method = f"subtitle_text_window_global:{match['method']}"
        if score >= MIN_MATCH_CONFIDENCE:
            min_start_index = max(min_start_index, int(match["start_index"]))
        mapped.append(
            {
                **item,
                "subtitle_index": row["subtitle_index"],
                "subtitle_text": row["subtitle_text"],
                "start_us": row["start_us"],
                "duration_us": PHOTO_DURATION_US,
                "match_method": method,
                "confidence": round(float(score), 4),
                "matched_window": match["text"],
                "window_size": match["width"],
                "window_start_index": int(match["start_index"]) + 1,
                "window_end_index": int(match["end_index"]) + 1,
            }
        )

    # A single Jianying track cannot contain overlapping clips. Preserve subtitle
    # starts when possible and only nudge direct collisions forward.
    last_end = -1
    for row in mapped:
        original = row["start_us"]
        participates_in_track = float(row.get("confidence", 0)) >= MIN_MATCH_CONFIDENCE
        if participates_in_track and original < last_end:
            row["start_us"] = last_end
            row["match_method"] += "+nonoverlap_nudge"
        row["end_us"] = row["start_us"] + PHOTO_DURATION_US
        row["start_sec"] = row["start_us"] / SEC
        row["duration_sec"] = PHOTO_DURATION_US / SEC
        row["nudged_us"] = row["start_us"] - original
        if participates_in_track:
            last_end = row["end_us"]
    return mapped


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as f:
        data = f.read(24)
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return 1920, 1080


def remove_existing_ai(data: dict[str, Any], image_dir: Path) -> dict[str, set[str]]:
    image_root = str(image_dir).replace("\\", "/")
    ai_material_ids = set()
    removed_names = set()
    for track in data.get("tracks", []):
        if track.get("name") == AI_TRACK_NAME:
            for segment in track.get("segments", []):
                if segment.get("material_id"):
                    ai_material_ids.add(segment.get("material_id"))
    for material in data["materials"].get("videos", []):
        path = str(material.get("path") or "").replace("\\", "/")
        if image_root in path:
            ai_material_ids.add(material.get("id"))

    if ai_material_ids:
        kept_tracks = []
        for track in data.get("tracks", []):
            if track.get("name") == AI_TRACK_NAME:
                continue
            old_segments = track.get("segments", [])
            new_segments = [seg for seg in old_segments if seg.get("material_id") not in ai_material_ids]
            if len(new_segments) != len(old_segments):
                track["segments"] = new_segments
            kept_tracks.append(track)
        data["tracks"] = kept_tracks
        for material in data["materials"].get("videos", []):
            if material.get("id") in ai_material_ids and material.get("material_name"):
                removed_names.add(str(material.get("material_name")))
        data["materials"]["videos"] = [
            material for material in data["materials"].get("videos", []) if material.get("id") not in ai_material_ids
        ]
    return {"ids": ai_material_ids, "names": removed_names}


def helper_materials(refs: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    return {
        "speeds": [{"id": refs["speed"], "type": "speed"}],
        "placeholder_infos": [{"id": refs["placeholder"], "type": "placeholder_info", "meta_type": "none"}],
        "canvases": [{"id": refs["canvas"], "type": "canvas_color"}],
        "material_animations": [{"id": refs["animation"], "type": "sticker_animation"}],
        "sound_channel_mappings": [{"id": refs["sound"], "type": ""}],
        "material_colors": [{"id": refs["color"]}],
        "vocal_separations": [{"id": refs["vocal"], "type": "vocal_separation"}],
    }


def append_ai_track(data: dict[str, Any], mapped: list[dict[str, Any]]) -> None:
    for key in [
        "videos",
        "speeds",
        "placeholder_infos",
        "canvases",
        "material_animations",
        "sound_channel_mappings",
        "material_colors",
        "vocal_separations",
    ]:
        data["materials"].setdefault(key, [])

    text_tracks = [t for t in data.get("tracks", []) if t.get("type") == "text"]
    subtitle_track = max(text_tracks, key=lambda t: len(t.get("segments", [])))
    filter_tri = [
        int(seg.get("track_render_index") or 0)
        for track in data.get("tracks", [])
        if track.get("type") == "filter"
        for seg in track.get("segments", [])
        if "track_render_index" in seg
    ]
    ai_track_render_index = max(filter_tri, default=2) + 1
    new_subtitle_tri = ai_track_render_index + 1
    for seg in subtitle_track.get("segments", []):
        if "track_render_index" in seg:
            seg["track_render_index"] = new_subtitle_tri

    ai_track = {"id": guid(), "type": "video", "flag": 2, "segments": [], "name": AI_TRACK_NAME}
    ai_render_index = 12000

    for row in mapped:
        material_id = guid()
        segment_id = guid()
        refs = {
            "speed": guid(),
            "placeholder": guid(),
            "canvas": guid(),
            "animation": guid(),
            "sound": guid(),
            "color": guid(),
            "vocal": guid(),
        }
        width, height = png_size(row["image_path"])
        data["materials"]["videos"].append(
            {
                "id": material_id,
                "type": "photo",
                "duration": 10_800_000_000,
                "path": str(row["image_path"]).replace("\\", "/"),
                "has_audio": False,
                "width": width,
                "height": height,
                "material_id": hashlib.md5(str(row["image_path"]).encode("utf-8")).hexdigest(),
                "material_name": row["image_path"].name,
                "crop": {},
                "stable": {"time_range": {}},
                "matting": {"path": ""},
                "check_flag": 62978047,
                "video_algorithm": {"path": "", "story_video_modify_video_config": {}},
                "is_unified_beauty_mode": True,
                "is_set_beauty_mode": True,
                "beauty_face_auto_preset": {},
                "video_mask_stroke": {"resource_id": "", "path": "", "type": ""},
                "video_mask_shadow": {"resource_id": "", "path": ""},
            }
        )
        for key, values in helper_materials(refs).items():
            data["materials"][key].extend(values)
        ai_track["segments"].append(
            {
                "id": segment_id,
                "source_timerange": {"duration": PHOTO_DURATION_US},
                "target_timerange": {"start": row["start_us"], "duration": PHOTO_DURATION_US},
                "render_timerange": {},
                "clip": {"scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": 0.0}, "flip": {}},
                "uniform_scale": {},
                "material_id": material_id,
                "extra_material_refs": list(refs.values()),
                "render_index": ai_render_index,
                "enable_hsl": False,
                "track_render_index": ai_track_render_index,
                "hdr_settings": {"mode": 1},
                "responsive_layout": {},
                "enable_adjust_mask": False,
                "source": "segmentsourcenormal",
            }
        )
        row["draft_material_id"] = material_id
        row["draft_segment_id"] = segment_id

    tracks = data.get("tracks", [])
    subtitle_index = tracks.index(subtitle_track)
    tracks.insert(subtitle_index, ai_track)


def update_key_value(draft_dir: Path, mapped: list[dict[str, Any]], removed_ai: dict[str, set[str]] | None = None) -> None:
    path = draft_dir / "key_value.json"
    data = read_json(path) if path.exists() else {}
    ai_names = {row["image_path"].name for row in mapped}
    removed_ids = (removed_ai or {}).get("ids", set())
    removed_names = (removed_ai or {}).get("names", set())
    data = {
        key: value
        for key, value in data.items()
        if key not in removed_ids
        and not (
            isinstance(value, dict)
            and value.get("materialName") in ai_names.union(removed_names)
        )
    }
    for rank, row in enumerate(mapped, start=1):
        material_hash = hashlib.md5(str(row["image_path"]).encode("utf-8")).hexdigest()
        base = {
            "filter_category": "",
            "filter_detail": "",
            "is_brand": 0,
            "is_from_artist_shop": 0,
            "is_vip": "0",
            "keywordSource": "",
            "materialCategory": "media",
            "materialId": material_hash,
            "materialName": row["image_path"].name,
            "materialSubcategory": "local",
            "materialSubcategoryId": "",
            "materialThirdcategory": "导入",
            "materialThirdcategoryId": "",
            "material_copyright": "",
            "material_is_purchased": "",
            "rank": str(900 + rank),
            "rec_id": "",
            "requestId": "",
            "role": "",
            "searchId": "",
            "searchKeyword": "",
            "team_id": "",
            "textTemplateVersion": "",
        }
        data[row["draft_material_id"]] = {**base, "segmentId": row["draft_material_id"]}
        data[row["draft_segment_id"]] = {**base, "segmentId": row["draft_segment_id"]}
    write_json(path, data)


def write_report(out_dir: Path, rows: list[dict[str, Any]]) -> Path:
    path = out_dir / "broll_exec_plan.csv"
    fields = [
        "image_id",
        "image_path",
        "start_sec",
        "duration_sec",
        "subtitle_index",
        "subtitle_text",
        "target_text",
        "match_method",
        "confidence",
        "matched_window",
        "window_size",
        "window_start_index",
        "window_end_index",
        "nudged_us",
        "draft_segment_id",
        "draft_material_id",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: image_id_sort_key(r["image_id"])):
            writer.writerow({field: row.get(field, "") for field in fields})
    return path


def write_confirmation_sheet(
    out_dir: Path,
    args: argparse.Namespace,
    timeline_id: str,
    timeline_name: str,
    subtitles: list[dict[str, Any]],
    items: list[dict[str, Any]],
    image_ids: list[str],
    mapped: list[dict[str, Any]],
    low_confidence: list[dict[str, Any]],
    exclude_ids: set[str],
) -> Path:
    nonempty_subtitles = [row for row in subtitles if clean_text(row.get("subtitle_text") or "")]
    can_execute = bool(nonempty_subtitles) and len(items) == len(image_ids) and len(mapped) == len(items) and not low_confidence
    path = out_dir / "preflight_confirmation.md"
    sample_rows = sorted(mapped, key=lambda row: image_id_sort_key(row["image_id"]))[:12]
    lines = [
        "# 剪映 AI B-roll 施工确认单",
        "",
        "## 输入确认",
        "",
        f"- 当前工程：`{args.draft_dir}`",
        f"- 内部草稿范围：`{timeline_name}`",
        f"- 当前时间线 ID：`{timeline_id}`",
        f"- B-ROLL 设计稿：`{args.broll}`",
        f"- AI 静态图目录：`{args.image_dir}`",
        "- 图片固定时长：`1.3s`",
        f"- 手工已铺/自动忽略图片：`{', '.join(sorted(exclude_ids, key=image_id_sort_key)) if exclude_ids else '无'}`",
        "",
        "## 当前工程字幕读取",
        "",
        f"- subtitle_rows：`{len(subtitles)}`",
        f"- subtitle_text_nonempty：`{len(nonempty_subtitles)}`",
        "- 字幕来源：当前剪映工程解密后的 text track",
        "- 正文脚本：未使用",
        "",
        "## B-ROLL 与图片读取",
        "",
        f"- B-ROLL AI 条目：`{len(items)}`",
        f"- 规范命名 AI 图片：`{len(image_ids)}`",
        f"- 解析后可施工图片：`{len(mapped)}`",
        "",
        "## 匹配结论",
        "",
        f"- 低置信匹配数量：`{len(low_confidence)}`",
        f"- 低置信图片编号：`{', '.join(row['image_id'] for row in low_confidence) if low_confidence else '无'}`",
        f"- 是否允许写入：`{'YES' if can_execute else 'NO'}`",
        "",
        "## 前 12 张抽样",
        "",
        "| 图片 | start_sec | 置信度 | 字幕序号 | 匹配字幕 | B-ROLL 台词落点 |",
        "|---|---:|---:|---:|---|---|",
    ]
    for row in sample_rows:
        lines.append(
            "| {image_id} | {start_sec:.3f} | {confidence} | {subtitle_index} | {subtitle_text} | {target_text} |".format(
                image_id=row["image_id"],
                start_sec=float(row["start_sec"]),
                confidence=row.get("confidence", ""),
                subtitle_index=row.get("subtitle_index", ""),
                subtitle_text=str(row.get("subtitle_text", "")).replace("|", "/"),
                target_text=str(row.get("target_text", "")).replace("|", "/"),
            )
        )
    path.write_text("\n".join(lines) + "\n", "utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Directly write AI B-roll photo clips into Jianying encrypted draft.")
    parser.add_argument("--draft-dir", type=Path, required=True)
    parser.add_argument("--broll", type=Path, required=True)
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--preflight-only", action="store_true", help="只生成施工确认单，不写入草稿。")
    parser.add_argument("--confirm-write", action="store_true", help="确认当前工程/B-ROLL/字幕匹配后才允许写入草稿。")
    parser.add_argument("--exclude-ids", default="", help="逗号分隔的图片编号；这些图视为手工已铺，自动施工时跳过。")
    parser.add_argument("--timeline-name", default="", help="内部草稿范围名称；通常留空，默认使用当前 prepared 草稿。")
    args = parser.parse_args()
    exclude_ids = parse_id_list(args.exclude_ids)

    for label, path in {
        "draft_dir": args.draft_dir,
        "broll": args.broll,
        "image_dir": args.image_dir,
        "jy_draftc": args.jy_draftc,
    }.items():
        if not path.exists():
            raise FileNotFoundError(f"{label} 不存在：{path}")

    run_id = time.strftime("direct_write_%Y%m%d_%H%M%S")
    out_dir = args.runtime / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    timeline_id, resolved_timeline_name = resolve_timeline_id(args.draft_dir, args.timeline_name)
    timeline_dir = args.draft_dir / "Timelines" / timeline_id
    encrypted_path = timeline_dir / "draft_content.json"
    plain_path = out_dir / "draft_content.dec.json"
    modified_plain = out_dir / "draft_content.modified.json"
    encrypted_out = out_dir / "draft_content.encrypted.json"

    print(f"draft_dir={args.draft_dir}")
    print(f"timeline_id={timeline_id}")
    print(f"draft_scope={resolved_timeline_name}")
    print(f"broll={args.broll}")
    print(f"image_dir={args.image_dir}")
    print("duration_sec=1.3")

    assert_layout_has_no_duplicate_timeline_ids(args.draft_dir)
    assert_all_project_timeline_files_match_folder_ids(args.draft_dir, args.jy_draftc, out_dir)
    write_root_mirror = root_mirrors_timeline_id(args.draft_dir, args.jy_draftc, out_dir, timeline_id)

    decrypt(args.jy_draftc, encrypted_path, plain_path)
    data = read_json(plain_path)
    assert_timeline_content_id(data, timeline_id, encrypted_path)
    table_ids = broll_table_ai_ids(args.broll)
    static_list_ids = broll_static_list_ids(args.broll)
    image_ids = [image_id for image_id in normalized_image_files(args.image_dir).keys() if image_id not in exclude_ids]
    if not image_ids:
        raise RuntimeError(f"AI 图片目录没有规范命名图片：{args.image_dir}")
    table_ids = [image_id for image_id in table_ids if image_id not in exclude_ids]
    static_list_ids = [image_id for image_id in static_list_ids if image_id not in exclude_ids]
    if table_ids and table_ids != image_ids:
        raise RuntimeError(
            "B-roll 表格 AI 编号与图片目录不一致："
            f"table={table_ids}, images={image_ids}"
        )
    if static_list_ids and static_list_ids != image_ids:
        raise RuntimeError(
            "AI 静态图清单编号与图片目录不一致："
            f"static_list={static_list_ids}, images={image_ids}"
        )
    items = [item for item in parse_broll_items(args.broll, args.image_dir) if item["image_id"] not in exclude_ids]
    if len(items) != len(image_ids):
        raise RuntimeError(f"B-roll AI 图片解析数量与图片目录不一致：items={len(items)} images={len(image_ids)}")
    subtitles = subtitle_rows(data)
    mapped = map_items(items, subtitles)
    low_confidence = [row for row in mapped if float(row.get("confidence", 0)) < MIN_MATCH_CONFIDENCE]
    confirmation = write_confirmation_sheet(
        out_dir,
        args,
        timeline_id,
        resolved_timeline_name,
        subtitles,
        items,
        image_ids,
        mapped,
        low_confidence,
        exclude_ids,
    )
    report = write_report(out_dir, mapped)
    print(f"subtitles={len(subtitles)}")
    print(f"subtitle_text_nonempty={sum(1 for row in subtitles if clean_text(row.get('subtitle_text') or ''))}")
    print(f"ai_images={len(items)}")
    print(f"excluded={','.join(sorted(exclude_ids, key=image_id_sort_key)) if exclude_ids else 'none'}")
    print(f"mapped={len(mapped)}")
    print(f"low_confidence={','.join(row['image_id'] for row in low_confidence) if low_confidence else 'none'}")
    print(f"confirmation={confirmation}")
    print(f"report={report}")
    print(f"work_dir={out_dir}")
    if args.preflight_only:
        print("PRELIGHT_ONLY_NO_DRAFT_WRITE")
        return 0
    if not args.confirm_write:
        raise RuntimeError("缺少 --confirm-write。必须先确认 preflight_confirmation.md 后才允许写入草稿。")
    if low_confidence:
        ids = ",".join(row["image_id"] for row in low_confidence)
        raise RuntimeError(f"存在低置信字幕匹配，停止写入：{ids}")

    removed_ai = remove_existing_ai(data, args.image_dir)
    append_ai_track(data, mapped)
    write_json(modified_plain, data)
    encrypt(args.jy_draftc, modified_plain, encrypted_out)

    targets = [
        timeline_dir / "draft_content.json",
        timeline_dir / "template-2.tmp",
    ]
    if write_root_mirror:
        targets.extend([args.draft_dir / "draft_content.json", args.draft_dir / "template-2.tmp"])
    else:
        print("skip_root_mirror=root draft_content id is not target timeline id")
    encrypted_text = encrypted_out.read_text("utf-8")
    for target in targets:
        target.write_text(encrypted_text, "utf-8")
        print(f"wrote={target}")
    update_key_value(args.draft_dir, mapped, removed_ai)
    assert_all_project_timeline_files_match_folder_ids(args.draft_dir, args.jy_draftc, out_dir)

    print(f"written_segments={len(mapped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
