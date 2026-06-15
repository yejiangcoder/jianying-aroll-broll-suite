from __future__ import annotations

import argparse
import csv
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from runtime_paths import get_runs_dir


TOOL_ROOT = Path(__file__).resolve().parents[1]
VENDOR = TOOL_ROOT / "vendor"
if VENDOR.exists():
    sys.path.insert(0, str(VENDOR))
    for extra in ["pywin32_system32", "win32", r"win32\lib", "pythonwin"]:
        extra_path = VENDOR / extra
        if extra_path.exists():
            sys.path.insert(0, str(extra_path))
            try:
                os.add_dll_directory(str(extra_path))
            except Exception:
                pass

from jianying_ai_image_ui_builder import JsonLogger, foreground_jianying, screenshot  # noqa: E402

try:
    import pyautogui  # noqa: E402
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"需要 pyautogui 才能执行 UI 施工：{exc}")

try:
    from pywinauto import Desktop  # noqa: E402
except Exception:
    Desktop = None


DEFAULT_RUNTIME = get_runs_dir()
STABLE_SOURCE_ROOT = TOOL_ROOT / "stable_ai_drag_sources"


@dataclass
class Job:
    image_id: str
    image_path: Path
    start_sec: float
    duration_sec: float
    matched_subtitle: str
    subtitle_block_index: int = 0
    sequence: int = 0
    script_unit_index: int = 0
    script_unit_count: int = 0
    script_anchor_ratio: float = -1.0
    script_unit_text: str = ""

    @property
    def path(self) -> Path:
        return self.image_path


@dataclass
class TrackLayout:
    track_y: int
    subtitle_range: tuple[int, int] | None
    filter_range: tuple[int, int] | None
    source: str


@dataclass
class ClipRect:
    left: int
    top: int
    right: int
    bottom: int
    pixels: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center_x(self) -> int:
        return (self.left + self.right) // 2

    @property
    def center_y(self) -> int:
        return (self.top + self.bottom) // 2


@dataclass
class SubtitleBlock:
    index: int
    left: int
    right: int
    top: int
    bottom: int
    pixels: int

    @property
    def width(self) -> int:
        return self.right - self.left


@dataclass
class ExistingTrackState:
    track_y: int
    last_right: int
    rect_count: int

@dataclass
class RulerCalibration:
    timeline_left: int
    px_per_sec: float
    tick_count: int
    tick_spacing_px: float


def latest_fixed_plan(runtime: Path) -> Path:
    candidates = sorted(
        [
            *runtime.glob(r"ui_plan_subtitle_units_1p3s_*\alignment_report_subtitle_blocks_1p3s.csv"),
            *runtime.glob(r"ui_plan_broll_anchors_1p3s_*\alignment_report_subtitle_blocks_1p3s.csv"),
            *runtime.glob(r"ui_plan_s16_1_subtitle_blocks_1p3s_*\alignment_report_subtitle_blocks_1p3s.csv"),
            *runtime.glob(r"ui_plan_s16_1_current_1p3s_*\alignment_report_1p3s.csv"),
            *runtime.glob(r"ui_plan_agent_1p3s_*\alignment_report_1p3s.csv"),
            *runtime.glob(r"ui_plan_1p3s_*\alignment_report_1p3s.csv"),
        ],
        key=lambda p: p.stat().st_mtime,
    )
    if not candidates:
        raise FileNotFoundError(f"没有找到 1.3 秒施工表：{runtime}\\ui_plan_broll_anchors_1p3s_*\\alignment_report_subtitle_blocks_1p3s.csv")
    return candidates[-1]


def read_jobs(plan: Path, start_id: str, only_ids: str = "", max_jobs: int = 0) -> list[Job]:
    marker = start_id.strip().zfill(2) if start_id.strip() else ""
    requested_ids = {
        part.strip().zfill(2)
        for part in re.split(r"[,，\s]+", only_ids.strip())
        if part.strip()
    }
    all_jobs: list[Job] = []
    with plan.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            image_id = (row.get("image_id") or "").strip().zfill(2)
            if requested_ids and image_id not in requested_ids:
                continue
            path = Path(row["image_path"])
            all_jobs.append(
                Job(
                    image_id=image_id,
                    image_path=path,
                    start_sec=float(row["start_sec"]),
                    duration_sec=float(row["duration_sec"]),
                    matched_subtitle=row.get("matched_subtitle", ""),
                    subtitle_block_index=int((row.get("subtitle_block_index") or "0").strip() or "0"),
                    sequence=int((row.get("sequence") or "0").strip() or "0"),
                    script_unit_index=int((row.get("script_unit_index") or "0").strip() or "0"),
                    script_unit_count=int((row.get("script_unit_count") or "0").strip() or "0"),
                    script_anchor_ratio=float((row.get("script_anchor_ratio") or "-1").strip() or "-1"),
                    script_unit_text=row.get("script_unit_text", ""),
                )
            )
    all_jobs = sorted(all_jobs, key=lambda job: (job.sequence or 999999, job.start_sec, job.image_id))
    if not marker:
        return all_jobs[:max_jobs] if max_jobs > 0 else all_jobs
    for index, job in enumerate(all_jobs):
        if job.image_id == marker:
            jobs = all_jobs[index:]
            return jobs[:max_jobs] if max_jobs > 0 else jobs
    raise ValueError(f"--start-id {marker} is not present in plan: {plan}")


def image_id_from_path(path: Path) -> str:
    match = re.search(r"_AI_(\d{2})_", path.name)
    return match.group(1) if match else ""


def build_source_grid(ai_dir: Path, cols: int, x0: int, y0: int, col_step: int, row_step: int) -> dict[str, tuple[int, int]]:
    files = sorted(
        [p for p in ai_dir.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}],
        key=lambda p: p.name.lower(),
    )
    mapping: dict[str, tuple[int, int]] = {}
    for index, path in enumerate(files):
        image_id = image_id_from_path(path)
        if not image_id:
            continue
        row = index // cols
        col = index % cols
        mapping[image_id] = (x0 + col * col_step, y0 + row * row_step)
    return mapping


def source_grid_from_explorer(ai_dir: Path, logger: JsonLogger) -> dict[str, tuple[int, int]]:
    if Desktop is None:
        logger.event("source_grid_uia", "skip", reason="pywinauto unavailable")
        return {}

    title_part = ai_dir.name
    windows = [
        win
        for win in Desktop(backend="uia").windows()
        if title_part in win.window_text() and ("资源管理器" in win.window_text() or "Explorer" in win.window_text())
    ]
    best_mapping: dict[str, tuple[int, int]] = {}
    best_title = ""
    for win in windows:
        mapping: dict[str, tuple[int, int]] = {}
        try:
            items = win.descendants(control_type="ListItem")
        except Exception:
            continue
        for item in items:
            name = item.window_text() or ""
            match = re.search(r"S16-1_AI_(\d{2})_", name)
            if not match:
                match = re.search(r"S16-1_AI_(\d{2})", name)
            if not match:
                continue
            rect = item.rectangle()
            mapping[match.group(1)] = ((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
        if len(mapping) > len(best_mapping):
            best_mapping = mapping
            best_title = win.window_text()

    logger.event("source_grid_uia", "ok" if best_mapping else "empty", title=best_title, count=len(best_mapping))
    return best_mapping


def prepare_drag_source(jobs: list[Job], log_dir: Path, logger: JsonLogger) -> Path:
    source_dir = log_dir / "ai_drag_source_36"
    source_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for job in sorted(jobs, key=lambda item: int(item.image_id or "999")):
        dst = source_dir / job.image_path.name
        if not dst.exists() or dst.stat().st_size != job.image_path.stat().st_size:
            shutil.copy2(job.image_path, dst)
        copied += 1
    logger.event("prepare_drag_source", "ok", source_dir=str(source_dir), copied=copied)
    return source_dir


def prepare_single_drag_source(job: Job, log_dir: Path, logger: JsonLogger) -> Path:
    safe_stem = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", job.image_path.stem)[:80]
    source_dir = STABLE_SOURCE_ROOT / f"{job.image_id}_{safe_stem}"
    source_dir.mkdir(parents=True, exist_ok=True)
    dst = source_dir / job.image_path.name
    if not dst.exists() or dst.stat().st_size != job.image_path.stat().st_size:
        shutil.copy2(job.image_path, dst)
    logger.event(
        "prepare_single_drag_source",
        "ok",
        image_id=job.image_id,
        source_dir=str(source_dir),
        file=str(dst),
        stable_source=True,
    )
    return source_dir


def set_clipboard_text_native(text: str) -> None:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    data = (text + "\0").encode("utf-16le")
    for _ in range(10):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("无法打开 Windows 剪贴板")

    handle = None
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise RuntimeError("GlobalAlloc failed for clipboard text")
        locked = kernel32.GlobalLock(handle)
        if not locked:
            raise RuntimeError("GlobalLock failed for clipboard text")
        ctypes.memmove(locked, data, len(data))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise RuntimeError("SetClipboardData failed for clipboard text")
        handle = None
    finally:
        user32.CloseClipboard()


def find_explorer_window(title_part: str) -> int:
    user32 = ctypes.windll.user32
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    found: list[int] = []

    def cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            title = buf.value
            if title_part in title and "文件资源管理器" in title:
                found.append(hwnd)
        return True

    user32.EnumWindows(enum_proc(cb), 0)
    return found[0] if found else 0


def arrange_explorer(ai_dir: Path, height: int, logger: JsonLogger) -> None:
    user32 = ctypes.windll.user32
    title_part = ai_dir.name
    hwnd = find_explorer_window(title_part)
    if not hwnd:
        subprocess.Popen(["explorer", str(ai_dir)])
        time.sleep(1.5)
        hwnd = find_explorer_window(title_part)
    if not hwnd:
        raise RuntimeError(f"没有找到 AI 图片资源管理器窗口：{ai_dir}")

    screen = pyautogui.size()
    user32.ShowWindow(hwnd, 9)
    time.sleep(0.1)
    user32.MoveWindow(hwnd, 0, 0, int(screen.width), height, True)
    time.sleep(0.1)
    user32.SetForegroundWindow(hwnd)
    set_clipboard_text_native(str(ai_dir))
    pyautogui.hotkey("ctrl", "l")
    time.sleep(0.08)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.08)
    pyautogui.press("enter")
    time.sleep(1.0)
    pyautogui.hotkey("ctrl", "shift", "3")
    time.sleep(0.25)
    logger.event("arrange_explorer", "ok", hwnd=f"0x{hwnd:X}", height=height)
    time.sleep(0.25)


def target_x(start_sec: float, timeline_left: int, px_per_sec: float, visible_start_sec: float) -> int:
    return int(round(timeline_left + (start_sec - visible_start_sec) * px_per_sec))


def is_subtitle_orange_pixel(r: int, g: int, b: int) -> bool:
    return r > 80 and 25 < g < 140 and 20 < b < 130 and r > g + 12 and r > b + 18 and g >= b - 15


def detect_subtitle_blocks(
    shot_path: Path,
    timeline_left: int,
    timeline_right: int,
    min_width: int = 2,
    row_threshold: int = 40,
) -> list[SubtitleBlock]:
    img = Image.open(shot_path).convert("RGB")
    y_min = int(img.height * 0.55)
    y_max = img.height - 250
    row_counts: dict[int, int] = {}
    for y in range(y_min, y_max):
        count = 0
        for x in range(max(0, timeline_left), min(timeline_right, img.width), 2):
            if is_subtitle_orange_pixel(*img.getpixel((x, y))):
                count += 1
        if count >= row_threshold:
            row_counts[y] = count
    rows = row_components(row_counts, threshold=row_threshold)
    if not rows:
        return []

    top, bottom, _score = max(rows, key=lambda item: item[2])
    hits: list[int] = []
    for x in range(max(0, timeline_left), min(timeline_right, img.width)):
        count = 0
        for y in range(top, bottom + 1):
            if is_subtitle_orange_pixel(*img.getpixel((x, y))):
                count += 1
        if count >= 5:
            hits.append(x)
    if not hits:
        return []

    components: list[tuple[int, int]] = []
    start = previous = hits[0]
    for x in hits[1:]:
        if x > previous + 1:
            components.append((start, previous))
            start = x
        previous = x
    components.append((start, previous))

    blocks: list[SubtitleBlock] = []
    for left, right in components:
        if right - left + 1 < min_width:
            continue
        pixels = 0
        for x in range(left, right + 1):
            for y in range(top, bottom + 1):
                if is_subtitle_orange_pixel(*img.getpixel((x, y))):
                    pixels += 1
        blocks.append(SubtitleBlock(len(blocks) + 1, left, right, top, bottom, pixels))
    return blocks


def write_subtitle_blocks_report(blocks: list[SubtitleBlock], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["subtitle_block_index", "left", "right", "top", "bottom", "width", "pixels"])
        for block in blocks:
            writer.writerow([block.index, block.left, block.right, block.top, block.bottom, block.width, block.pixels])


def median_int(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def assert_real_subtitle_card_boundaries(blocks: list[SubtitleBlock]) -> None:
    if len(blocks) < 40:
        return
    widths = [block.width for block in blocks]
    median_width = median_int(widths)
    narrow_count = sum(1 for width in widths if width <= 6)
    narrow_ratio = narrow_count / len(widths)
    span = max(block.right for block in blocks) - min(block.left for block in blocks) + 1
    total_width = sum(widths)
    stripe_like = median_width <= 6 and narrow_ratio >= 0.65 and total_width < span * 0.90
    if stripe_like:
        raise RuntimeError(
            "当前截图识别到的是锁轨/缩略图斜纹小条，不是真正字幕卡边界；"
            f"blocks={len(blocks)}, median_width={median_width}px, narrow_ratio={narrow_ratio:.0%}。"
            "请把时间线调整到能看清单个字幕卡边界后再施工。"
        )


def mapped_subtitle_block_index(job: Job, block_count: int) -> tuple[int, str]:
    if block_count <= 0:
        raise RuntimeError("没有识别到字幕卡，无法对齐台词")

    if job.script_unit_index > 0 and job.script_unit_count > 0:
        if block_count == job.script_unit_count:
            return min(block_count, max(1, job.script_unit_index)), "script_unit_exact"
        ratio = job.script_anchor_ratio
        if ratio < 0:
            ratio = (job.script_unit_index - 1) / max(1, job.script_unit_count - 1)
        mapped = int(round(ratio * max(0, block_count - 1))) + 1
        return min(block_count, max(1, mapped)), "script_unit_ratio"

    if job.subtitle_block_index > 0:
        if job.subtitle_block_index > block_count:
            raise RuntimeError(
                f"B-ROLL 对齐台词序号 {job.subtitle_block_index} 超过当前识别到的字幕卡数量 {block_count}，"
                "拒绝把图片挤到末尾。请先让时间线显示完整字幕卡边界。"
            )
        return max(1, job.subtitle_block_index), "broll_design_anchor"

    raise RuntimeError(f"AI {job.image_id} 计划中没有台词锚点")


def write_subtitle_mapping_preview(jobs: list[Job], blocks: list[SubtitleBlock], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "sequence",
                "image_id",
                "mapped_subtitle_block_index",
                "mapping_method",
                "block_left",
                "block_right",
                "script_unit_index",
                "script_unit_count",
                "script_anchor_ratio",
                "matched_subtitle",
                "script_unit_text",
                "image_path",
            ]
        )
        for job in jobs:
            try:
                block_index, method = mapped_subtitle_block_index(job, len(blocks))
                block = blocks[block_index - 1]
                writer.writerow(
                    [
                        job.sequence,
                        job.image_id,
                        block_index,
                        method,
                        block.left,
                        block.right,
                        job.script_unit_index,
                        job.script_unit_count,
                        f"{job.script_anchor_ratio:.8f}",
                        job.matched_subtitle,
                        job.script_unit_text,
                        str(job.image_path),
                    ]
                )
            except Exception as exc:
                writer.writerow(
                    [
                        job.sequence,
                        job.image_id,
                        "",
                        f"failed:{exc}",
                        "",
                        "",
                        job.script_unit_index,
                        job.script_unit_count,
                        f"{job.script_anchor_ratio:.8f}",
                        job.matched_subtitle,
                        job.script_unit_text,
                        str(job.image_path),
                    ]
                )


def detect_ruler_calibration(
    shot_path: Path,
    timeline_left_hint: int,
    timeline_right: int,
    ruler_y: int,
    major_sec: float,
) -> RulerCalibration:
    img = Image.open(shot_path).convert("RGB")
    # Do not scan the track header area on the far left; it has vertical UI
    # dividers that look like ruler ticks and can shift every target point.
    x_min = max(0, timeline_left_hint - 5)
    x_max = min(img.width - 1, timeline_right)
    y_min = max(0, ruler_y - 55)
    y_max = min(img.height - 1, ruler_y + 45)
    scores: list[tuple[int, int]] = []
    for x in range(x_min, x_max + 1):
        score = 0
        for y in range(y_min, y_max + 1):
            r, g, b = img.getpixel((x, y))
            if 55 <= r <= 145 and 50 <= g <= 145 and 40 <= b <= 135 and abs(r - g) < 36:
                score += 1
        if score >= 8:
            scores.append((x, score))
    if not scores:
        raise RuntimeError("没有在时间尺区域识别到刻度线，无法自动校准时间比例")

    components: list[tuple[int, int, int]] = []
    xs = [x for x, _score in scores]
    score_map = dict(scores)
    start = previous = xs[0]
    best = score_map[start]
    for x in xs[1:]:
        if x > previous + 1:
            components.append((start, previous, best))
            start = x
            best = score_map[x]
        else:
            best = max(best, score_map[x])
        previous = x
    components.append((start, previous, best))

    tick_xs = [
        (left + right) // 2
        for left, right, best in components
        if right - left <= 8 and best >= 12
    ]
    if len(tick_xs) < 2:
        raise RuntimeError(f"时间尺刻度太少，无法校准：ticks={tick_xs}")
    diffs = [b - a for a, b in zip(tick_xs, tick_xs[1:]) if 80 <= b - a <= 900]
    if not diffs:
        raise RuntimeError(f"时间尺刻度间距异常，无法校准：ticks={tick_xs}")
    diffs_sorted = sorted(diffs)
    spacing = diffs_sorted[len(diffs_sorted) // 2]
    if major_sec <= 0:
        raise RuntimeError(f"主刻度秒数非法：{major_sec}")
    return RulerCalibration(
        timeline_left=tick_xs[0],
        px_per_sec=spacing / major_sec,
        tick_count=len(tick_xs),
        tick_spacing_px=float(spacing),
    )


def row_components(counts: dict[int, int], threshold: int) -> list[tuple[int, int, int]]:
    rows = sorted(y for y, count in counts.items() if count >= threshold)
    if not rows:
        return []
    components: list[tuple[int, int, int]] = []
    start = previous = rows[0]
    best_count = counts[start]
    for y in rows[1:]:
        if y > previous + 1:
            components.append((start, previous, best_count))
            start = y
            best_count = counts[y]
        else:
            best_count = max(best_count, counts[y])
        previous = y
    components.append((start, previous, best_count))
    return components


def is_teal_clip_pixel(r: int, g: int, b: int) -> bool:
    # Jianying image/video clips use a blue-green body/title color. Keep this
    # broad because selected clips and thumbnails shift the exact color.
    return r < 95 and g > 50 and b > 40 and g > r + 18 and b > r + 8 and abs(g - b) < 125


def detect_teal_clip_rects(
    shot_path: Path,
    timeline_left: int,
    timeline_right: int,
    y_min: int | None = None,
    y_max: int | None = None,
    x_min: int | None = None,
    x_max: int | None = None,
) -> list[ClipRect]:
    img = Image.open(shot_path).convert("RGB")
    x0 = max(timeline_left, x_min if x_min is not None else timeline_left)
    x1 = min(timeline_right, x_max if x_max is not None else timeline_right, img.width - 1)
    top = y_min if y_min is not None else int(img.height * 0.53)
    bottom = y_max if y_max is not None else img.height - 100
    y0 = max(0, top)
    y1 = min(img.height - 1, bottom)

    points: set[tuple[int, int]] = set()
    step = 2
    for y in range(y0, y1 + 1, step):
        for x in range(x0, x1 + 1, step):
            r, g, b = img.getpixel((x, y))
            if is_teal_clip_pixel(r, g, b):
                points.add((x, y))

    seen: set[tuple[int, int]] = set()
    rects: list[ClipRect] = []
    for point in list(points):
        if point in seen:
            continue
        stack = [point]
        seen.add(point)
        xs: list[int] = []
        ys: list[int] = []
        while stack:
            x, y = stack.pop()
            xs.append(x)
            ys.append(y)
            for dx, dy in ((step, 0), (-step, 0), (0, step), (0, -step)):
                nxt = (x + dx, y + dy)
                if nxt in points and nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        if len(xs) < 20:
            continue
        rect = ClipRect(min(xs), min(ys), max(xs), max(ys), len(xs))
        if rect.width < 10 or rect.height < 10:
            continue
        rects.append(rect)

    return merge_clip_rects(rects)


def merge_clip_rects(rects: list[ClipRect]) -> list[ClipRect]:
    merged = rects[:]
    changed = True
    while changed:
        changed = False
        output: list[ClipRect] = []
        used = [False] * len(merged)
        for i, rect in enumerate(merged):
            if used[i]:
                continue
            current = rect
            used[i] = True
            for j in range(i + 1, len(merged)):
                other = merged[j]
                if used[j]:
                    continue
                overlap_x = min(current.right, other.right) - max(current.left, other.left)
                min_width = max(1, min(current.width, other.width))
                vertical_gap = max(other.top - current.bottom, current.top - other.bottom, 0)
                combined_height = max(current.bottom, other.bottom) - min(current.top, other.top)
                if overlap_x >= min_width * 0.55 and vertical_gap <= 42 and combined_height <= 125:
                    current = ClipRect(
                        min(current.left, other.left),
                        min(current.top, other.top),
                        max(current.right, other.right),
                        max(current.bottom, other.bottom),
                        current.pixels + other.pixels,
                    )
                    used[j] = True
                    changed = True
            output.append(current)
        merged = output
    return sorted(merged, key=lambda item: item.pixels, reverse=True)


def rects_are_similar(a: ClipRect, b: ClipRect) -> bool:
    overlap_x = min(a.right, b.right) - max(a.left, b.left)
    overlap_y = min(a.bottom, b.bottom) - max(a.top, b.top)
    if overlap_x > 0 and overlap_y > 0:
        overlap_area = overlap_x * overlap_y
        min_area = max(1, min(a.width * a.height, b.width * b.height))
        if overlap_area / min_area > 0.35:
            return True
    return abs(a.center_x - b.center_x) <= 8 and abs(a.center_y - b.center_y) <= 8


def find_added_clip_by_diff(
    before_path: Path,
    after_path: Path,
    timeline_left: int,
    timeline_right: int,
    expected_default_width: int,
) -> ClipRect | None:
    before = Image.open(before_path).convert("RGB")
    after = Image.open(after_path).convert("RGB")
    x0 = max(0, timeline_left)
    x1 = min(timeline_right, before.width - 1, after.width - 1)
    y0 = int(before.height * 0.62)
    y1 = min(before.height - 100, after.height - 100)
    step = 2
    points: set[tuple[int, int]] = set()
    for y in range(y0, y1 + 1, step):
        for x in range(x0, x1 + 1, step):
            br, bg, bb = before.getpixel((x, y))
            ar, ag, ab = after.getpixel((x, y))
            if abs(ar - br) + abs(ag - bg) + abs(ab - bb) > 90:
                points.add((x, y))

    seen: set[tuple[int, int]] = set()
    rects: list[ClipRect] = []
    for point in list(points):
        if point in seen:
            continue
        stack = [point]
        seen.add(point)
        xs: list[int] = []
        ys: list[int] = []
        while stack:
            x, y = stack.pop()
            xs.append(x)
            ys.append(y)
            for dx, dy in ((step, 0), (-step, 0), (0, step), (0, -step)):
                nxt = (x + dx, y + dy)
                if nxt in points and nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        if len(xs) < 20:
            continue
        rect = ClipRect(min(xs), min(ys), max(xs), max(ys), len(xs))
        if 8 <= rect.width <= max(240, expected_default_width + 120) and 14 <= rect.height <= 180:
            rects.append(rect)

    if not rects:
        return None
    return min(rects, key=lambda rect: abs(rect.width - expected_default_width))


def find_added_clip(
    before_path: Path,
    after_path: Path,
    timeline_left: int,
    timeline_right: int,
    expected_default_width: int,
) -> ClipRect | None:
    diff_clip = find_added_clip_by_diff(before_path, after_path, timeline_left, timeline_right, expected_default_width)
    if diff_clip is not None:
        return diff_clip

    before_rects = detect_teal_clip_rects(before_path, timeline_left, timeline_right)
    after_rects = detect_teal_clip_rects(after_path, timeline_left, timeline_right)
    candidates = [
        rect
        for rect in after_rects
        if 20 <= rect.width <= max(220, expected_default_width + 90)
        and 16 <= rect.height <= 130
        and not any(rects_are_similar(rect, old) for old in before_rects)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda rect: abs(rect.width - expected_default_width))


def find_newly_dropped_clip(
    shot_path: Path,
    layout: TrackLayout,
    timeline_left: int,
    timeline_right: int,
    expected_default_width: int,
) -> ClipRect | None:
    # Fresh image drops land in Jianying's upper overlay area, even when the
    # cursor is aimed lower. Find that real clip before trimming or moving it.
    subtitle_top = layout.subtitle_range[0] if layout.subtitle_range else None
    y_max = subtitle_top - 4 if subtitle_top else None
    rects = detect_teal_clip_rects(shot_path, timeline_left, timeline_right, y_max=y_max)
    candidates = [
        rect
        for rect in rects
        if 20 <= rect.width <= max(220, expected_default_width + 80)
        and 18 <= rect.height <= 120
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda rect: abs(rect.width - expected_default_width))


def find_clip_near(
    shot_path: Path,
    near_x: int,
    near_y: int,
    timeline_left: int,
    timeline_right: int,
    radius_x: int = 180,
    radius_y: int = 90,
) -> ClipRect | None:
    rects = detect_teal_clip_rects(
        shot_path,
        timeline_left,
        timeline_right,
        y_min=near_y - radius_y,
        y_max=near_y + radius_y,
        x_min=near_x - radius_x,
        x_max=near_x + radius_x,
    )
    candidates = [
        rect
        for rect in rects
        if rect.left <= near_x + radius_x
        and rect.right >= near_x - radius_x
        and rect.top <= near_y + radius_y
        and rect.bottom >= near_y - radius_y
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda rect: abs(rect.center_x - near_x) + abs(rect.center_y - near_y))


def detect_track_layout(shot_path: Path, timeline_left: int, timeline_right: int, fallback_y: int) -> TrackLayout:
    img = Image.open(shot_path).convert("RGB")
    y_min = int(img.height * 0.55)
    y_max = img.height - 180
    orange_counts: dict[int, int] = {}
    purple_counts: dict[int, int] = {}
    for y in range(y_min, y_max):
        orange = 0
        purple = 0
        for x in range(timeline_left, min(timeline_right, img.width), 5):
            r, g, b = img.getpixel((x, y))
            if is_subtitle_orange_pixel(r, g, b):
                orange += 1
            if 45 < r < 130 and 25 < g < 110 and 80 < b < 200 and b > r + 18:
                purple += 1
        orange_counts[y] = orange
        purple_counts[y] = purple

    orange_rows = row_components(orange_counts, threshold=40)
    purple_rows = row_components(purple_counts, threshold=60)
    if not orange_rows or not purple_rows:
        return TrackLayout(fallback_y, None, None, "fallback_no_track_detection")

    subtitle = max(orange_rows, key=lambda item: item[2])
    below = [row for row in purple_rows if row[0] > subtitle[1]]
    if not below:
        return TrackLayout(fallback_y, subtitle[:2], None, "fallback_no_filter_below_subtitle")
    filter_row = min(below, key=lambda item: item[0])

    gap_top = subtitle[1] + 1
    gap_bottom = filter_row[0] - 1
    if gap_bottom <= gap_top:
        track_y = subtitle[1] + 6
    else:
        track_y = (gap_top + gap_bottom) // 2
    return TrackLayout(track_y, subtitle[:2], filter_row[:2], "detected_subtitle_below_filter_above")


def find_clip_bounds(shot_path: Path, track_y: int, near_x: int, timeline_left: int, timeline_right: int) -> tuple[int, int] | None:
    img = Image.open(shot_path).convert("RGB")
    y0 = max(0, track_y - 40)
    y1 = min(img.height, track_y + 40)
    x0 = max(timeline_left, near_x - 60)
    x1 = min(timeline_right, near_x + 220)
    hits: list[int] = []
    for x in range(x0, x1):
        count = 0
        for y in range(y0, y1, 2):
            r, g, b = img.getpixel((x, y))
            if r < 70 and g > 65 and b > 60:
                count += 1
        if count >= 4:
            hits.append(x)
    if not hits:
        return None

    components: list[tuple[int, int]] = []
    start = previous = hits[0]
    for x in hits[1:]:
        if x > previous + 1:
            components.append((start, previous))
            start = x
        previous = x
    components.append((start, previous))

    candidates = [item for item in components if item[1] - item[0] >= 8 and item[0] <= near_x + 20 and item[1] >= near_x]
    if not candidates:
        candidates = [item for item in components if item[1] - item[0] >= 8]
    if not candidates:
        return None
    return min(candidates, key=lambda item: abs(item[0] - near_x))


def find_teal_clip_row_y(shot_path: Path, near_x: int, timeline_left: int, timeline_right: int) -> int | None:
    img = Image.open(shot_path).convert("RGB")
    x0 = max(timeline_left, near_x - 120)
    x1 = min(timeline_right, near_x + 160)
    y_min = int(img.height * 0.55)
    y_max = img.height - 120
    scores: dict[int, int] = {}
    for y in range(y_min, y_max):
        score = 0
        for x in range(x0, x1, 3):
            r, g, b = img.getpixel((x, y))
            if r < 70 and 80 < g < 190 and 80 < b < 190 and abs(g - b) < 70:
                score += 1
        if score:
            scores[y] = score
    rows = row_components(scores, threshold=8)
    if not rows:
        return None
    best = max(rows, key=lambda row: row[2])
    return (best[0] + best[1]) // 2


def trim_selected_clip_right_edge(
    log_dir: Path,
    clip: ClipRect,
    duration_sec: float,
    px_per_sec: float,
    timeline_left: int,
    timeline_right: int,
    tag: str,
    strict_duration: bool,
    duration_tolerance_px: int,
) -> ClipRect:
    expected_width = max(8, int(round(duration_sec * px_per_sec)))
    if strict_duration and clip.width <= 0:
        raise RuntimeError(f"{tag} 没有识别到可裁剪片段宽度，拒绝继续")

    target_right = int(round(clip.left + expected_width))
    if target_right >= clip.right - 2:
        if strict_duration and abs(clip.width - expected_width) > duration_tolerance_px:
            raise RuntimeError(f"{tag} 片段宽度不是 1.3 秒：actual_px={clip.width}, expected_px={expected_width}")
        return clip

    pyautogui.moveTo(clip.right - 1, clip.center_y)
    time.sleep(0.08)
    pyautogui.dragTo(target_right, clip.center_y, duration=0.35, button="left")
    time.sleep(0.35)
    after = screenshot(log_dir, f"trim_after_{tag}.png")
    measured = find_clip_near(after, clip.left + expected_width // 2, clip.center_y, timeline_left, timeline_right)
    if measured is None:
        raise RuntimeError(f"{tag} 裁剪后没量到真实片段，拒绝继续")
    actual_width = measured.width
    if strict_duration and abs(actual_width - expected_width) > duration_tolerance_px:
        raise RuntimeError(f"{tag} 仍不是 1.3 秒短片段：actual_px={actual_width}, expected_px={expected_width}")
    return measured


def verify_final_clip(
    shot_path: Path,
    expected_x: int,
    expected_y: int,
    expected_width: int,
    timeline_left: int,
    timeline_right: int,
    duration_tolerance_px: int,
    track_tolerance_px: int,
    ai_track_anchor_y: int | None,
) -> ClipRect:
    measured = find_clip_near(
        shot_path,
        expected_x + expected_width // 2,
        expected_y,
        timeline_left,
        timeline_right,
        radius_x=max(220, expected_width + 120),
        radius_y=max(120, track_tolerance_px + 80),
    )
    if measured is None:
        raise RuntimeError("最终位置没有量到 AI 图片片段")
    if abs(measured.width - expected_width) > duration_tolerance_px:
        raise RuntimeError(f"最终片段不是 1.3 秒：actual_px={measured.width}, expected_px={expected_width}")
    if ai_track_anchor_y is not None and abs(measured.center_y - ai_track_anchor_y) > track_tolerance_px:
        raise RuntimeError(f"最终片段不在同一条 AI 轨道：actual_y={measured.center_y}, expected_y={ai_track_anchor_y}")
    return measured


def verify_between_subtitle_and_filter(
    shot_path: Path,
    final_rect: ClipRect,
    timeline_left: int,
    timeline_right: int,
    fallback_y: int,
) -> TrackLayout:
    layout = detect_track_layout(shot_path, timeline_left, timeline_right, fallback_y)
    if layout.subtitle_range is None or layout.filter_range is None:
        raise RuntimeError(f"无法在最终截图里识别字幕和滤镜轨道：{layout.source}")
    subtitle_bottom = layout.subtitle_range[1]
    filter_top = layout.filter_range[0]
    if not (subtitle_bottom < final_rect.center_y < filter_top):
        raise RuntimeError(
            f"AI 图片不在字幕和滤镜之间：ai_y={final_rect.center_y}, subtitle_bottom={subtitle_bottom}, filter_top={filter_top}"
        )
    return layout


def detect_existing_ai_track(
    shot_path: Path,
    timeline_left: int,
    timeline_right: int,
    fallback_y: int,
) -> ExistingTrackState | None:
    layout = detect_track_layout(shot_path, timeline_left, timeline_right, fallback_y)
    if layout.subtitle_range is None or layout.filter_range is None:
        return None
    subtitle_bottom = layout.subtitle_range[1]
    filter_top = layout.filter_range[0]
    rects = [
        rect
        for rect in detect_teal_clip_rects(shot_path, timeline_left, timeline_right)
        if 14 <= rect.width <= 90
        and 35 <= rect.height <= 130
        and subtitle_bottom < rect.center_y < filter_top
    ]
    if not rects:
        return None

    rows: list[list[ClipRect]] = []
    for rect in sorted(rects, key=lambda item: item.center_y):
        for row in rows:
            row_y = int(round(sum(item.center_y for item in row) / len(row)))
            if abs(rect.center_y - row_y) <= 18:
                row.append(rect)
                break
        else:
            rows.append([rect])
    best = max(rows, key=lambda row: (len(row), max(item.right for item in row)))
    track_y = int(round(sum(item.center_y for item in best) / len(best)))
    return ExistingTrackState(track_y=track_y, last_right=max(item.right for item in best), rect_count=len(best))


def execute_jobs(args: argparse.Namespace, jobs: list[Job], log_dir: Path, logger: JsonLogger) -> int:
    track_y = args.track_y
    layout = TrackLayout(track_y, None, None, "manual")
    existing_track: ExistingTrackState | None = None
    subtitle_blocks: list[SubtitleBlock] = []
    if not args.dry_run or args.probe_window:
        foreground_jianying(logger)
        first_shot = screenshot(log_dir, "00_before_build.png")
        if args.target_mode == "subtitle-block":
            subtitle_blocks = detect_subtitle_blocks(
                first_shot,
                args.timeline_left,
                args.timeline_right,
                args.subtitle_min_block_width,
                args.subtitle_row_threshold,
            )
            write_subtitle_blocks_report(subtitle_blocks, log_dir / "detected_subtitle_blocks.csv")
            logger.event(
                "subtitle_blocks",
                "ok" if subtitle_blocks else "empty",
                count=len(subtitle_blocks),
                report=str(log_dir / "detected_subtitle_blocks.csv"),
            )
            if len(subtitle_blocks) < args.min_subtitle_blocks:
                raise RuntimeError(f"识别到的字幕块太少：{len(subtitle_blocks)} < {args.min_subtitle_blocks}")
            if args.reject_subtitle_hatch_artifacts:
                assert_real_subtitle_card_boundaries(subtitle_blocks)
            preview_path = log_dir / "subtitle_mapping_preview.csv"
            write_subtitle_mapping_preview(jobs, subtitle_blocks, preview_path)
            planned_unit_counts = sorted({job.script_unit_count for job in jobs if job.script_unit_count > 0})
            logger.event(
                "subtitle_mapping_preflight",
                "ok",
                detected_subtitle_blocks=len(subtitle_blocks),
                planned_script_unit_counts=planned_unit_counts,
                jobs=len(jobs),
                preview=str(preview_path),
                rule="dynamic: script unit exact when counts match, otherwise ratio-map to detected subtitle blocks",
            )
            if planned_unit_counts and args.require_subtitle_coverage > 0:
                expected_units = max(planned_unit_counts)
                coverage = len(subtitle_blocks) / expected_units if expected_units > 0 else 1.0
                logger.event(
                    "subtitle_coverage",
                    "ok" if coverage >= args.require_subtitle_coverage else "failed",
                    detected_subtitle_blocks=len(subtitle_blocks),
                    expected_script_units=expected_units,
                    coverage=round(coverage, 4),
                    required=args.require_subtitle_coverage,
                )
                if coverage < args.require_subtitle_coverage:
                    raise RuntimeError(
                        f"当前时间线没有缩到全片可见：识别字幕块 {len(subtitle_blocks)} / 计划台词单元 {expected_units}，"
                        f"覆盖率 {coverage:.1%} < {args.require_subtitle_coverage:.0%}"
                    )
        if args.auto_calibrate_ruler:
            calibration = detect_ruler_calibration(
                first_shot,
                args.timeline_left,
                args.timeline_right,
                args.ruler_y,
                args.ruler_major_sec,
            )
            args.timeline_left = calibration.timeline_left
            args.px_per_sec = calibration.px_per_sec
            logger.event(
                "ruler_calibration",
                "ok",
                timeline_left=args.timeline_left,
                px_per_sec=round(args.px_per_sec, 4),
                tick_count=calibration.tick_count,
                tick_spacing_px=calibration.tick_spacing_px,
                ruler_major_sec=args.ruler_major_sec,
            )
        if args.auto_track_y:
            layout = detect_track_layout(first_shot, args.timeline_left, args.timeline_right, args.track_y)
            track_y = layout.track_y
            logger.event(
                "track_layout",
                "ok",
                track_y=track_y,
                subtitle_range=layout.subtitle_range,
                filter_range=layout.filter_range,
                source=layout.source,
            )
            if args.require_detected_track and layout.source != "detected_subtitle_below_filter_above":
                raise RuntimeError(f"未能稳定识别字幕下面/滤镜上面的 AI 第二行：{layout.source}")
        else:
            logger.event("track_layout", "manual", track_y=track_y)
        if args.detect_existing_ai_track:
            existing_track = detect_existing_ai_track(first_shot, args.timeline_left, args.timeline_right, track_y)
            if existing_track:
                track_y = existing_track.track_y
                logger.event(
                    "existing_ai_track",
                    "ok",
                    track_y=existing_track.track_y,
                    last_right=existing_track.last_right,
                    rect_count=existing_track.rect_count,
                )
            else:
                logger.event("existing_ai_track", "empty")
    else:
        logger.event("track_layout", "dry_run_no_window", track_y=track_y)

    if args.prepare_source and not args.single_source_per_job:
        args.ai_dir = prepare_drag_source(jobs, log_dir, logger)
    if not args.dry_run and not args.single_source_per_job:
        arrange_explorer(args.ai_dir, args.explorer_height, logger)
    source_grid: dict[str, tuple[int, int]] = {}
    if not args.single_source_per_job:
        source_grid = source_grid_from_explorer(args.ai_dir, logger)
        if not source_grid:
            source_grid = build_source_grid(args.ai_dir, args.grid_cols, args.grid_x0, args.grid_y0, args.grid_col_step, args.grid_row_step)
            logger.event("source_grid_static", "ok", count=len(source_grid))
    failures = 0
    last_same_track_right = existing_track.last_right if existing_track else args.timeline_left - args.same_track_gap_px
    ai_track_anchor_y: int | None = existing_track.track_y if existing_track else None
    shifted_count = 0
    max_shift_sec = 0.0
    for index, job in enumerate(jobs, start=1):
        if not job.image_path.exists():
            logger.image_status(job, "drag_1p3s", "failed", "image file does not exist")
            failures += 1
            if args.stop_on_fail:
                break
            continue
        duration_sec = args.duration_sec if args.duration_sec > 0 else job.duration_sec
        job.duration_sec = duration_sec
        if args.target_mode == "subtitle-block":
            try:
                mapped_index, mapping_method = mapped_subtitle_block_index(job, len(subtitle_blocks))
            except Exception as exc:
                logger.image_status(job, "drag_1p3s", "failed", str(exc))
                failures += 1
                if args.stop_on_fail:
                    break
                continue
            subtitle_block = subtitle_blocks[mapped_index - 1]
            x = subtitle_block.left + args.subtitle_block_offset_x
            width_px = max(8, int(round(duration_sec * args.px_per_sec)))
            target_source = {
                "mode": "subtitle-block",
                "mapping_method": mapping_method,
                "subtitle_block_index": subtitle_block.index,
                "plan_subtitle_block_index": job.subtitle_block_index,
                "script_unit_index": job.script_unit_index,
                "script_unit_count": job.script_unit_count,
                "script_anchor_ratio": job.script_anchor_ratio,
                "subtitle_block": [subtitle_block.left, subtitle_block.top, subtitle_block.right, subtitle_block.bottom],
            }
        else:
            x = target_x(job.start_sec, args.timeline_left, args.px_per_sec, args.visible_start_sec)
            min_width_px = 1 if args.direct_drop else 8
            width_px = max(min_width_px, int(round(duration_sec * args.px_per_sec)))
            target_source = {"mode": "time", "start_sec": job.start_sec}
        wanted_min_x = last_same_track_right + args.same_track_gap_px
        if x < wanted_min_x and args.collision_policy == "exact-or-stop":
            logger.image_status(
                job,
                "drag_1p3s",
                "failed",
                f"exact target would overlap second AI row: target_x={x}, min_x={wanted_min_x}",
            )
            failures += 1
            if args.stop_on_fail:
                break
            continue
        actual_x = max(x, wanted_min_x) if args.collision_policy == "push-right" else x
        shift_px = max(0, actual_x - x)
        shift_sec = max(0.0, shift_px / args.px_per_sec) if args.px_per_sec > 0 else 0.0
        if shift_px > 0:
            shifted_count += 1
            max_shift_sec = max(max_shift_sec, shift_sec)
            if args.target_mode == "subtitle-block":
                shift_too_large = shift_px > args.max_shift_px
                reason = f"same-row shift too large: {shift_px}px"
            else:
                shift_too_large = shift_sec > args.max_shift_sec
                reason = f"same-row shift too large: {shift_sec:.3f}s"
            if shift_too_large:
                logger.image_status(job, "drag_1p3s", "failed", reason)
                failures += 1
                if args.stop_on_fail:
                    break
                continue
        end_x = actual_x + width_px
        if actual_x < args.timeline_left or end_x > args.timeline_right:
            logger.image_status(job, "drag_1p3s", "failed", f"target out of visible timeline: start_x={actual_x}, end_x={end_x}")
            failures += 1
            if args.stop_on_fail:
                break
            continue

        current_ai_dir = args.ai_dir
        current_source_grid = source_grid
        if args.single_source_per_job:
            if args.dry_run:
                current_source_grid = {job.image_id: (args.grid_x0, args.grid_y0)}
                logger.event("single_source", "dry_run", image_id=job.image_id)
            else:
                current_ai_dir = prepare_single_drag_source(job, log_dir, logger)
                arrange_explorer(current_ai_dir, args.explorer_height, logger)
                current_source_grid = source_grid_from_explorer(current_ai_dir, logger)
                if current_source_grid:
                    logger.event("single_source_grid_uia", "ok", image_id=job.image_id, count=len(current_source_grid))
                else:
                    current_source_grid = build_source_grid(
                        current_ai_dir,
                        args.grid_cols,
                        args.grid_x0,
                        args.grid_y0,
                        args.grid_col_step,
                        args.grid_row_step,
                    )
                    logger.event("single_source_grid_static", "ok", image_id=job.image_id, count=len(current_source_grid))

        if job.image_id not in current_source_grid:
            logger.image_status(job, "drag_1p3s", "failed", "source image not visible in source grid")
            failures += 1
            if args.stop_on_fail:
                break
            continue

        src_x, src_y = current_source_grid[job.image_id]
        logger.event(
            "job",
            "start",
            index=index,
            image_id=job.image_id,
            image_path=str(job.image_path),
            start_sec=job.start_sec,
            duration_sec=duration_sec,
            src=[src_x, src_y],
            target_dst=[x, track_y],
            actual_dst=[actual_x, track_y],
            shift_sec=round(shift_sec, 3),
            shift_px=shift_px,
            target_source=target_source,
        )
        if args.dry_run:
            logger.image_status(job, "drag_1p3s", "dry_run")
            last_same_track_right = end_x
            continue

        try:
            if args.seek_before_drop:
                foreground_jianying(logger)
                pyautogui.click(actual_x, args.ruler_y)
                time.sleep(args.after_seek_wait)
                logger.event(
                    "seek_playhead",
                    "ok",
                    image_id=job.image_id,
                    target=[actual_x, args.ruler_y],
                    start_sec=job.start_sec,
                    target_source=target_source,
                )
            arrange_explorer(current_ai_dir, args.explorer_height, logger)
            if args.direct_drop:
                before_drop_shot = screenshot(log_dir, f"drop_before_{index:02d}_{job.image_id}.png")
                pyautogui.moveTo(src_x, src_y)
                time.sleep(0.08)
                pyautogui.dragTo(actual_x, track_y, duration=args.drag_duration, button="left")
                time.sleep(args.after_drop_wait)
                drop_shot = screenshot(log_dir, f"drop_after_{index:02d}_{job.image_id}.png")
                dropped = find_added_clip(before_drop_shot, drop_shot, args.timeline_left, args.timeline_right, width_px)
                if dropped is None:
                    dropped = find_newly_dropped_clip(drop_shot, layout, args.timeline_left, args.timeline_right, width_px)
                if dropped is None:
                    raise RuntimeError("直接拖入后没有真实量到 AI 图片片段，停止")
                expected_track_y = ai_track_anchor_y if ai_track_anchor_y is not None else track_y
                if abs(dropped.left - actual_x) > args.drop_target_tolerance_px:
                    raise RuntimeError(
                        f"直接拖入没有落到目标字幕头：actual_x={dropped.left}, expected_x={actual_x}"
                    )
                if abs(dropped.center_y - expected_track_y) > args.track_tolerance_px:
                    raise RuntimeError(
                        f"直接拖入不在同一条 AI 第二轨：actual_y={dropped.center_y}, expected_y={expected_track_y}"
                    )
                if args.require_below_subtitle:
                    final_layout = verify_between_subtitle_and_filter(
                        drop_shot,
                        dropped,
                        args.timeline_left,
                        args.timeline_right,
                        expected_track_y,
                    )
                    logger.event(
                        "relative_track_verify",
                        "ok",
                        image_id=job.image_id,
                        subtitle_range=final_layout.subtitle_range,
                        filter_range=final_layout.filter_range,
                        ai_center_y=dropped.center_y,
                    )
                if args.anchor_to_first_clip_track and ai_track_anchor_y is None:
                    ai_track_anchor_y = dropped.center_y
                    track_y = ai_track_anchor_y
                    logger.event("ai_track_anchor", "ok", ai_track_anchor_y=ai_track_anchor_y)
                logger.event(
                    "direct_drop",
                    "ok",
                    image_id=job.image_id,
                    target=[actual_x, track_y],
                    duration_sec=duration_sec,
                    rect=[dropped.left, dropped.top, dropped.right, dropped.bottom],
                    width=dropped.width,
                    center=[dropped.center_x, dropped.center_y],
                    note="Real screenshot verification passed; no predicted placement accepted.",
                )
                logger.image_status(job, "direct_drop_1p3s", "ok")
                last_same_track_right = actual_x + width_px
                if index % args.screenshot_every == 0:
                    screenshot(log_dir, f"job_{index:02d}_{job.image_id}.png")
                continue

            raise RuntimeError("旧的二段式拖动路线已禁用；正式施工必须使用 direct-drop 真实截图确认")
        except Exception as exc:
            failures += 1
            reason = str(exc)
            logger.image_status(job, "drag_1p3s", "failed", reason)
            logger.event("job", "failed", index=index, image_id=job.image_id, reason=reason)
            screenshot(log_dir, f"failed_{index:02d}_{job.image_id}.png")
            if args.undo_on_fail:
                try:
                    for undo_index in range(args.undo_steps_on_fail):
                        pyautogui.hotkey("ctrl", "z")
                        time.sleep(0.55)
                        screenshot(log_dir, f"undo_after_fail_{index:02d}_{job.image_id}_{undo_index + 1}.png")
                    logger.event("undo_on_fail", "sent", image_id=job.image_id)
                except Exception as undo_exc:
                    logger.event("undo_on_fail", "failed", image_id=job.image_id, reason=str(undo_exc))
            if args.stop_on_fail:
                break

    if not args.dry_run or args.probe_window:
        screenshot(log_dir, "99_after_build.png")
    logger.event(
        "done",
        "ok" if failures == 0 else "partial",
        total=len(jobs),
        failures=failures,
        shifted_count=shifted_count,
        max_shift_sec=round(max_shift_sec, 3),
    )
    return 0 if failures == 0 else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="LEGACY DISABLED: old screenshot-based Jianying drag builder.")
    parser.add_argument("--plan", type=Path, default=None, help="1.3s alignment_report_1p3s.csv. Defaults to latest.")
    parser.add_argument("--ai-dir", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--start-id", default="", help="Resume from this AI image id, e.g. 25.")
    parser.add_argument("--only-ids", default="", help="Comma/space separated AI ids to run, e.g. 02,04,06.")
    parser.add_argument("--max-jobs", type=int, default=0, help="Run only the first N jobs after filtering.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--probe-window", action="store_true", help="With --dry-run, also foreground Jianying and detect the second AI row.")
    parser.add_argument("--execute", action="store_true", help="Required for real UI actions.")
    parser.add_argument("--stop-on-fail", action="store_true", default=True)
    parser.add_argument(
        "--target-mode",
        choices=["subtitle-block", "time"],
        default="subtitle-block",
        help="subtitle-block aligns images to detected orange subtitle clips; time is the legacy fallback.",
    )

    parser.add_argument("--explorer-height", type=int, default=900)
    parser.add_argument("--grid-cols", type=int, default=18)
    parser.add_argument("--grid-x0", type=int, default=185)
    parser.add_argument("--grid-y0", type=int, default=168)
    parser.add_argument("--grid-col-step", type=int, default=87)
    parser.add_argument("--grid-row-step", type=int, default=129)
    parser.add_argument("--prepare-source", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument(
        "--single-source-per-job",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Use a temporary Explorer folder with only the current image, avoiding thumbnail grid mismatches.",
    )

    parser.add_argument("--timeline-left", type=int, default=60)
    parser.add_argument("--timeline-right", type=int, default=3740)
    parser.add_argument("--track-y", type=int, default=1648)
    parser.add_argument("--auto-track-y", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--require-detected-track", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--stage-x", type=int, default=3550)
    parser.add_argument("--duration-sec", type=float, default=1.3)
    parser.add_argument("--same-track-gap-px", type=int, default=12)
    parser.add_argument("--collision-policy", choices=["push-right", "exact-or-stop"], default="exact-or-stop")
    parser.add_argument("--max-shift-sec", type=float, default=999.0)
    parser.add_argument("--max-shift-px", type=int, default=28)
    parser.add_argument("--expected-image-width-px", type=int, default=0)
    parser.add_argument("--subtitle-min-block-width", type=int, default=2)
    parser.add_argument("--subtitle-row-threshold", type=int, default=40)
    parser.add_argument("--subtitle-block-offset-x", type=int, default=0)
    parser.add_argument("--min-subtitle-blocks", type=int, default=3)
    parser.add_argument("--reject-subtitle-hatch-artifacts", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--require-subtitle-coverage", type=float, default=0.8)
    parser.add_argument("--visible-start-sec", type=float, default=0.0)
    parser.add_argument("--px-per-sec", type=float, default=23.0)
    parser.add_argument("--default-image-sec", type=float, default=1.3)
    parser.add_argument(
        "--duration-mode",
        choices=["global-default", "trim-by-pixels"],
        default="global-default",
        help="global-default trusts Jianying's still-image default duration; trim-by-pixels drags the right edge.",
    )
    parser.add_argument(
        "--direct-drop",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Drop each image directly onto the target AI row; intended for zoomed-out full-timeline construction.",
    )
    parser.add_argument(
        "--seek-before-drop",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Click the timeline ruler at the target x before dropping; Jianying snaps new stills to the playhead.",
    )
    parser.add_argument("--ruler-y", type=int, default=1255)
    parser.add_argument("--auto-calibrate-ruler", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--ruler-major-sec", type=float, default=30.0)
    parser.add_argument("--after-seek-wait", type=float, default=0.25)
    parser.add_argument("--strict-duration", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--duration-tolerance-px", type=int, default=4)
    parser.add_argument("--anchor-to-first-clip-track", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--detect-existing-ai-track", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--track-tolerance-px", type=int, default=18)
    parser.add_argument("--drop-target-tolerance-px", type=int, default=28)
    parser.add_argument("--require-below-subtitle", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--undo-on-fail", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--undo-steps-on-fail", type=int, default=4)

    parser.add_argument("--drag-duration", type=float, default=0.7)
    parser.add_argument("--after-drop-wait", type=float, default=1.0)
    parser.add_argument("--post-drop-source-y", type=int, default=1458)
    parser.add_argument("--post-drop-move-y", type=int, default=0)
    parser.add_argument("--post-drop-move-duration", type=float, default=0.35)
    parser.add_argument("--post-drop-move-wait", type=float, default=0.35)
    parser.add_argument("--screenshot-every", type=int, default=5)
    parser.add_argument("--legacy-allow-screenshot-route", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if not args.legacy_allow_screenshot_route:
        print("DISABLED_LEGACY_SCREENSHOT_ROUTE")
        print("这个旧脚本会从剪映截图识别橙色字幕块，已按最终纠偏方案禁用。")
        print("请使用 run_plan_v1.ps1 / broll_plan_pipeline.py 生成 broll_semantic_plan、final_subtitles、broll_exec_plan。")
        return 9

    if not args.dry_run and not args.execute:
        print("STOPPED_SAFE_GUARD")
        print("Use --execute for real Jianying UI construction, or --dry-run for a log-only pass.")
        return 2
    if args.execute and args.direct_drop and args.duration_mode == "trim-by-pixels":
        print("STOPPED_SAFE_GUARD")
        print("Direct-drop is disabled for strict 1.3s execution because it bypasses the trim-and-verify path.")
        return 2
    if args.execute and args.duration_mode == "global-default" and not args.direct_drop:
        print("STOPPED_SAFE_GUARD")
        print("Global-default execution must use --direct-drop with real screenshot verification; legacy staged move is disabled.")
        return 2

    plan = args.plan or latest_fixed_plan(args.runtime)
    jobs = read_jobs(plan, args.start_id, args.only_ids, args.max_jobs)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_dir = args.runtime / f"ui_drag_1p3s_{stamp}"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = JsonLogger(log_dir)
    logger.event("start", "ok", argv=sys.argv[1:], plan=str(plan), job_count=len(jobs), log_dir=str(log_dir))

    print("PLAN")
    print(f"plan: {plan}")
    print(f"jobs: {len(jobs)}")
    print(f"log_dir: {log_dir}")
    return execute_jobs(args, jobs, log_dir, logger)


if __name__ == "__main__":
    raise SystemExit(main())
