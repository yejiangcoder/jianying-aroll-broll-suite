from __future__ import annotations

import argparse
import csv
import difflib
import json
import math
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime_paths import get_runs_dir

try:
    from PIL import Image, ImageDraw
except Exception as exc:  # pragma: no cover - shown to user in CLI
    raise SystemExit(f"需要 Pillow/PIL 才能读取图片尺寸：{exc}")


DEFAULT_DRAFT_ROOT = Path(r"D:\JianyingPro Drafts")
DEFAULT_OUTPUT_ROOT = get_runs_dir()
OUTPUT_VIDEO_NAME = "ai_image_overlay_16x9.mp4"
TRACK_NAME = "AI_BROLL_BETWEEN_FILTER_AND_SUBTITLE"
VIDEO_RENDER_INDEX = 12000
TEXT_RENDER_INDEX = 15000
FILTER_RENDER_INDEX = 11000
SEC = 1_000_000


@dataclass
class BrollItem:
    no: int
    priority: str
    name: str
    quote: str
    image: Path
    anchor_index: int = 0
    anchor_text: str = ""


@dataclass
class Sentence:
    index: int
    start_raw: int
    end_raw: int
    start: int
    end: int
    text: str
    clean: str


@dataclass
class TimelineInfo:
    index: int
    id: str
    name: str
    path: Path
    is_active: bool
    script_path: Path
    script_exists: bool
    script_sentence_count: int
    script_translate_segment_count: int


@dataclass
class Placement:
    item: BrollItem
    start: int
    end: int
    source: str
    confidence: float
    matched_text: str
    raw_start: int
    raw_end: int

    @property
    def duration(self) -> int:
        return max(0, self.end - self.start)


def norm_text(text: str) -> str:
    text = re.sub(r"\[\.\.\.\s*\d+(?:\.\d+)?s\]", "", text or "")
    text = re.sub(r"[`'\"“”‘’\s，。！？、,.!?：:；;（）()《》<>【】\[\]…\-—·%]", "", text)
    return text.lower()


def is_noise_sentence(text: str) -> bool:
    stripped = (text or "").strip()
    return not norm_text(stripped) or bool(re.fullmatch(r"\[\.\.\.\s*\d+(?:\.\d+)?s\]", stripped))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")


def find_current_draft(draft_root: Path) -> Path:
    if not draft_root.exists():
        raise FileNotFoundError(f"草稿根目录不存在：{draft_root}")

    candidates: list[tuple[int, float, Path]] = []
    for child in draft_root.iterdir():
        if not child.is_dir():
            continue
        content = child / "draft_content.json"
        script = child / "common_attachment" / "attachment_script_video.json"
        timeline_dir = child / "Timelines"
        if not content.exists() and not timeline_dir.exists():
            continue
        locked_score = 1 if (child / ".locked").exists() else 0
        mtimes = [p.stat().st_mtime for p in [content, script, child / "draft_meta_info.json"] if p.exists()]
        mtime = max(mtimes) if mtimes else child.stat().st_mtime
        candidates.append((locked_score, mtime, child))

    if not candidates:
        raise FileNotFoundError(f"没有在 {draft_root} 下找到剪映草稿")

    candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return candidates[0][2]


def find_draft_by_project_name(draft_root: Path, project_name: str) -> Path:
    if not draft_root.exists():
        raise FileNotFoundError(f"剪映草稿根目录不存在：{draft_root}")
    wanted = project_name.strip()
    if not wanted:
        return find_current_draft(draft_root)

    direct = draft_root / wanted
    if direct.exists() and direct.is_dir():
        return direct

    compact_wanted = re.sub(r"\s+", "", wanted).lower()
    matches = [
        child
        for child in draft_root.iterdir()
        if child.is_dir() and re.sub(r"\s+", "", child.name).lower() == compact_wanted
    ]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise RuntimeError(f"工程名匹配到多个草稿：{', '.join(str(p) for p in matches)}")
    raise FileNotFoundError(f"没有在 {draft_root} 下找到工程：{project_name}")


def normalize_timeline_name(name: str) -> str:
    raw = re.sub(r"\s+", "", name or "").lower()
    raw = raw.replace("時間線", "时间线")
    match = re.fullmatch(r"(?:时间线|timeline)?0*(\d+)", raw)
    if match:
        return f"timeline{int(match.group(1))}"
    match = re.fullmatch(r"(?:时间线|timeline)0*(\d+)", raw)
    if match:
        return f"timeline{int(match.group(1))}"
    return raw.replace("时间线", "timeline")


def _script_counts(script_path: Path) -> tuple[int, int]:
    if not script_path.exists():
        return 0, 0
    try:
        data = read_json(script_path).get("script_video", {})
    except Exception:
        return 0, 0
    sentence_count = 0
    for part in data.get("parts", []) or []:
        sentence_count += len(part.get("sentences") or [])
    return sentence_count, len(data.get("translate_segments") or [])


def discover_timelines(draft: Path) -> list[TimelineInfo]:
    timelines_dir = draft / "Timelines"
    project_json = timelines_dir / "project.json"
    layout_json = draft / "timeline_layout.json"
    if not timelines_dir.exists():
        return []

    active_id = ""
    layout_names: dict[str, str] = {}
    layout_order: list[str] = []
    if layout_json.exists():
        try:
            layout = read_json(layout_json)
            active_id = str(layout.get("activeTimeline") or "")
            for dock in layout.get("dockItems", []) or []:
                ids = [str(row) for row in dock.get("timelineIds", []) or []]
                names = [str(row) for row in dock.get("timelineNames", []) or []]
                for idx, timeline_id in enumerate(ids):
                    if timeline_id not in layout_order:
                        layout_order.append(timeline_id)
                    if idx < len(names) and names[idx]:
                        layout_names[timeline_id] = names[idx]
        except Exception:
            pass

    rows: list[dict[str, Any]] = []
    if project_json.exists():
        try:
            project = read_json(project_json)
            for row in project.get("timelines", []) or []:
                if row.get("is_marked_delete"):
                    continue
                timeline_id = str(row.get("id") or "")
                if timeline_id:
                    rows.append({"id": timeline_id, "name": str(row.get("name") or "")})
        except Exception:
            rows = []

    seen = {row["id"] for row in rows}
    for timeline_id in layout_order:
        if timeline_id not in seen:
            rows.append({"id": timeline_id, "name": layout_names.get(timeline_id, "")})
            seen.add(timeline_id)

    for child in timelines_dir.iterdir():
        if child.is_dir() and child.name not in seen:
            rows.append({"id": child.name, "name": ""})
            seen.add(child.name)

    if layout_order:
        order = {timeline_id: i for i, timeline_id in enumerate(layout_order)}
        rows.sort(key=lambda row: order.get(row["id"], len(order) + len(rows)))

    result: list[TimelineInfo] = []
    for index, row in enumerate(rows, start=1):
        timeline_id = row["id"]
        name = row.get("name") or layout_names.get(timeline_id) or f"时间线{index:02d}"
        path = timelines_dir / timeline_id
        script_path = path / "common_attachment" / "attachment_script_video.json"
        sentence_count, segment_count = _script_counts(script_path)
        result.append(
            TimelineInfo(
                index=index,
                id=timeline_id,
                name=name,
                path=path,
                is_active=timeline_id == active_id,
                script_path=script_path,
                script_exists=script_path.exists(),
                script_sentence_count=sentence_count,
                script_translate_segment_count=segment_count,
            )
        )
    return result


def resolve_timeline(draft: Path, timeline_name: str | None) -> TimelineInfo | None:
    timelines = discover_timelines(draft)
    if not timelines:
        return None
    if not timeline_name:
        return next((row for row in timelines if row.is_active), timelines[0])

    wanted = normalize_timeline_name(timeline_name)
    for row in timelines:
        if normalize_timeline_name(row.name) == wanted:
            return row

    number_match = re.search(r"(\d+)", timeline_name)
    if number_match:
        wanted_index = int(number_match.group(1))
        for row in timelines:
            if row.index == wanted_index:
                return row

    available = ", ".join(f"{row.name}({row.id})" for row in timelines)
    raise RuntimeError(f"没有找到时间线：{timeline_name}；可用时间线：{available}")


def parse_broll(md_path: Path, image_dir: Path) -> list[BrollItem]:
    if not md_path.exists():
        raise FileNotFoundError(f"B-roll 文档不存在：{md_path}")
    if not image_dir.exists():
        raise FileNotFoundError(f"AI 图片目录不存在：{image_dir}")

    text = md_path.read_text(encoding="utf-8")
    items: list[BrollItem] = []
    for match in re.finditer(r"(?ms)^【(\d{2})】\s*(.*?)(?=^【\d{2}】|^#\s*4\.|\Z)", text):
        no = int(match.group(1))
        body = match.group(2)
        if "AI静态图" not in body and "画幅：16:9" not in body and "画面名称：" not in body:
            continue
        image_matches = sorted(image_dir.glob(f"S16-1_AI_{no:02d}_*.png"))
        if not image_matches:
            continue
        priority = _field(body, "优先级")
        name = _field(body, "画面名称") or image_matches[0].stem
        quote = (_field(body, "台词落点") or "").strip("“”\"")
        anchor_raw = _field(body, "对齐台词序号")
        anchor_match = re.search(r"\d+", anchor_raw or "")
        anchor_index = int(anchor_match.group(0)) if anchor_match else 0
        anchor_text = (_field(body, "对齐台词起句") or "").strip("“”\"")
        items.append(
            BrollItem(
                no=no,
                priority=priority,
                name=name,
                quote=quote,
                image=image_matches[0],
                anchor_index=anchor_index,
                anchor_text=anchor_text,
            )
        )

    items.sort(key=lambda item: item.no)
    return items


def _field(body: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}：(.+)$", body, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def find_script_file(draft: Path, timeline_name: str | None = None) -> Path:
    if timeline_name:
        timeline = resolve_timeline(draft, timeline_name)
        if timeline and timeline.script_path.exists():
            return timeline.script_path
        raise FileNotFoundError(f"指定草稿范围没有字幕附件：{draft} / {timeline_name}")

    direct = draft / "common_attachment" / "attachment_script_video.json"
    if direct.exists():
        return direct
    active = resolve_timeline(draft, None)
    if active and active.script_path.exists():
        return active.script_path
    for path in draft.glob(r"Timelines\*\common_attachment\attachment_script_video.json"):
        return path
    raise FileNotFoundError(f"当前草稿没有可读字幕附件：{draft}")


def extract_sentences(script_path: Path) -> list[Sentence]:
    data = read_json(script_path)["script_video"]
    raw_rows: list[tuple[int, int, str]] = []
    for part in data.get("parts", []):
        part_start = int(part.get("target_start_time") or 0)
        for sentence in part.get("sentences", []):
            words = sentence.get("words") or []
            text = (sentence.get("text") or sentence.get("origin_text") or "").strip()
            if not text:
                text = "".join((word.get("text") or word.get("origin_text") or "") for word in words)
            if is_noise_sentence(text):
                continue
            starts: list[int] = []
            ends: list[int] = []
            for word in words:
                tr = word.get("time_range") or {}
                start = int(tr.get("start") or 0)
                duration = int(tr.get("duration") or 0)
                starts.append(start)
                ends.append(start + duration)
            if not starts or not ends:
                tr = sentence.get("time_range") or {}
                start = int(tr.get("start") or 0)
                duration = int(tr.get("duration") or 0)
                if duration:
                    starts.append(start)
                    ends.append(start + duration)
            if starts and ends:
                raw_rows.append((part_start + min(starts), part_start + max(ends), text.strip()))

    if not raw_rows:
        raise ValueError(f"字幕附件里没有可用句子：{script_path}")

    raw_rows.sort(key=lambda row: (row[0], row[1]))
    offset = raw_rows[0][0]
    rows: list[Sentence] = []
    for i, (start, end, text) in enumerate(raw_rows):
        rows.append(
            Sentence(
                index=i,
                start_raw=start,
                end_raw=end,
                start=max(0, start - offset),
                end=max(0, end - offset),
                text=text,
                clean=norm_text(text),
            )
        )
    return rows


def parse_srt_time(value: str) -> int:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", value.strip())
    if not match:
        raise ValueError(f"SRT 时间码格式不正确：{value}")
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    return ((hours * 3600 + minutes * 60 + seconds) * 1000 + millis) * 1000


def extract_sentences_from_srt(srt_path: Path) -> list[Sentence]:
    text = srt_path.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\r?\n\r?\n+", text.strip())
    raw_rows: list[tuple[int, int, str]] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        time_line = next((line for line in lines if "-->" in line), "")
        if not time_line:
            continue
        start_text, end_text = [part.strip().split()[0] for part in time_line.split("-->", 1)]
        body_lines = [line for line in lines if line != time_line and not re.fullmatch(r"\d+", line)]
        body = "".join(body_lines).strip()
        if is_noise_sentence(body):
            continue
        raw_rows.append((parse_srt_time(start_text), parse_srt_time(end_text), body))

    if not raw_rows:
        raise ValueError(f"SRT 里没有可用字幕：{srt_path}")

    raw_rows.sort(key=lambda row: (row[0], row[1]))
    offset = raw_rows[0][0]
    rows: list[Sentence] = []
    for i, (start, end, body) in enumerate(raw_rows):
        rows.append(
            Sentence(
                index=i,
                start_raw=start,
                end_raw=end,
                start=max(0, start - offset),
                end=max(0, end - offset),
                text=body,
                clean=norm_text(body),
            )
        )
    return rows


def _subtitle_candidates(draft: Path, timeline_name: str | None) -> list[tuple[Path, str]]:
    candidates: list[tuple[Path, str]] = []
    if timeline_name:
        timeline = resolve_timeline(draft, timeline_name)
        if not timeline:
            raise RuntimeError(f"工程没有可选择的时间线：{draft}")
        candidates.append((timeline.script_path, f"jianying_attachment:{timeline.name}"))
        return candidates

    direct = draft / "common_attachment" / "attachment_script_video.json"
    if direct.exists():
        candidates.append((direct, "jianying_attachment:project_root"))
    active = resolve_timeline(draft, None)
    if active and active.script_path.exists():
        candidates.append((active.script_path, f"jianying_attachment:{active.name}"))
    for timeline in discover_timelines(draft):
        if timeline.script_path.exists():
            candidates.append((timeline.script_path, f"jianying_attachment:{timeline.name}"))

    deduped: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for path, label in candidates:
        resolved = path.resolve()
        if resolved not in seen:
            deduped.append((path, label))
            seen.add(resolved)
    return deduped


def load_subtitles(draft: Path, srt_path: Path | None, timeline_name: str | None = None) -> tuple[list[Sentence], Path, str]:
    errors: list[str] = []
    for script_path, label in _subtitle_candidates(draft, timeline_name):
        if not script_path.exists():
            errors.append(f"{label}: 文件不存在 {script_path}")
            continue
        try:
            return extract_sentences(script_path), script_path, label
        except Exception as exc:
            errors.append(f"{label}: {exc}")

    if not srt_path:
        detail = "；".join(errors) if errors else "没有发现字幕附件"
        raise RuntimeError(f"无法从剪映工程自动读取可匹配字幕时间轴：{detail}")
    return extract_sentences_from_srt(srt_path), srt_path, "srt_fallback"


def score_text(quote: str, candidate: str) -> float:
    q = norm_text(quote)
    c = norm_text(candidate)
    if not q or not c:
        return 0.0
    if q in c:
        return 1.0
    if c in q and len(c) >= 4:
        return min(0.92, len(c) / max(1, len(q)) + 0.25)
    seq = difflib.SequenceMatcher(None, q, c).ratio()
    qset, cset = set(q), set(c)
    overlap = len(qset & cset) / max(1, len(qset | cset))
    # Short Chinese subtitle fragments rarely reach high SequenceMatcher scores;
    # char overlap keeps semantically close punch lines usable without over-trusting them.
    return max(seq, overlap * 0.78)


def best_sentence_match(item: BrollItem, sentences: list[Sentence]) -> tuple[float, int, int, str]:
    best_score = 0.0
    best_start = 0
    best_end = 0
    best_text = ""
    for i in range(len(sentences)):
        for span in (1, 2, 3, 4):
            if i + span > len(sentences):
                continue
            chunk = sentences[i : i + span]
            # Ignore huge overlapping ASR chunks when making a multi-sentence candidate.
            if chunk[-1].end - chunk[0].start > 7 * SEC:
                continue
            text = "".join(row.text for row in chunk)
            score = score_text(item.quote, text) * (0.99 if span > 1 else 1.0)
            if score > best_score:
                best_score = score
                best_start = chunk[0].start
                best_end = chunk[-1].end
                best_text = text
    return best_score, best_start, best_end, best_text


def distribute_fallbacks(
    items: list[BrollItem], sentences: list[Sentence], anchors: dict[int, Placement]
) -> list[Placement]:
    sentence_starts = sorted({s.start for s in sentences if s.end > s.start})
    timeline_end = max(s.end for s in sentences)
    if not sentence_starts or sentence_starts[0] != 0:
        sentence_starts.insert(0, 0)

    placements_by_no: dict[int, Placement] = dict(anchors)
    anchor_numbers = sorted(anchors)
    all_numbers = [item.no for item in items]
    item_by_no = {item.no: item for item in items}

    boundaries = [None] + anchor_numbers + [None]
    for left_no, right_no in zip(boundaries, boundaries[1:]):
        left_index = -1 if left_no is None else all_numbers.index(left_no)
        right_index = len(all_numbers) if right_no is None else all_numbers.index(right_no)
        missing = [item_by_no[no] for no in all_numbers[left_index + 1 : right_index] if no not in placements_by_no]
        if not missing:
            continue
        left_time = 0 if left_no is None else placements_by_no[left_no].end
        right_time = timeline_end if right_no is None else placements_by_no[right_no].start
        if right_time <= left_time:
            right_time = min(timeline_end, left_time + len(missing) * 2 * SEC)
        window_starts = [t for t in sentence_starts if left_time <= t < right_time]
        if len(window_starts) < len(missing):
            step = max(1, (right_time - left_time) // (len(missing) + 1))
            window_starts = [left_time + step * (i + 1) for i in range(len(missing))]
        else:
            step = len(window_starts) / (len(missing) + 1)
            window_starts = [window_starts[max(0, min(len(window_starts) - 1, round(step * (i + 1))))] for i in range(len(missing))]

        for item, start in zip(missing, window_starts):
            placements_by_no[item.no] = Placement(
                item=item,
                start=int(start),
                end=int(min(timeline_end, start + 2_800_000)),
                source="fallback_order",
                confidence=0.0,
                matched_text="按 B-roll 顺序补位",
                raw_start=0,
                raw_end=0,
            )

    placements = [placements_by_no[item.no] for item in items]
    placements.sort(key=lambda p: (p.start, p.item.no))
    return fix_overlaps(placements, timeline_end)


def build_placements(items: list[BrollItem], sentences: list[Sentence], confidence_threshold: float) -> list[Placement]:
    timeline_end = max(s.end for s in sentences)
    anchors: dict[int, Placement] = {}
    for item in items:
        confidence, match_start, match_end, match_text = best_sentence_match(item, sentences)
        if confidence >= confidence_threshold and match_end > match_start:
            anchors[item.no] = Placement(
                item=item,
                start=match_start,
                end=match_end,
                source="subtitle_text_match",
                confidence=confidence,
                matched_text=match_text,
                raw_start=sentences[0].start_raw + match_start,
                raw_end=sentences[0].start_raw + match_end,
            )

    if len(anchors) == len(items):
        return fix_overlaps([anchors[item.no] for item in items], timeline_end)

    # Keep high-confidence subtitle hits, but spread misses across the full subtitle
    # timeline. Anchored-only windows can collapse when only a few items match.
    spread = {p.item.no: p for p in build_placements_spread(items, sentences, confidence_threshold)}
    merged: list[Placement] = []
    for item in items:
        if item.no in anchors:
            merged.append(anchors[item.no])
            continue
        fallback = spread[item.no]
        fallback.source = "fallback_subtitle_spread"
        fallback.confidence = 0.0
        fallback.matched_text = "台词未直接命中，按全片字幕边界均匀铺排"
        merged.append(fallback)
    return fix_overlaps(merged, timeline_end)


def build_placements_spread(items: list[BrollItem], sentences: list[Sentence], confidence_threshold: float) -> list[Placement]:
    timeline_end = max(s.end for s in sentences)
    starts = sorted({s.start for s in sentences if s.end > s.start})
    if not starts or starts[0] != 0:
        starts.insert(0, 0)
    starts = [s for s in starts if 0 <= s < timeline_end]
    starts.append(timeline_end)

    chosen: list[int] = []
    last_index = -1
    for idx, _item in enumerate(items):
        wanted = round(idx * (len(starts) - 1) / max(1, len(items)))
        wanted = max(last_index + 1, min(wanted, len(starts) - 2))
        if wanted <= last_index:
            wanted = min(len(starts) - 2, last_index + 1)
        chosen.append(wanted)
        last_index = wanted

    placements: list[Placement] = []
    for idx, (item, start_index) in enumerate(zip(items, chosen)):
        next_index = chosen[idx + 1] if idx + 1 < len(chosen) else len(starts) - 1
        start = starts[start_index]
        end = starts[next_index]
        if end <= start:
            end = min(timeline_end, start + 1_500_000)
        confidence, match_start, match_end, match_text = best_sentence_match(item, sentences)
        source = "spread_subtitle"
        if confidence >= confidence_threshold:
            source = "spread_subtitle+text_hint"
        placements.append(
            Placement(
                item=item,
                start=start,
                end=end,
                source=source,
                confidence=confidence,
                matched_text=match_text if match_text else "按字幕边界均匀铺轨",
                raw_start=sentences[0].start_raw + match_start if match_text else 0,
                raw_end=sentences[0].start_raw + match_end if match_text else 0,
            )
        )
    return fix_overlaps(placements, timeline_end)


def fix_overlaps(placements: list[Placement], timeline_end: int) -> list[Placement]:
    if not placements:
        return placements
    placements = sorted(placements, key=lambda p: (p.start, p.item.no))
    min_duration = 700_000
    for index, placement in enumerate(placements):
        placement.start = max(0, placement.start)
        placement.end = max(placement.end, placement.start + min_duration)
        if index + 1 < len(placements):
            next_start = placements[index + 1].start
            if placement.end > next_start:
                placement.end = max(placement.start + min_duration, next_start)
    for index in range(1, len(placements)):
        prev = placements[index - 1]
        current = placements[index]
        if current.start < prev.end:
            current.start = prev.end
            current.end = max(current.end, current.start + min_duration)
    for placement in placements:
        if placement.start > timeline_end:
            placement.start = timeline_end
        placement.end = max(placement.end, placement.start + min_duration)
    return sorted(placements, key=lambda p: (p.start, p.item.no))


def empty_materials() -> dict[str, list[Any]]:
    keys = [
        "ai_translates",
        "audio_balances",
        "audio_effects",
        "audio_fades",
        "audio_pannings",
        "audio_pitch_shifts",
        "audio_track_indexes",
        "audios",
        "beats",
        "canvases",
        "chromas",
        "color_curves",
        "common_mask",
        "digital_human_model_dressing",
        "digital_humans",
        "drafts",
        "effects",
        "flowers",
        "green_screens",
        "handwrites",
        "hsl",
        "hsl_curves",
        "images",
        "log_color_wheels",
        "loudnesses",
        "manual_beautys",
        "manual_deformations",
        "material_animations",
        "material_colors",
        "multi_language_refs",
        "placeholder_infos",
        "placeholders",
        "plugin_effects",
        "primary_color_wheels",
        "realtime_denoises",
        "shapes",
        "smart_crops",
        "smart_relights",
        "sound_channel_mappings",
        "speeds",
        "stickers",
        "tail_leaders",
        "text_templates",
        "texts",
        "time_marks",
        "transitions",
        "video_effects",
        "video_radius",
        "video_shadows",
        "video_strokes",
        "video_trackings",
        "videos",
        "vocal_beautifys",
        "vocal_separations",
    ]
    return {key: [] for key in keys}


def make_speed(speed_id: str) -> dict[str, Any]:
    return {"curve_speed": None, "id": speed_id, "mode": 0, "speed": 1.0, "type": "speed"}


def image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as img:
        return img.size


def make_video_material(path: Path, material_id: str) -> dict[str, Any]:
    width, height = image_size(path)
    return {
        "audio_fade": None,
        "category_id": "",
        "category_name": "local",
        "check_flag": 63487,
        "crop": {
            "upper_left_x": 0.0,
            "upper_left_y": 0.0,
            "upper_right_x": 1.0,
            "upper_right_y": 0.0,
            "lower_left_x": 0.0,
            "lower_left_y": 1.0,
            "lower_right_x": 1.0,
            "lower_right_y": 1.0,
        },
        "crop_ratio": "free",
        "crop_scale": 1.0,
        "duration": 10_800_000_000,
        "height": height,
        "id": material_id,
        "local_material_id": "",
        "material_id": material_id,
        "material_name": path.name,
        "media_path": "",
        "path": str(path),
        "type": "photo",
        "width": width,
    }


def make_segment(placement: Placement, material_id: str, speed_id: str) -> dict[str, Any]:
    duration = max(1, placement.duration)
    return {
        "cartoon": False,
        "clip": {
            "alpha": 1.0,
            "flip": {"horizontal": False, "vertical": False},
            "rotation": 0.0,
            "scale": {"x": 1.0, "y": 1.0},
            "transform": {"x": 0.0, "y": 0.0},
        },
        "common_keyframes": [],
        "enable_adjust": True,
        "enable_color_correct_adjust": False,
        "enable_color_curves": True,
        "enable_color_match_adjust": False,
        "enable_color_wheels": True,
        "enable_lut": True,
        "enable_smart_color_adjust": False,
        "extra_material_refs": [speed_id],
        "group_id": "",
        "hdr_settings": {"intensity": 1.0, "mode": 1, "nits": 1000},
        "id": uuid.uuid4().hex,
        "intensifies_audio": False,
        "is_placeholder": False,
        "is_tone_modify": False,
        "keyframe_refs": [],
        "last_nonzero_volume": 1.0,
        "material_id": material_id,
        "render_index": VIDEO_RENDER_INDEX,
        "responsive_layout": {"enable": False, "horizontal_pos_layout": 0, "size_layout": 0, "target_follow": "", "vertical_pos_layout": 0},
        "reverse": False,
        "source_timerange": {"start": 0, "duration": duration},
        "speed": 1.0,
        "target_timerange": {"start": placement.start, "duration": duration},
        "template_id": "",
        "template_scene": "default",
        "track_attribute": 0,
        "track_render_index": 0,
        "uniform_scale": {"on": True, "value": 1.0},
        "visible": True,
        "volume": 1.0,
    }


def make_draft_content(
    placements: list[Placement],
    width: int = 1920,
    height: int = 1080,
    fps: float = 30.0,
    cover_path: Path | None = None,
) -> dict[str, Any]:
    now_us = int(time.time() * 1_000_000)
    materials = empty_materials()
    segments = []
    for placement in placements:
        material_id = uuid.uuid4().hex
        speed_id = uuid.uuid4().hex
        materials["videos"].append(make_video_material(placement.item.image, material_id))
        materials["speeds"].append(make_speed(speed_id))
        segments.append(make_segment(placement, material_id, speed_id))

    duration = max((p.end for p in placements), default=0)
    return {
        "canvas_config": {"background": None, "height": height, "ratio": "original", "width": width},
        "color_space": -1,
        "config": {
            "adjust_max_index": 1,
            "attachment_info": [],
            "combination_max_index": 1,
            "export_range": None,
            "extract_audio_last_index": 1,
            "lyrics_recognition_id": "",
            "lyrics_sync": True,
            "lyrics_taskinfo": [],
            "maintrack_adsorb": False,
            "material_save_mode": 0,
            "multi_language_current": "none",
            "multi_language_list": [],
            "multi_language_main": "none",
            "multi_language_mode": "none",
            "original_sound_last_index": 1,
            "record_audio_last_index": 1,
            "sticker_max_index": 1,
            "subtitle_keywords_config": None,
            "subtitle_recognition_id": "",
            "subtitle_sync": True,
            "system_font_list": [],
            "video_mute": False,
            "zoom_info_params": None,
        },
        "cover": None,
        "create_time": now_us,
        "draft_type": "",
        "duration": duration,
        "extra_info": None,
        "fps": fps,
        "free_render_index_mode_on": False,
        "function_assistant_info": None,
        "group_container": None,
        "id": str(uuid.uuid4()).upper(),
        "is_drop_frame_timecode": False,
        "keyframe_graph_list": [],
        "keyframes": {"adjusts": [], "audios": [], "effects": [], "filters": [], "handwrites": [], "stickers": [], "texts": [], "videos": []},
        "last_modified_platform": {"app_id": 3704, "app_source": "lv", "app_version": "10.7.0", "os": "windows"},
        "lyrics_effects": [],
        "materials": materials,
        "mutable_config": None,
        "name": TRACK_NAME,
        "new_version": "110.0.0",
        "path": "",
        "platform": {"app_id": 3704, "app_source": "lv", "app_version": "10.7.0", "os": "windows"},
        "relationships": [],
        "render_index_track_mode_on": False,
        "retouch_cover": None,
        "smart_ads_info": None,
        "source": "default",
        "static_cover_image_path": str(cover_path) if cover_path else "",
        "time_marks": None,
        "tracks": [
            {
                "attribute": 0,
                "flag": 0,
                "id": uuid.uuid4().hex,
                "is_default_name": False,
                "name": TRACK_NAME,
                "segments": segments,
                "type": "video",
            }
        ],
        "uneven_animation_template_info": None,
        "update_time": now_us,
        "version": 360000,
    }


def copy_companion_assets(draft_path: Path, placements: list[Placement]) -> tuple[list[Placement], int]:
    resource_dir = draft_path / "Resources" / "AI_BROLL"
    resource_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Placement] = []
    total_size = 0
    for placement in placements:
        dst = resource_dir / placement.item.image.name
        shutil.copy2(placement.item.image, dst)
        total_size += dst.stat().st_size
        item = BrollItem(
            no=placement.item.no,
            priority=placement.item.priority,
            name=placement.item.name,
            quote=placement.item.quote,
            image=dst,
        )
        copied.append(
            Placement(
                item=item,
                start=placement.start,
                end=placement.end,
                source=placement.source,
                confidence=placement.confidence,
                matched_text=placement.matched_text,
                raw_start=placement.raw_start,
                raw_end=placement.raw_end,
            )
        )
    return copied, total_size


def write_draft_cover(draft_path: Path, placements: list[Placement]) -> Path | None:
    if not placements:
        return None
    cover_path = draft_path / "draft_cover.jpg"
    normalize_image(placements[0].item.image, cover_path, 1280, 720)
    return cover_path


def make_meta(draft_name: str, draft_path: Path, duration: int, material_size: int, cover_name: str) -> dict[str, Any]:
    now_us = int(time.time() * 1_000_000)
    root_path = draft_path.parent
    drive = draft_path.drive or ""
    return {
        "cloud_draft_cover": False,
        "cloud_draft_sync": False,
        "cloud_package_completed_time": "",
        "draft_cloud_capcut_purchase_info": "",
        "draft_cloud_last_action_download": False,
        "draft_cloud_package_type": "",
        "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": cover_name,
        "draft_deeplink_url": "",
        "draft_enterprise_info": {
            "draft_enterprise_extra": "",
            "draft_enterprise_id": "",
            "draft_enterprise_name": "",
            "enterprise_material": [],
        },
        "draft_fold_path": draft_path.as_posix(),
        "draft_id": str(uuid.uuid4()).upper(),
        "draft_is_ae_produce": False,
        "draft_is_ai_packaging_used": False,
        "draft_is_ai_shorts": False,
        "draft_is_ai_translate": False,
        "draft_is_article_video_draft": False,
        "draft_is_cloud_temp_draft": False,
        "draft_is_from_deeplink": "false",
        "draft_is_invisible": False,
        "draft_is_pippit_draft": False,
        "draft_is_web_article_video": False,
        "draft_materials": [],
        "draft_materials_copied_info": [],
        "draft_name": draft_name,
        "draft_need_rename_folder": False,
        "draft_new_version": "",
        "draft_removable_storage_device": drive,
        "draft_root_path": str(root_path),
        "draft_segment_extra_info": [],
        "draft_timeline_materials_size_": material_size,
        "draft_type": "",
        "draft_web_article_video_enter_from": "",
        "tm_draft_cloud_completed": "",
        "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_modified": 0,
        "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1,
        "tm_draft_cloud_user_id": -1,
        "tm_draft_create": now_us,
        "tm_draft_modified": now_us,
        "tm_draft_removed": 0,
        "tm_duration": duration,
    }


def create_companion_draft(draft_root: Path, placements: list[Placement], name: str, overwrite: bool) -> Path:
    draft_path = draft_root / name
    if draft_path.exists():
        if not overwrite:
            raise FileExistsError(f"辅助草稿已存在：{draft_path}")
        shutil.rmtree(draft_path)
    timeline_id = str(uuid.uuid4()).upper()
    draft_path.mkdir(parents=True)
    (draft_path / "Resources").mkdir()
    timeline_path = draft_path / "Timelines" / timeline_id
    timeline_path.mkdir(parents=True)
    (timeline_path / "common_attachment").mkdir()
    (draft_path / "common_attachment").mkdir()

    resource_placements, material_size = copy_companion_assets(draft_path, placements)
    cover_path = write_draft_cover(draft_path, resource_placements)
    duration = max((p.end for p in resource_placements), default=0)
    content = make_draft_content(resource_placements, cover_path=cover_path)
    write_json(draft_path / "draft_content.json", content)
    write_json(timeline_path / "draft_content.json", content)
    write_json(draft_path / "draft_meta_info.json", make_meta(name, draft_path, duration, material_size, cover_path.name if cover_path else ""))
    write_json(
        draft_path / "Timelines" / "project.json",
        {
            "config": {"color_space": -1, "render_index_track_mode_on": False, "use_float_render": False},
            "create_time": int(time.time() * 1_000_000),
            "id": str(uuid.uuid4()).upper(),
            "main_timeline_id": timeline_id,
            "timelines": [
                {
                    "create_time": int(time.time() * 1_000_000),
                    "id": timeline_id,
                    "is_marked_delete": False,
                    "name": "AI_BROLL",
                    "update_time": int(time.time() * 1_000_000),
                }
            ],
            "update_time": int(time.time() * 1_000_000),
            "version": 0,
        },
    )
    for rel, value in {
        "attachment_pc_common.json": {"ai_packaging_infos": [], "broll": {"ai_packaging_infos": []}},
        "attachment_editing.json": {"editing_draft": {}},
        "draft_virtual_store.json": {"draft_materials": [], "draft_virtual_store": []},
        "timeline_layout.json": {"activeTimeline": timeline_id, "dockItems": [], "layoutOrientation": 1},
        "common_attachment/attachment_pc_timeline.json": {"reference_lines_config": {"horizontal_lines": [], "is_lock": False, "is_visible": False, "vertical_lines": []}, "safe_area_type": 0},
    }.items():
        write_json(draft_path / rel, value)
        if rel.startswith("common_attachment/"):
            write_json(timeline_path / rel, value)
        elif rel in {"attachment_pc_common.json", "attachment_editing.json"}:
            write_json(timeline_path / rel, value)
    (draft_path / "draft_settings").write_text(
        "[General]\n"
        f"draft_create_time={int(time.time())}\n"
        f"draft_last_edit_time={int(time.time())}\n",
        encoding="utf-8",
    )
    return draft_path


def write_reports(output_dir: Path, draft: Path, script_path: Path, items: list[BrollItem], sentences: list[Sentence], placements: list[Placement]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_csv = output_dir / "alignment_report.csv"
    with report_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["编号", "优先级", "画面名称", "图片", "开始秒", "结束秒", "时长秒", "来源", "置信度", "台词落点", "命中的字幕"])
        for p in placements:
            writer.writerow(
                [
                    f"{p.item.no:02d}",
                    p.item.priority,
                    p.item.name,
                    str(p.item.image),
                    f"{p.start / SEC:.3f}",
                    f"{p.end / SEC:.3f}",
                    f"{p.duration / SEC:.3f}",
                    p.source,
                    f"{p.confidence:.3f}",
                    p.item.quote,
                    p.matched_text,
                ]
            )

    srt = output_dir / "detected_subtitles_normalized.srt"
    with srt.open("w", encoding="utf-8") as f:
        for i, s in enumerate(sentences, start=1):
            f.write(f"{i}\n{fmt_srt(s.start)} --> {fmt_srt(s.end)}\n{s.text}\n\n")

    manifest = {
        "draft": str(draft),
        "script_path": str(script_path),
        "image_count": len(items),
        "sentence_count": len(sentences),
        "track_name": TRACK_NAME,
        "video_render_index": VIDEO_RENDER_INDEX,
        "filter_render_index_reference": FILTER_RENDER_INDEX,
        "text_render_index_reference": TEXT_RENDER_INDEX,
        "placements": [
            {
                "no": p.item.no,
                "name": p.item.name,
                "image": str(p.item.image),
                "start_us": p.start,
                "end_us": p.end,
                "source": p.source,
                "confidence": p.confidence,
                "quote": p.item.quote,
                "matched_text": p.matched_text,
            }
            for p in placements
        ],
    }
    write_json(output_dir / "alignment_manifest.json", manifest)


def fmt_srt(us: int) -> str:
    ms = max(0, round(us / 1000))
    hours = ms // 3_600_000
    ms %= 3_600_000
    minutes = ms // 60_000
    ms %= 60_000
    seconds = ms // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def build_overlay_video(placements: list[Placement], output_dir: Path, width: int = 1920, height: int = 1080) -> Path | None:
    if not placements:
        return None
    concat_file = output_dir / "overlay_concat.txt"
    normalized_dir = output_dir / "overlay_frames"
    normalized_dir.mkdir(parents=True, exist_ok=True)

    black_frame = normalized_dir / "000_black.jpg"
    Image.new("RGB", (width, height), (0, 0, 0)).save(black_frame, quality=95)
    lines: list[str] = []
    cursor = 0
    for index, placement in enumerate(placements, start=1):
        if placement.start > cursor:
            lines.append(f"file '{str(black_frame).replace(chr(92), '/')}'")
            lines.append(f"duration {(placement.start - cursor) / SEC:.6f}")
        frame_path = normalized_dir / f"{index:03d}_{placement.item.no:02d}.jpg"
        normalize_image(placement.item.image, frame_path, width, height)
        lines.append(f"file '{str(frame_path).replace(chr(92), '/')}'")
        lines.append(f"duration {max(0.04, placement.duration / SEC):.6f}")
        cursor = max(cursor, placement.end)
    lines.append(f"file '{str(frame_path).replace(chr(92), '/')}'")
    concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    output_video = output_dir / "AI_BROLL_reference_overlay.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-vf",
        f"fps=30,scale={width}:{height},format=yuv420p",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(output_video),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except Exception:
        return None
    return output_video


def normalize_image(src: Path, dst: Path, width: int, height: int) -> None:
    with Image.open(src) as img:
        img = img.convert("RGB")
        canvas = Image.new("RGB", (width, height), (0, 0, 0))
        scale = min(width / img.width, height / img.height)
        new_size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        resized = img.resize(new_size, Image.Resampling.LANCZOS)
        x = (width - new_size[0]) // 2
        y = (height - new_size[1]) // 2
        canvas.paste(resized, (x, y))
        canvas.save(dst, quality=95)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 AI 图片按剪映字幕时间对齐，生成报告和 AI B-roll 辅助草稿。")
    parser.add_argument("--draft-root", type=Path, default=DEFAULT_DRAFT_ROOT)
    parser.add_argument("--draft", type=Path, default=None)
    parser.add_argument("--ai-dir", type=Path, required=True)
    parser.add_argument("--broll-md", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--confidence", type=float, default=0.56)
    parser.add_argument("--companion-name", default="")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--no-overlay-video", action="store_true")
    args = parser.parse_args(argv)

    draft = args.draft if args.draft else find_current_draft(args.draft_root)
    script_path = find_script_file(draft)
    items = parse_broll(args.broll_md, args.ai_dir)
    if not items:
        raise ValueError("没有找到可用 AI 图片条目")
    sentences = extract_sentences(script_path)
    placements = build_placements(items, sentences, args.confidence)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_root / f"run_{stamp}"
    write_reports(output_dir, draft, script_path, items, sentences, placements)

    companion_name = args.companion_name or f"S16-1_AI_BROLL_AUTO_{stamp}"
    companion = create_companion_draft(args.draft_root, placements, companion_name, args.overwrite)
    overlay = None if args.no_overlay_video else build_overlay_video(placements, output_dir)

    print("OK")
    print(f"当前工程: {draft}")
    print(f"字幕附件: {script_path}")
    print(f"AI 图片: {len(items)} 张")
    print(f"字幕句子: {len(sentences)} 条")
    print(f"对齐报告: {output_dir / 'alignment_report.csv'}")
    print(f"对齐清单: {output_dir / 'alignment_manifest.json'}")
    print(f"辅助草稿: {companion}")
    if overlay:
        print(f"参考视频: {overlay}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
