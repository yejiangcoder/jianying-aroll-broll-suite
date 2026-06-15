from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from align_ai_images import (
    DEFAULT_OUTPUT_ROOT,
    SEC,
    discover_timelines,
    extract_sentences,
    extract_sentences_from_srt,
    find_draft_by_project_name,
    norm_text,
    resolve_timeline,
)


DEFAULT_CONFIG = Path(r"D:\video tools\jianying-ai-image-aligner\agent_inputs.json")
READY_THRESHOLD = 0.72


@dataclass
class SemanticItem:
    image_id: str
    image_path: Path
    target_text: str
    before_text: str
    after_text: str
    prompt: str
    duration_sec: float
    note: str
    priority: str = ""
    name: str = ""
    subtitle_block_index_hint: int = 0


@dataclass
class SubtitleRow:
    subtitle_block_index: int
    subtitle_text: str
    start_us: int
    end_us: int
    source: str
    has_text: bool

    @property
    def start_sec(self) -> float:
        return self.start_us / SEC

    @property
    def end_sec(self) -> float:
        return self.end_us / SEC


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"agent 输入配置不存在：{path}")
    return read_json(path)


def clean_text(text: str) -> str:
    return (text or "").strip().strip("“”\"'")


def field(body: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}：(.+)$", body, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def first_field(body: str, keys: list[str]) -> str:
    for key in keys:
        value = field(body, key)
        if value:
            return value
    return ""


def find_image(image_dir: Path, image_id: str) -> Path | None:
    patterns = [
        f"*AI_{image_id}_*.png",
        f"*AI_{image_id}_*.jpg",
        f"*AI_{image_id}_*.jpeg",
        f"*AI_{image_id}_*.webp",
    ]
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(image_dir.glob(pattern))
    matches = sorted({p for p in matches if re.search(rf"(?:^|[_-])AI[_-]{image_id}(?:[_-]|$)", p.stem)})
    return matches[0] if matches else None


def parse_semantic_plan(broll_md: Path, image_dir: Path, duration_sec: float) -> list[SemanticItem]:
    if not broll_md.exists():
        raise FileNotFoundError(f"B-ROLL 设计稿不存在：{broll_md}")
    if not image_dir.exists():
        raise FileNotFoundError(f"AI 静态图目录不存在：{image_dir}")

    text = broll_md.read_text(encoding="utf-8")
    items: list[SemanticItem] = []
    for match in re.finditer(r"(?ms)^【(\d{2})】\s*(.*?)(?=^【\d{2}】|^#\s*\d+\.|\Z)", text):
        image_id = match.group(1)
        body = match.group(2)
        if "画幅：16:9" not in body and "画面名称：" not in body:
            continue
        image_path = find_image(image_dir, image_id)
        if not image_path:
            continue
        anchor_text = clean_text(field(body, "对齐台词起句"))
        quote = clean_text(field(body, "台词落点"))
        target_text = anchor_text or quote
        if not target_text:
            continue
        anchor_raw = field(body, "对齐台词序号")
        anchor_match = re.search(r"\d+", anchor_raw or "")
        items.append(
            SemanticItem(
                image_id=image_id,
                image_path=image_path,
                target_text=target_text,
                before_text=clean_text(
                    first_field(body, ["对齐台词前句", "对齐前句", "前一句", "before_text"])
                ),
                after_text=clean_text(
                    first_field(body, ["对齐台词后句", "对齐后句", "后一句", "after_text"])
                ),
                prompt=field(body, "画面方向") or field(body, "画面设计"),
                duration_sec=duration_sec,
                note=field(body, "备注"),
                priority=field(body, "优先级"),
                name=field(body, "画面名称") or image_path.stem,
                subtitle_block_index_hint=int(anchor_match.group(0)) if anchor_match else 0,
            )
        )

    items.sort(key=lambda item: int(item.image_id))
    return items


def resolve_draft(cfg: dict[str, Any]) -> Path:
    draft_root = Path(cfg.get("draft_root") or r"D:\JianyingPro Drafts")
    project_name = str(cfg.get("project_name") or "").strip()
    if project_name:
        return find_draft_by_project_name(draft_root, project_name)
    draft_dir = cfg.get("draft_dir")
    if draft_dir:
        return Path(draft_dir)
    return find_draft_by_project_name(draft_root, "")


def segments_from_script(script_path: Path, label: str) -> list[SubtitleRow]:
    data = read_json(script_path).get("script_video", {})
    segments = data.get("translate_segments") or []
    rows: list[tuple[int, int]] = []
    for segment in segments:
        target = segment.get("target_time_range") or {}
        start = int(target.get("start") or segment.get("start_time") or 0)
        duration = int(target.get("duration") or segment.get("duration") or 0)
        if duration > 0:
            rows.append((start, start + duration))
    if not rows:
        return []
    rows.sort(key=lambda row: (row[0], row[1]))
    offset = rows[0][0]
    return [
        SubtitleRow(
            subtitle_block_index=index,
            subtitle_text="",
            start_us=max(0, start - offset),
            end_us=max(0, end - offset),
            source=label,
            has_text=False,
        )
        for index, (start, end) in enumerate(rows, start=1)
    ]


def subtitle_rows_from_sentences(script_path: Path, label: str) -> list[SubtitleRow]:
    sentences = extract_sentences(script_path)
    return [
        SubtitleRow(
            subtitle_block_index=index,
            subtitle_text=sentence.text,
            start_us=sentence.start,
            end_us=sentence.end,
            source=label,
            has_text=True,
        )
        for index, sentence in enumerate(sentences, start=1)
    ]


def subtitle_rows_from_srt(srt_path: Path) -> list[SubtitleRow]:
    sentences = extract_sentences_from_srt(srt_path)
    return [
        SubtitleRow(
            subtitle_block_index=index,
            subtitle_text=sentence.text,
            start_us=sentence.start,
            end_us=sentence.end,
            source=f"srt:{srt_path}",
            has_text=True,
        )
        for index, sentence in enumerate(sentences, start=1)
    ]


def load_final_subtitles(
    cfg: dict[str, Any],
    draft: Path,
    srt_override: Path | None,
) -> tuple[list[SubtitleRow], str, str, str]:
    errors: list[str] = []
    srt_path = srt_override
    if not srt_path:
        fallback_srt = ((cfg.get("timeline_source") or {}).get("fallback_srt") or "").strip()
        srt_path = Path(fallback_srt) if fallback_srt else None
    if srt_path:
        if srt_path.exists():
            rows = subtitle_rows_from_srt(srt_path)
            return rows, "srt", str(srt_path), ""
        errors.append(f"SRT 不存在：{srt_path}")

    timeline_name = str(cfg.get("timeline_name") or "").strip()
    try:
        timeline = resolve_timeline(draft, timeline_name or None)
    except Exception as exc:
        timeline = None
        errors.append(str(exc))
    script_candidates: list[tuple[Path, str]] = []
    if timeline:
        script_candidates.append((timeline.script_path, f"jianying_attachment:{timeline.name}"))
    direct = draft / "common_attachment" / "attachment_script_video.json"
    script_candidates.append((direct, "jianying_attachment:project_root"))

    seen: set[Path] = set()
    for script_path, label in script_candidates:
        resolved = script_path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if not script_path.exists():
            errors.append(f"{label} 文件不存在：{script_path}")
            continue
        try:
            rows = subtitle_rows_from_sentences(script_path, label)
            return rows, "jianying_sentences", str(script_path), ""
        except Exception as exc:
            errors.append(f"{label} 没有可读字幕文本：{exc}")
        try:
            rows = segments_from_script(script_path, label)
            if rows:
                return rows, "jianying_translate_segments_no_text", str(script_path), "只有字幕段时间，没有字幕文本"
        except Exception as exc:
            errors.append(f"{label} 读取字幕段失败：{exc}")

    return [], "missing", "", "；".join(errors) if errors else "没有找到最终字幕时间源"


def score_text(target: str, candidate: str) -> float:
    target_norm = norm_text(target)
    candidate_norm = norm_text(candidate)
    if not target_norm or not candidate_norm:
        return 0.0
    if target_norm == candidate_norm:
        return 1.0
    if target_norm in candidate_norm:
        return min(0.98, 0.85 + len(target_norm) / max(1, len(candidate_norm)) * 0.15)
    if candidate_norm in target_norm and len(candidate_norm) >= 4:
        return min(0.92, 0.65 + len(candidate_norm) / max(1, len(target_norm)) * 0.25)
    seq = difflib.SequenceMatcher(None, target_norm, candidate_norm).ratio()
    overlap = len(set(target_norm) & set(candidate_norm)) / max(1, len(set(target_norm) | set(candidate_norm)))
    return max(seq, overlap * 0.78)


def score_candidate(item: SemanticItem, rows: list[SubtitleRow], idx: int) -> float:
    base = score_text(item.target_text, rows[idx].subtitle_text)
    if item.before_text and idx > 0:
        base = max(base, base * 0.86 + score_text(item.before_text, rows[idx - 1].subtitle_text) * 0.14)
    if item.after_text and idx + 1 < len(rows):
        base = max(base, base * 0.86 + score_text(item.after_text, rows[idx + 1].subtitle_text) * 0.14)
    return min(1.0, base)


def build_exec_row(item: SemanticItem, subtitle: SubtitleRow | None, method: str, confidence: float, review: bool, reason: str) -> dict[str, str]:
    start_sec = ""
    end_sec = ""
    candidate_start_sec = ""
    candidate_end_sec = ""
    subtitle_index = ""
    subtitle_text = ""
    if subtitle:
        candidate_start_sec = f"{subtitle.start_sec:.3f}"
        candidate_end_sec = f"{subtitle.end_sec:.3f}"
        subtitle_index = str(subtitle.subtitle_block_index)
        subtitle_text = subtitle.subtitle_text
        if not review:
            start_sec = candidate_start_sec
            end_sec = f"{subtitle.start_sec + item.duration_sec:.3f}"
    return {
        "image_id": item.image_id,
        "image_path": str(item.image_path),
        "target_text": item.target_text,
        "subtitle_block_index": subtitle_index,
        "matched_subtitle_text": subtitle_text,
        "start_sec": start_sec,
        "end_sec": end_sec,
        "duration_sec": f"{item.duration_sec:.3f}",
        "match_confidence": f"{confidence:.3f}",
        "review_required": "true" if review else "false",
        "match_method": method,
        "review_reason": reason,
        "candidate_start_sec": candidate_start_sec,
        "candidate_end_sec": candidate_end_sec,
        "before_text": item.before_text,
        "after_text": item.after_text,
        "prompt": item.prompt,
        "note": item.note,
        "subtitle_block_index_hint": str(item.subtitle_block_index_hint or ""),
    }


def match_exec_plan(items: list[SemanticItem], subtitles: list[SubtitleRow], threshold: float) -> list[dict[str, str]]:
    if not subtitles:
        return [
            build_exec_row(item, None, "missing_subtitle_time_source", 0.0, True, "无法得到最终字幕 start_sec")
            for item in items
        ]

    has_text = any(row.has_text and row.subtitle_text.strip() for row in subtitles)
    rows: list[dict[str, str]] = []
    if not has_text:
        for item in items:
            hint = item.subtitle_block_index_hint
            if hint and 1 <= hint <= len(subtitles):
                rows.append(
                    build_exec_row(
                        item,
                        subtitles[hint - 1],
                        "broll_subtitle_index_hint_no_text",
                        0.650,
                        False,
                        "",
                    )
                )
            else:
                rows.append(
                    build_exec_row(
                        item,
                        None,
                        "subtitle_segments_have_no_text_and_broll_has_no_index_hint",
                        0.0,
                        True,
                        "工程只有字幕段时间，没有字幕文本；B-ROLL 设计稿也没有对齐台词序号",
                    )
                )
        return rows

    for item in items:
        scored = [(score_candidate(item, subtitles, idx), idx) for idx in range(len(subtitles))]
        scored.sort(reverse=True)
        best_score, best_idx = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        review = best_score < threshold or (second_score >= best_score - 0.025 and best_score < 0.98)
        reason = ""
        method = "subtitle_text_match"
        if best_score < threshold:
            reason = f"文本匹配低于阈值 {threshold:.2f}"
            method = "low_confidence_subtitle_text_match"
        elif second_score >= best_score - 0.025 and best_score < 0.98:
            reason = "候选字幕过近，需要人工确认"
            method = "ambiguous_subtitle_text_match"
        rows.append(build_exec_row(item, subtitles[best_idx], method, best_score, review, reason))
    return rows


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def make_unique_output_dir(output_root: Path, prefix: str) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = output_root / f"{prefix}_{stamp}"
    if not base.exists():
        base.mkdir(parents=True, exist_ok=False)
        return base
    for index in range(2, 100):
        candidate = output_root / f"{prefix}_{stamp}_{index:02d}"
        if not candidate.exists():
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
    raise RuntimeError(f"无法创建唯一输出目录：{base}")


def semantic_rows(items: list[SemanticItem]) -> list[dict[str, str]]:
    return [
        {
            "image_id": item.image_id,
            "image_path": str(item.image_path),
            "target_text": item.target_text,
            "before_text": item.before_text,
            "after_text": item.after_text,
            "prompt": item.prompt,
            "duration_sec": f"{item.duration_sec:.3f}",
            "note": item.note,
            "priority": item.priority,
            "name": item.name,
            "subtitle_block_index_hint": str(item.subtitle_block_index_hint or ""),
        }
        for item in items
    ]


def subtitle_csv_rows(subtitles: list[SubtitleRow]) -> list[dict[str, str]]:
    return [
        {
            "subtitle_block_index": str(row.subtitle_block_index),
            "subtitle_text": row.subtitle_text,
            "start_sec": f"{row.start_sec:.3f}",
            "end_sec": f"{row.end_sec:.3f}",
            "source": row.source,
            "has_text": "true" if row.has_text else "false",
        }
        for row in subtitles
    ]


def write_dry_run(out_dir: Path, exec_rows: list[dict[str, str]], target_track_y: str) -> Path:
    ready = [row for row in exec_rows if row["review_required"] == "false" and row["start_sec"]]
    dry_rows = []
    for index, row in enumerate(ready, start=1):
        dry_rows.append(
            {
                "sequence": str(index),
                "image_id": row["image_id"],
                "image_path": row["image_path"],
                "target_text": row["target_text"],
                "subtitle_block_index": row["subtitle_block_index"],
                "start_sec": row["start_sec"],
                "duration_sec": row["duration_sec"],
                "target_track_y": target_track_y,
                "action": "move playhead to start_sec, insert original image on fixed AI_BROLL track, keep 1.3s duration",
            }
        )
    dry_path = out_dir / "dry_run_actions.csv"
    write_csv(
        dry_path,
        dry_rows,
        [
            "sequence",
            "image_id",
            "image_path",
            "target_text",
            "subtitle_block_index",
            "start_sec",
            "duration_sec",
            "target_track_y",
            "action",
        ],
    )
    return dry_path


def write_report(
    out_dir: Path,
    cfg: dict[str, Any],
    draft: Path,
    semantic: list[dict[str, str]],
    subtitles: list[dict[str, str]],
    exec_rows: list[dict[str, str]],
    subtitle_source_kind: str,
    subtitle_source_path: str,
    subtitle_error: str,
    dry_run_path: Path | None,
) -> Path:
    review_count = sum(1 for row in exec_rows if row["review_required"] == "true")
    ready_count = len(exec_rows) - review_count
    status = "READY_FOR_DRY_RUN" if exec_rows and review_count == 0 else "AUXILIARY_MANUAL_REQUIRED"
    report = out_dir / "plan_report.md"
    lines = [
        "# Jianying AI B-roll V1 Plan Report",
        "",
        f"- status: {status}",
        f"- project: {draft}",
        f"- timeline_name: {cfg.get('timeline_name', '')}",
        f"- broll_md: {cfg.get('broll_md', '')}",
        f"- ai_image_dir: {cfg.get('ai_image_dir', '')}",
        f"- duration_sec: {float(cfg.get('duration_sec', 1.3)):.3f}",
        f"- semantic_image_count: {len(semantic)}",
        f"- final_subtitle_count: {len(subtitles)}",
        f"- subtitle_source_kind: {subtitle_source_kind}",
        f"- subtitle_source_path: {subtitle_source_path}",
        f"- ready_count: {ready_count}",
        f"- review_required_count: {review_count}",
    ]
    if subtitle_error:
        lines.append(f"- subtitle_source_note: {subtitle_error}")
    if dry_run_path:
        lines.append(f"- dry_run_actions: {dry_run_path}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- This run does not inspect orange subtitle blocks from screenshots.",
            "- This run does not write Jianying draft files.",
            "- This run does not generate MP4 overlay video.",
            "- Rows with review_required=true are not allowed to enter UI execution.",
        ]
    )
    if review_count:
        lines.extend(["", "## Blocker", ""])
        if not subtitles:
            lines.append("- No reliable final subtitle time source was found.")
        elif subtitle_source_kind == "jianying_translate_segments_no_text":
            lines.append("- Current Jianying attachment has subtitle segment timing but no readable subtitle text.")
            lines.append("- Current B-ROLL entries need `对齐台词序号` to map images onto these segment indexes.")
        else:
            lines.append("- Some B-ROLL target texts did not match final subtitles with enough confidence.")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build B-roll semantic plan and final execution plan without using Jianying UI screenshots.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--srt", type=Path, default=None)
    parser.add_argument("--threshold", type=float, default=READY_THRESHOLD)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict-ready", action="store_true")
    args = parser.parse_args()

    cfg = read_config(args.config)
    duration_sec = float(cfg.get("duration_sec", 1.3))
    if abs(duration_sec - 1.3) > 0.001:
        raise RuntimeError(f"当前工具只允许 1.3 秒，配置里是：{duration_sec}")
    if cfg.get("ai_only") is not True:
        raise RuntimeError("agent_inputs.json 必须声明 ai_only=true")

    draft = resolve_draft(cfg)
    broll_md = Path(cfg["broll_md"])
    ai_dir = Path(cfg["ai_image_dir"])
    items = parse_semantic_plan(broll_md, ai_dir, duration_sec)
    if not items:
        raise RuntimeError(f"B-ROLL 设计稿中没有找到可施工的 AI静态图，或 AI 目录缺少规范命名图片：{broll_md}")

    subtitles, source_kind, source_path, source_error = load_final_subtitles(cfg, draft, args.srt)
    exec_rows = match_exec_plan(items, subtitles, args.threshold)
    semantic = semantic_rows(items)
    subtitle_rows = subtitle_csv_rows(subtitles)

    out_dir = make_unique_output_dir(args.output_root, "plan_v1")

    semantic_fields = [
        "image_id",
        "image_path",
        "target_text",
        "before_text",
        "after_text",
        "prompt",
        "duration_sec",
        "note",
        "priority",
        "name",
        "subtitle_block_index_hint",
    ]
    subtitle_fields = ["subtitle_block_index", "subtitle_text", "start_sec", "end_sec", "source", "has_text"]
    exec_fields = [
        "image_id",
        "image_path",
        "target_text",
        "subtitle_block_index",
        "matched_subtitle_text",
        "start_sec",
        "end_sec",
        "duration_sec",
        "match_confidence",
        "review_required",
        "match_method",
        "review_reason",
        "candidate_start_sec",
        "candidate_end_sec",
        "before_text",
        "after_text",
        "prompt",
        "note",
        "subtitle_block_index_hint",
    ]

    semantic_csv = out_dir / "broll_semantic_plan.csv"
    semantic_json = out_dir / "broll_semantic_plan.json"
    subtitles_csv = out_dir / "final_subtitles.csv"
    subtitles_json = out_dir / "final_subtitles.json"
    exec_csv = out_dir / "broll_exec_plan.csv"
    exec_json = out_dir / "broll_exec_plan.json"

    write_csv(semantic_csv, semantic, semantic_fields)
    write_json(semantic_json, semantic)
    write_csv(subtitles_csv, subtitle_rows, subtitle_fields)
    write_json(subtitles_json, subtitle_rows)
    write_csv(exec_csv, exec_rows, exec_fields)
    write_json(exec_json, exec_rows)

    dry_path = None
    if args.dry_run:
        target_track_y = str((cfg.get("ui_execution") or {}).get("target_track_y") or "")
        dry_path = write_dry_run(out_dir, exec_rows, target_track_y)

    report = write_report(
        out_dir,
        cfg,
        draft,
        semantic,
        subtitle_rows,
        exec_rows,
        source_kind,
        source_path,
        source_error,
        dry_path,
    )
    review_count = sum(1 for row in exec_rows if row["review_required"] == "true")
    ready_count = len(exec_rows) - review_count
    manifest = {
        "status": "ready" if exec_rows and review_count == 0 else "manual_required",
        "output_dir": str(out_dir),
        "config": str(args.config),
        "draft": str(draft),
        "project_name": str(cfg.get("project_name") or ""),
        "timeline_name": str(cfg.get("timeline_name") or ""),
        "broll_md": str(broll_md),
        "ai_image_dir": str(ai_dir),
        "duration_sec": duration_sec,
        "semantic_image_count": len(semantic),
        "final_subtitle_count": len(subtitle_rows),
        "ready_count": ready_count,
        "review_required_count": review_count,
        "subtitle_source_kind": source_kind,
        "subtitle_source_path": source_path,
        "subtitle_source_note": source_error,
        "semantic_csv": str(semantic_csv),
        "final_subtitles_csv": str(subtitles_csv),
        "exec_csv": str(exec_csv),
        "dry_run_actions_csv": str(dry_path) if dry_path else "",
        "report": str(report),
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
        "rules": {
            "no_ui_screenshot_subtitle_detection": True,
            "no_draft_write": True,
            "no_mp4_overlay": True,
            "ai_only": True,
            "duration_sec": 1.3,
        },
    }
    manifest_path = out_dir / "manifest.json"
    write_json(manifest_path, manifest)

    print("OK_BROLL_PLAN_PIPELINE")
    print(f"status: {manifest['status']}")
    print(f"semantic_images: {len(semantic)}")
    print(f"final_subtitles: {len(subtitle_rows)}")
    print(f"ready: {ready_count}")
    print(f"review_required: {review_count}")
    print(f"subtitle_source: {source_kind}")
    if source_error:
        print(f"subtitle_note: {source_error}")
    print(f"output_dir: {out_dir}")
    print(f"semantic_plan: {semantic_csv}")
    print(f"final_subtitles: {subtitles_csv}")
    print(f"exec_plan: {exec_csv}")
    print(f"report: {report}")

    if args.strict_ready and review_count:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
