from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

from align_ai_images import (
    DEFAULT_OUTPUT_ROOT,
    discover_timelines,
    find_draft_by_project_name,
    SEC,
    build_placements,
    load_subtitles,
    parse_broll,
    resolve_timeline,
)


DEFAULT_CONFIG = Path(r"D:\video tools\jianying-ai-image-aligner\agent_inputs.json")


def read_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"agent 输入配置不存在：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_ai_inputs(broll_md: Path, ai_dir: Path) -> list:
    items = parse_broll(broll_md, ai_dir)
    if not items:
        raise RuntimeError(f"B-ROLL 设计稿中没有找到可施工的 AI静态图条目，或 AI 图片目录没有匹配图片：{broll_md}")
    missing_files = [item for item in items if not item.image.exists()]
    if missing_files:
        ids = ", ".join(f"{item.no:02d}" for item in missing_files)
        raise FileNotFoundError(f"这些 AI 图在目录中不存在：{ids}")
    return items


def resolve_draft_from_config(cfg: dict) -> Path:
    project_name = (cfg.get("project_name") or "").strip()
    draft_root = Path(cfg.get("draft_root") or r"D:\JianyingPro Drafts")
    if project_name:
        return find_draft_by_project_name(draft_root, project_name)

    draft_dir = cfg.get("draft_dir")
    if draft_dir:
        return Path(draft_dir)

    return find_draft_by_project_name(draft_root, "")


def write_report(out_dir: Path, rows: list[dict[str, str]]) -> Path:
    report = out_dir / "alignment_report_1p3s.csv"
    fieldnames = [
        "image_id",
        "image_path",
        "start_sec",
        "end_sec",
        "duration_sec",
        "matched_subtitle",
        "broll_text",
        "match_method",
        "confidence",
    ]
    with report.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return report


def rows_from_placements(placements, duration_sec: float) -> list[dict[str, str]]:
    rows = []
    for placement in sorted(placements, key=lambda p: (p.start, p.item.no)):
        start = placement.start / SEC
        rows.append(
            {
                "image_id": f"{placement.item.no:02d}",
                "image_path": str(placement.item.image),
                "start_sec": f"{start:.3f}",
                "end_sec": f"{start + duration_sec:.3f}",
                "duration_sec": f"{duration_sec:.3f}",
                "matched_subtitle": placement.matched_text,
                "broll_text": placement.item.quote,
                "match_method": f"{placement.source}+fixed_1.3s",
                "confidence": f"{placement.confidence:.3f}",
            }
        )
    return rows


def rows_from_fallback_report(report: Path, valid_ids: set[str], image_by_id: dict[str, Path], duration_sec: float) -> list[dict[str, str]]:
    if not report.exists():
        raise FileNotFoundError(f"fallback alignment report 不存在：{report}")
    with report.open("r", encoding="utf-8-sig", newline="") as f:
        source_rows = list(csv.DictReader(f))
    rows = []
    seen: set[str] = set()
    for row in sorted(source_rows, key=lambda r: (float(r.get("start_sec") or 0), r.get("image_id") or "")):
        image_id = (row.get("image_id") or "").strip().zfill(2)
        if image_id not in valid_ids:
            continue
        start = float(row["start_sec"])
        item = dict(row)
        item["image_id"] = image_id
        item["image_path"] = str(image_by_id[image_id])
        item["start_sec"] = f"{start:.3f}"
        item["end_sec"] = f"{start + duration_sec:.3f}"
        item["duration_sec"] = f"{duration_sec:.3f}"
        item["match_method"] = f"{item.get('match_method', 'fallback_report')}+fixed_1.3s"
        rows.append(item)
        seen.add(image_id)
    missing = sorted(valid_ids - seen)
    if missing:
        raise RuntimeError(f"fallback report 缺少这些 B-ROLL AI 图编号：{', '.join(missing)}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent entry: build a strict 1.3s AI-only construction plan from configured inputs.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--confidence", type=float, default=0.56)
    args = parser.parse_args()

    cfg = read_config(args.config)
    draft = resolve_draft_from_config(cfg)
    timeline_name = (cfg.get("timeline_name") or "").strip()
    timeline = resolve_timeline(draft, timeline_name) if timeline_name else resolve_timeline(draft, None)
    broll_md = Path(cfg["broll_md"])
    ai_dir = Path(cfg["ai_image_dir"])
    duration_sec = float(cfg.get("duration_sec", 1.3))
    if abs(duration_sec - 1.3) > 0.001:
        raise RuntimeError(f"当前工具只允许 1.3 秒施工，配置里是：{duration_sec}")
    if cfg.get("ai_only") is not True:
        raise RuntimeError("agent_inputs.json 必须声明 ai_only=true")

    items = validate_ai_inputs(broll_md, ai_dir)
    image_by_id = {f"{item.no:02d}": item.image for item in items}
    valid_ids = set(image_by_id)
    source = "draft_attachment"
    source_path = ""
    source_error = ""
    try:
        fallback_srt = cfg.get("timeline_source", {}).get("fallback_srt") or ""
        subtitles, subtitle_path, source = load_subtitles(
            draft,
            Path(fallback_srt) if fallback_srt else None,
            timeline_name=timeline_name or None,
        )
        source_path = str(subtitle_path)
        placements = build_placements(items, subtitles, args.confidence)
        rows = rows_from_placements(placements, duration_sec)
    except Exception as exc:
        source_error = str(exc)
        fallback_report = cfg.get("timeline_source", {}).get("fallback_alignment_report") or ""
        allow_report = bool(cfg.get("timeline_source", {}).get("allow_fallback_alignment_report", bool(fallback_report)))
        if not fallback_report or not allow_report:
            raise RuntimeError(
                "无法从当前工程读取字幕时间轴，且未配置 fallback_alignment_report。"
                f" 原始错误：{source_error}"
            ) from exc
        source = "fallback_alignment_report"
        source_path = fallback_report
        rows = rows_from_fallback_report(Path(fallback_report), valid_ids, image_by_id, duration_sec)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = args.output_root / f"ui_plan_agent_1p3s_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = write_report(out_dir, rows)
    manifest = out_dir / "alignment_manifest_1p3s.json"
    manifest.write_text(
        json.dumps(
            {
                "config": str(args.config),
                "draft_root": str(cfg.get("draft_root") or ""),
                "project_name": str(cfg.get("project_name") or ""),
                "draft_dir": str(draft),
                "timeline_name_requested": timeline_name,
                "timeline_resolved": {
                    "index": timeline.index,
                    "id": timeline.id,
                    "name": timeline.name,
                    "path": str(timeline.path),
                    "is_active": timeline.is_active,
                    "script_path": str(timeline.script_path),
                    "script_exists": timeline.script_exists,
                    "script_sentence_count": timeline.script_sentence_count,
                    "script_translate_segment_count": timeline.script_translate_segment_count,
                }
                if timeline
                else None,
                "timelines": [
                    {
                        "index": row.index,
                        "id": row.id,
                        "name": row.name,
                        "is_active": row.is_active,
                        "script_sentence_count": row.script_sentence_count,
                        "script_translate_segment_count": row.script_translate_segment_count,
                    }
                    for row in discover_timelines(draft)
                ],
                "broll_md": str(broll_md),
                "ai_image_dir": str(ai_dir),
                "duration_sec": duration_sec,
                "ai_count": len(items),
                "plan_count": len(rows),
                "timeline_source": source,
                "timeline_source_path": source_path,
                "timeline_source_error_before_fallback": source_error,
                "report": str(report),
                "rules": {
                    "ai_only": True,
                    "track": "subtitle first row, AI second row between subtitle and filter",
                    "duration": "strict 1.3s",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("OK_AGENT_PLAN")
    print(f"ai_items: {len(items)}")
    print(f"placements: {len(rows)}")
    print(f"timeline_source: {source}")
    print(f"report: {report}")
    print(f"manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
