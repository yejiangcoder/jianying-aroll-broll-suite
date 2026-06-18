from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

from direct_draft_broll_writer import AI_TRACK_NAME, draft_video_segments, subtitle_rows
from draft_runtime_binding import DraftRuntimeBinding
from runtime_paths import get_runtime_root


PNG_EXTENSIONS = {".png"}


def safe_name(value: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value, flags=re.UNICODE).strip("._")
    return value[:48] or "image"


def source_images(source_dir: Path, recursive: bool) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    files = [
        path
        for path in source_dir.glob(pattern)
        if path.is_file() and path.suffix.lower() in PNG_EXTENSIONS
    ]
    return sorted(files, key=lambda path: (path.name.lower(), str(path.parent).lower()))


def clean_md_cell(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().strip("“”\"' ")).replace("|", "/")


def md_field(body: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}：(.+)$", body, flags=re.MULTILINE)
    return clean_md_cell(match.group(1)) if match else ""


def reference_table_items(reference_broll: Path) -> dict[str, dict[str, str]]:
    items: dict[str, dict[str, str]] = {}
    for line in reference_broll.read_text("utf-8").splitlines():
        if not line.startswith("|") or "AI静态图" not in line:
            continue
        cells = [clean_md_cell(cell) for cell in line.strip().strip("|").split("|")]
        if len(cells) < 6 or cells[0] in {"序号", "---"}:
            continue
        image_id = cells[0]
        if not re.fullmatch(r"\d+", image_id):
            continue
        items[image_id] = {
            "source_reference_id": image_id,
            "priority": cells[1],
            "quote": cells[2],
            "broll_type": cells[3],
            "design": cells[4],
            "sound": cells[5],
        }
    return items


def reference_static_items(reference_broll: Path) -> list[dict[str, str]]:
    text = reference_broll.read_text("utf-8")
    table = reference_table_items(reference_broll)
    items: list[dict[str, str]] = []
    for match in re.finditer(r"(?ms)^【(\d+)】\s*(.*?)(?=^【\d+】|\Z)", text):
        source_id = match.group(1)
        body = match.group(2)
        name = md_field(body, "画面名称")
        quote = md_field(body, "台词落点")
        direction = md_field(body, "画面方向")
        if not name or not quote or not direction:
            continue
        table_item = table.get(source_id, {})
        items.append(
            {
                "source_reference_id": source_id,
                "priority": md_field(body, "优先级") or table_item.get("priority", "P0"),
                "name": name,
                "frame": md_field(body, "画幅") or "16:9 横屏",
                "quote": quote,
                "align_quote": md_field(body, "对齐台词起句"),
                "direction": direction,
                "negative": md_field(body, "负面约束"),
                "sound": table_item.get("sound", "无"),
                "design": table_item.get("design", direction),
            }
        )
    if not items:
        raise RuntimeError(f"真实 B-Roll 参考稿没有可解析的 AI 静态图清单：{reference_broll}")
    return items


def selected_reference_items(reference_broll: Path, count: int) -> list[dict[str, str]]:
    items = reference_static_items(reference_broll)
    return evenly_spaced(items, count)


def primary_video_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    rows = draft_video_segments(data)
    if not rows:
        raise RuntimeError("当前草稿没有可用于测试 slot 的 video segment")

    groups: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(int(row["track_index"]), []).append(row)
    best_rows = max(
        groups.values(),
        key=lambda values: (sum(int(row["duration_us"]) for row in values), len(values)),
    )
    return sorted(best_rows, key=lambda row: (int(row["start_us"]), int(row["end_us"])))


def containing_video_segment(start_us: int, end_us: int, video_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in video_rows:
        if start_us >= int(row["start_us"]) and end_us <= int(row["end_us"]):
            return row
    return None


def evenly_spaced(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if len(rows) < count:
        raise RuntimeError(f"可用分布式字幕 slot 数量不足：required={count}, actual={len(rows)}")
    if count == 1:
        return [rows[len(rows) // 2]]
    raw_indexes = [round(index * (len(rows) - 1) / (count - 1)) for index in range(count)]
    indexes: list[int] = []
    used: set[int] = set()
    for raw_index in raw_indexes:
        candidates = sorted(range(len(rows)), key=lambda candidate: (abs(candidate - raw_index), candidate))
        chosen = next(candidate for candidate in candidates if candidate not in used)
        used.add(chosen)
        indexes.append(chosen)
    return [rows[index] for index in sorted(indexes)]


def distributed_caption_slots(
    data: dict[str, Any],
    count: int,
    min_caption_duration_us: int,
) -> list[dict[str, Any]]:
    video_rows = primary_video_rows(data)
    captions = subtitle_rows(data)
    candidates: list[dict[str, Any]] = []
    for caption in captions:
        text = str(caption.get("subtitle_text") or "").strip()
        start_us = int(caption.get("start_us") or 0)
        duration_us = int(caption.get("duration_us") or 0)
        end_us = start_us + duration_us
        if not text or duration_us < min_caption_duration_us:
            continue
        container = containing_video_segment(start_us, end_us, video_rows)
        if not container:
            continue
        candidates.append(
            {
                "caption_index": caption.get("subtitle_index"),
                "text": text,
                "target_start_us": start_us,
                "target_end_us": end_us,
                "duration_us": duration_us,
                "container_video_segment": container,
            }
        )
    return evenly_spaced(candidates, count)


def write_broll_test_design(path: Path, slots: list[dict[str, Any]], reference_broll: Path) -> None:
    lines = [
        "# 图片对齐工具分布式台词对齐测试 B-roll 设计稿",
        "",
        f"格式参考：`{reference_broll}`",
        "",
        "说明：正式流程必须消费 B-Roll agent 生成的设计稿。本文件只用于图片对齐工具测试，画面名称/方向/约束来自真实参考稿，台词落点来自当前草稿实际字幕。",
        "",
        "# 1. B-roll 落点表",
        "",
        "| 序号 | 优先级 | 台词落点 | B-roll类型 | 画面设计 | 音效关键词 |",
        "|---|---|---|---|---|---|",
    ]
    for slot in slots:
        reference = slot["reference_broll_item"]
        lines.append(
            "| {image_id} | {priority} | {text} | AI静态图 | {design} | {sound} |".format(
                image_id=slot["image_id"],
                priority=reference.get("priority", "P0"),
                text=clean_md_cell(slot["text"]),
                design=clean_md_cell(reference.get("design") or reference.get("direction") or ""),
                sound=clean_md_cell(reference.get("sound") or "无"),
            )
        )
    lines.extend(["", "# 2. AI静态图清单（测试复用真实设计稿结构）", ""])
    for slot in slots:
        reference = slot["reference_broll_item"]
        lines.extend(
            [
                f"【{slot['image_id']}】",
                f"优先级：{reference.get('priority', 'P0')}",
                f"画面名称：{clean_md_cell(reference.get('name') or Path(slot['image_path']).stem)}",
                f"画幅：{clean_md_cell(reference.get('frame') or '16:9 横屏')}",
                f"台词落点：{clean_md_cell(slot['text'])}",
                f"对齐台词起句：{clean_md_cell(slot['text'])}",
                f"画面方向：{clean_md_cell(reference.get('direction') or reference.get('design') or '')}",
                f"负面约束：{clean_md_cell(reference.get('negative') or '沿用参考设计稿约束，不生成可读文字或真实品牌 Logo。')}",
                f"参考原始编号：{reference.get('source_reference_id', '')}",
                "",
            ]
        )
    path.write_text("\n".join(lines), "utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an isolated 10-image visual_slot_plan test package.")
    parser.add_argument("--draft-dir", type=Path, required=True)
    parser.add_argument("--source-image-dir", type=Path, required=True)
    parser.add_argument("--reference-broll", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--jy-draftc", type=Path, default=None)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--selection-mode", choices=["captions", "video-segments"], default="captions")
    parser.add_argument("--min-caption-duration-us", type=int, default=700_000)
    parser.add_argument("--recursive", action="store_true")
    args = parser.parse_args()

    if args.count <= 0:
        raise RuntimeError("--count 必须大于 0")
    if not args.draft_dir.exists():
        raise FileNotFoundError(f"draft_dir 不存在：{args.draft_dir}")
    if not args.source_image_dir.exists():
        raise FileNotFoundError(f"source_image_dir 不存在：{args.source_image_dir}")
    if not args.reference_broll.exists():
        raise FileNotFoundError(f"reference_broll 不存在：{args.reference_broll}")

    out_dir = args.out_dir or (
        get_runtime_root() / "test_packages" / f"test_visual_slot_package_{time.strftime('%Y%m%d_%H%M%S')}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    test_image_dir = out_dir / "test_ai_images"
    test_image_dir.mkdir(parents=True, exist_ok=True)

    binding = DraftRuntimeBinding.bind(args.draft_dir, args.jy_draftc, out_dir)
    data = binding.decrypt_timeline(out_dir / "draft_content.dec.json")
    images = source_images(args.source_image_dir, args.recursive)
    if len(images) < args.count:
        raise RuntimeError(f"源图片目录 PNG 数量不足：required={args.count}, actual={len(images)}")
    reference_items = selected_reference_items(args.reference_broll, args.count)

    selected_images = images[: args.count]
    if args.selection_mode == "captions":
        selected_targets = distributed_caption_slots(data, args.count, args.min_caption_duration_us)
    else:
        video_rows = primary_video_rows(data)
        if len(video_rows) < args.count:
            raise RuntimeError(f"当前主视频轨 segment 数量不足：required={args.count}, actual={len(video_rows)}")
        selected_targets = [
            {
                "caption_index": "",
                "text": f"测试slot {index:02d} 覆盖视频片段 {str(video['segment_id'])[:8]}",
                "target_start_us": int(video["start_us"]),
                "target_end_us": int(video["end_us"]),
                "duration_us": int(video["duration_us"]),
                "container_video_segment": video,
            }
            for index, video in enumerate(evenly_spaced(video_rows, args.count), start=1)
        ]

    slots: list[dict[str, Any]] = []
    copied_images = []
    for index, (image, target) in enumerate(zip(selected_images, selected_targets), start=1):
        image_id = f"{index:02d}"
        dest = test_image_dir / f"test_AI_{image_id}_{safe_name(image.stem)}.png"
        shutil.copy2(image, dest)
        video = target["container_video_segment"]
        start_us = int(target["target_start_us"])
        end_us = int(target["target_end_us"])
        text = str(target["text"]).strip()
        slot = {
            "slot_id": f"broll_test_{image_id}",
            "image_id": image_id,
            "image_path": str(dest),
            "text": text,
            "target_start_us": start_us,
            "target_end_us": end_us,
            "duration_us": end_us - start_us,
            "source_start_us": 0,
            "source_end_us": 0,
            "container_video_segment_ids": [video["segment_id"]],
            "confidence": 1.0,
            "selection_mode": args.selection_mode,
            "caption_index": target.get("caption_index", ""),
            "reference_broll_item": reference_items[index - 1],
        }
        slots.append(slot)
        copied_images.append({"image_id": image_id, "source": str(image), "copied_to": str(dest)})

    broll_path = out_dir / "broll_test_design.md"
    slot_plan_path = out_dir / "visual_slot_plan.json"
    manifest_path = out_dir / "test_package_manifest.json"

    write_broll_test_design(broll_path, slots, args.reference_broll)
    slot_plan_path.write_text(
        json.dumps(
            {
                "version": "image_aligner_test_visual_slot_v1",
                "draft_dir": str(args.draft_dir),
                "source_image_dir": str(args.source_image_dir),
                "reference_broll": str(args.reference_broll),
                "image_dir": str(test_image_dir),
                "selection_mode": args.selection_mode,
                "min_caption_duration_us": args.min_caption_duration_us,
                "slots": slots,
            },
            ensure_ascii=False,
            indent=2,
        ),
        "utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            {
                "draft_dir": str(args.draft_dir),
                "timeline_id": binding.timeline_id,
                "timeline_name": binding.timeline_name,
                "source_image_dir": str(args.source_image_dir),
                "reference_broll": str(args.reference_broll),
                "image_dir": str(test_image_dir),
                "broll_md": str(broll_path),
                "visual_slot_plan": str(slot_plan_path),
                "copied_images": copied_images,
                "selected_targets": selected_targets,
            },
            ensure_ascii=False,
            indent=2,
        ),
        "utf-8",
    )

    print(f"OUT_DIR={out_dir}")
    print(f"IMAGE_DIR={test_image_dir}")
    print(f"BROLL_MD={broll_path}")
    print(f"VISUAL_SLOT_PLAN={slot_plan_path}")
    print(f"MANIFEST={manifest_path}")
    print(f"TEST_IMAGE_COUNT={len(copied_images)}")
    print(f"TEST_SLOT_COUNT={len(slots)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
