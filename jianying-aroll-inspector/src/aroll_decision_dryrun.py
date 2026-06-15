from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any


TOOL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = TOOL_ROOT / "runtime"
DEFAULT_SUBTITLE_SOURCE = (
    TOOL_ROOT
    / "runtime"
    / "aroll_inspect_20260614_111146"
    / "subtitle_timeline.json"
)
LEAD_GUARD_US = 200_000
TAIL_GUARD_US = 300_000
NORMAL_PAUSE_MS = 60


def read_json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def clean_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def uid_for_index(index: int) -> str:
    return f"sub_{index:06d}"


def make_span_text(rows_by_index: dict[int, dict[str, Any]], start_index: int, end_index: int) -> str:
    return "".join(clean_text(rows_by_index[i].get("subtitle_text") or "") for i in range(start_index, end_index + 1))


def make_candidate(
    cluster_id: str,
    take_no: int,
    rows_by_index: dict[int, dict[str, Any]],
    start_index: int,
    end_index: int,
    quality_score: int,
    quality_reasons: list[str],
    problems: list[str],
) -> dict[str, Any]:
    start_row = rows_by_index[start_index]
    end_row = rows_by_index[end_index]
    return {
        "take_id": f"{cluster_id}_take_{take_no:02d}",
        "subtitle_start_uid": start_row["subtitle_uid"],
        "subtitle_end_uid": end_row["subtitle_uid"],
        "subtitle_start_index": start_index,
        "subtitle_end_index": end_index,
        "text": make_span_text(rows_by_index, start_index, end_index),
        "quality_score": quality_score,
        "quality_reasons": quality_reasons,
        "problems": problems,
    }


def quality_for_action(action: str, reason: str) -> tuple[int, list[str], list[str]]:
    if action == "keep":
        return (
            86,
            ["语义更完整", "更接近正式表达", "上下文衔接更顺"],
            [],
        )
    if "partial" in reason or "半句" in reason:
        return (
            42,
            ["保留为候选供审查"],
            ["半句/没说完", "后文已有更完整版本"],
        )
    if "self" in reason or "重复" in reason:
        return (
            48,
            ["保留为候选供审查"],
            ["自我重复/卡顿", "后文已有更干净版本"],
        )
    return (
        55,
        ["保留为候选供审查"],
        ["语义重复或表达不如 best_take"],
    )


def predefined_take_groups() -> list[dict[str, Any]]:
    # Phase 3A uses the original 6月14日 subtitle source as a dry-run sample.
    # These groups are text-review decisions only; no audio clarity is scored here.
    return [
        {
            "intent_summary": "表达有人想爬出困境时，旁人会把他拽回来",
            "cluster_type": "repeated_take",
            "decision_reason": "第 7 条补全了“爬出粪坑”，第 6 条只是起句废 take。",
            "takes": [(6, 6, "drop", "partial_restart"), (7, 7, "keep", "best_complete")],
        },
        {
            "intent_summary": "引出“有这么一群精分数字游民”",
            "cluster_type": "repeated_take",
            "decision_reason": "第 13-14 条比第 12 条更完整，补出了“数字游民”的正式对象。",
            "takes": [(12, 12, "drop", "less_specific"), (13, 14, "keep", "best_complete")],
        },
        {
            "intent_summary": "恨不得给硅谷大佬当牛做马",
            "cluster_type": "self_correction",
            "decision_reason": "第 17 条有明显重复卡顿，第 18 条是干净版本。",
            "takes": [(17, 17, "drop", "self_repetition"), (18, 18, "keep", "best_clean")],
        },
        {
            "intent_summary": "年少时把他当成寻找优越感的弱智对象",
            "cluster_type": "ng_restart",
            "decision_reason": "第 24 条停在“寻”，第 25-26 条完成了句子。",
            "takes": [(24, 24, "drop", "partial_restart"), (25, 26, "keep", "best_complete")],
        },
        {
            "intent_summary": "嘉豪敢相信自己就是主角",
            "cluster_type": "ng_restart",
            "decision_reason": "第 30 条没说完，第 31 条表达完整。",
            "takes": [(30, 30, "drop", "partial_restart"), (31, 31, "keep", "best_complete")],
        },
        {
            "intent_summary": "嘉豪不是中二",
            "cluster_type": "semantic_duplicate",
            "decision_reason": "第 40 条是第 39 条的强化修正版。",
            "takes": [(39, 39, "drop", "less_final"), (40, 40, "keep", "best_final")],
        },
        {
            "intent_summary": "是你杀死了年少时候的自己",
            "cluster_type": "ng_restart",
            "decision_reason": "第 41 条只起了半句，第 42 条完整。",
            "takes": [(41, 41, "drop", "partial_restart"), (42, 42, "keep", "best_complete")],
        },
        {
            "intent_summary": "评论区全是哇塞姐妹底子好",
            "cluster_type": "repeated_take",
            "decision_reason": "第 47-48 条比第 46 条更完整，包含具体评论内容。",
            "takes": [(46, 46, "drop", "partial_restart"), (47, 48, "keep", "best_complete")],
        },
        {
            "intent_summary": "你可以嘲笑她们虚伪",
            "cluster_type": "semantic_duplicate",
            "decision_reason": "第 49 条代词更贴合女性语境，第 50 条是重复改口。",
            "takes": [(49, 49, "keep", "better_context"), (50, 50, "drop", "semantic_duplicate")],
        },
        {
            "intent_summary": "从金融视角看集体做多",
            "cluster_type": "ng_restart",
            "decision_reason": "第 51 条停在“角”，第 52 条完整进入金融视角。",
            "takes": [(51, 51, "drop", "partial_restart"), (52, 52, "keep", "best_complete")],
        },
        {
            "intent_summary": "普通四分女获得敢要彩礼的底气",
            "cluster_type": "repeated_take",
            "decision_reason": "第 57-58 条完成核心表达，第 56 条只是铺垫起句。",
            "takes": [(56, 56, "drop", "partial_restart"), (57, 58, "keep", "best_complete")],
        },
        {
            "intent_summary": "兄弟健身却被说死肌肉",
            "cluster_type": "semantic_duplicate",
            "decision_reason": "第 65-66 条是第 63-64 条的重复修正版，按最后一遍保留。",
            "takes": [(63, 64, "drop", "earlier_duplicate"), (65, 66, "keep", "best_final")],
        },
        {
            "intent_summary": "亲手摧毁男性基本盘",
            "cluster_type": "ng_restart",
            "decision_reason": "第 69 条有重复起句，第 70 条补全核心宾语。",
            "takes": [(69, 69, "drop", "self_repetition"), (70, 70, "keep", "best_complete")],
        },
        {
            "intent_summary": "导致国男在婚恋市场举步维艰",
            "cluster_type": "ng_restart",
            "decision_reason": "第 72 条停在“婚”，第 73 条完整。",
            "takes": [(72, 72, "drop", "partial_restart"), (73, 73, "keep", "best_complete")],
        },
        {
            "intent_summary": "为了低调受过的气全是笑话",
            "cluster_type": "repeated_take",
            "decision_reason": "第 89 条补出“为了低调”，比第 87-88 条更完整。",
            "takes": [(87, 88, "drop", "earlier_incomplete"), (89, 89, "keep", "best_complete")],
        },
        {
            "intent_summary": "把敢于在舞台中央说话的自己挖出来",
            "cluster_type": "ng_restart",
            "decision_reason": "第 96-97 条没完成对象，第 98-100 条完成正式表达。",
            "takes": [(96, 97, "drop", "partial_restart"), (98, 100, "keep", "best_complete")],
        },
        {
            "intent_summary": "抢回输掉的尊严",
            "cluster_type": "semantic_duplicate",
            "decision_reason": "第 113-114 条比第 112 条更适合最终收束，表达更干净。",
            "takes": [(112, 112, "drop", "less_final"), (113, 114, "keep", "best_final")],
        },
    ]


def build_clusters(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows_by_index = {int(row["subtitle_index"]): row for row in rows}
    used: set[int] = set()
    clusters: list[dict[str, Any]] = []
    decision_spans: list[dict[str, Any]] = []

    def add_decision_span(cluster: dict[str, Any], candidate: dict[str, Any], decision: str, reason: str) -> None:
        decision_spans.append(
            {
                "span_id": "",
                "subtitle_start_uid": candidate["subtitle_start_uid"],
                "subtitle_end_uid": candidate["subtitle_end_uid"],
                "subtitle_start_index": candidate["subtitle_start_index"],
                "subtitle_end_index": candidate["subtitle_end_index"],
                "decision": decision,
                "cluster_id": cluster["cluster_id"],
                "take_id": candidate["take_id"],
                "pause_after_ms": NORMAL_PAUSE_MS if decision == "keep" else 0,
                "pause_type": "normal" if decision == "keep" else "none",
                "mapped_text": candidate["text"],
                "reason": reason,
            }
        )

    cluster_no = 1
    for group in predefined_take_groups():
        valid = True
        for start, end, _action, _reason in group["takes"]:
            if any(index not in rows_by_index for index in range(start, end + 1)):
                valid = False
                break
        if not valid:
            continue
        cluster_id = f"tc_{cluster_no:03d}"
        cluster_no += 1
        candidates: list[dict[str, Any]] = []
        best_take_id = ""
        drop_take_ids: list[str] = []
        for take_no, (start, end, action, reason) in enumerate(group["takes"], start=1):
            quality_score, quality_reasons, problems = quality_for_action(action, reason)
            candidate = make_candidate(
                cluster_id,
                take_no,
                rows_by_index,
                start,
                end,
                quality_score,
                quality_reasons,
                problems,
            )
            candidates.append(candidate)
            for index in range(start, end + 1):
                used.add(index)
            if action == "keep":
                best_take_id = candidate["take_id"]
            else:
                drop_take_ids.append(candidate["take_id"])
        if not best_take_id:
            best_take_id = max(candidates, key=lambda item: int(item["quality_score"]))["take_id"]
            drop_take_ids = [candidate["take_id"] for candidate in candidates if candidate["take_id"] != best_take_id]
        cluster = {
            "cluster_id": cluster_id,
            "intent_summary": group["intent_summary"],
            "cluster_type": group["cluster_type"],
            "candidates": candidates,
            "best_take_id": best_take_id,
            "drop_take_ids": drop_take_ids,
            "decision_reason": group["decision_reason"],
        }
        clusters.append(cluster)
        for candidate in candidates:
            decision = "keep" if candidate["take_id"] == best_take_id else "drop"
            add_decision_span(
                cluster,
                candidate,
                decision,
                "best take in repeated cluster" if decision == "keep" else "dropped duplicate / less clean take",
            )

    for index in sorted(rows_by_index):
        if index in used:
            continue
        cluster_id = f"tc_{cluster_no:03d}"
        cluster_no += 1
        candidate = make_candidate(
            cluster_id,
            1,
            rows_by_index,
            index,
            index,
            80,
            ["无相邻重复 take", "作为连续上下文保留"],
            [],
        )
        cluster = {
            "cluster_id": cluster_id,
            "intent_summary": candidate["text"][:40],
            "cluster_type": "single_clean_take",
            "candidates": [candidate],
            "best_take_id": candidate["take_id"],
            "drop_take_ids": [],
            "decision_reason": "未识别到重复 take，默认保留以保证完整内容。",
        }
        clusters.append(cluster)
        add_decision_span(cluster, candidate, "keep", "single clean take / preserve content")

    decision_spans.sort(key=lambda item: (int(item["subtitle_start_index"]), int(item["subtitle_end_index"])))
    for index, span in enumerate(decision_spans, start=1):
        span["span_id"] = f"sp_{index:03d}"
    clusters.sort(key=lambda cluster: min(candidate["subtitle_start_index"] for candidate in cluster["candidates"]))
    return clusters, decision_spans


def validate_spans(spans: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid_indices = {int(row["subtitle_index"]) for row in rows}
    uid_by_index = {int(row["subtitle_index"]): row["subtitle_uid"] for row in rows}
    covered: list[int] = []
    fatal_reasons: list[str] = []
    warnings: list[str] = []
    uid_index_valid = True

    for span in spans:
        start = int(span["subtitle_start_index"])
        end = int(span["subtitle_end_index"])
        if start > end:
            fatal_reasons.append(f"SPAN_INDEX_REVERSED:{span['span_id']}")
        if start not in valid_indices or end not in valid_indices:
            uid_index_valid = False
            fatal_reasons.append(f"SPAN_INDEX_NOT_FOUND:{span['span_id']}")
            continue
        if span["subtitle_start_uid"] != uid_by_index[start] or span["subtitle_end_uid"] != uid_by_index[end]:
            uid_index_valid = False
            fatal_reasons.append(f"SPAN_UID_INDEX_MISMATCH:{span['span_id']}")
        covered.extend(range(start, end + 1))

    counter = Counter(covered)
    duplicates = [index for index, count in counter.items() if count > 1]
    missing = sorted(valid_indices - set(covered))
    extra = sorted(set(covered) - valid_indices)
    no_overlap = not duplicates
    if duplicates:
        fatal_reasons.append(f"SPAN_OVERLAP:{duplicates[:20]}")
    if missing:
        fatal_reasons.append(f"SPAN_COVERAGE_MISSING:{missing[:20]}")
    if extra:
        fatal_reasons.append(f"SPAN_COVERAGE_EXTRA:{extra[:20]}")
    sorted_spans = sorted(spans, key=lambda item: int(item["subtitle_start_index"]))
    for previous, current in zip(sorted_spans, sorted_spans[1:]):
        if int(current["subtitle_start_index"]) <= int(previous["subtitle_end_index"]):
            fatal_reasons.append(f"SPAN_ORDER_OVERLAP:{previous['span_id']}->{current['span_id']}")
            break
    keep_count = sum(1 for span in spans if span["decision"] == "keep")
    drop_count = sum(1 for span in spans if span["decision"] == "drop")
    if drop_count == 0:
        warnings.append("NO_DROP_SPANS_DETECTED")
    return {
        "uid_index_valid": uid_index_valid,
        "no_overlap": no_overlap,
        "coverage_summary": f"covered {len(set(covered))}/{len(valid_indices)} subtitle indices; keep_spans={keep_count}; drop_spans={drop_count}",
        "fatal_reasons": sorted(set(fatal_reasons)),
        "warnings": sorted(set(warnings)),
    }


def estimate_span_duration_us(span: dict[str, Any], rows_by_index: dict[int, dict[str, Any]]) -> int:
    start = int(span["subtitle_start_index"])
    end = int(span["subtitle_end_index"])
    return int(rows_by_index[end]["end_us"]) - int(rows_by_index[start]["start_us"])


def estimate_final_with_guard_us(spans: list[dict[str, Any]], rows_by_index: dict[int, dict[str, Any]]) -> int:
    total = 0
    for span in spans:
        if span["decision"] != "keep":
            continue
        start = int(span["subtitle_start_index"])
        end = int(span["subtitle_end_index"])
        cut_start = max(0, int(rows_by_index[start]["start_us"]) - LEAD_GUARD_US)
        cut_end = int(rows_by_index[end]["end_us"]) + TAIL_GUARD_US
        total += max(0, cut_end - cut_start) + int(span.get("pause_after_ms") or 0) * 1000
    return total


def load_source_duration_us(subtitle_path: Path, rows: list[dict[str, Any]]) -> int:
    report_path = subtitle_path.parent / "aroll_inspect_report.json"
    if report_path.exists():
        try:
            report = read_json(report_path)
            selected = report.get("selected_main_video_track") or {}
            duration = int(selected.get("total_target_duration_us") or 0)
            if duration > 0:
                return duration
        except Exception:
            pass
    return max(int(row["end_us"]) for row in rows) if rows else 0


def run_decision_dryrun(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    run_dir = args.runtime / f"aroll_decision_dryrun_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    rows = read_json(args.subtitle_timeline)
    rows = sorted(rows, key=lambda item: int(item["subtitle_index"]))
    rows_by_index = {int(row["subtitle_index"]): row for row in rows}
    source_duration_us = load_source_duration_us(args.subtitle_timeline, rows)

    clusters, spans = build_clusters(rows)
    validation = validate_spans(spans, rows)
    kept_duration = sum(estimate_span_duration_us(span, rows_by_index) for span in spans if span["decision"] == "keep")
    dropped_duration = sum(estimate_span_duration_us(span, rows_by_index) for span in spans if span["decision"] == "drop")
    final_with_guard = estimate_final_with_guard_us(spans, rows_by_index)
    drop_reasons = Counter(
        span["reason"] for span in spans if span["decision"] == "drop"
    ).most_common()

    take_clusters = {
        "source": "subtitle_timeline",
        "subtitle_count": len(rows),
        "clusters": clusters,
    }
    decisions = {
        "source": "subtitle_timeline",
        "decision_mode": "take_cluster_best_take_selection",
        "spans": spans,
    }
    report = {
        "subtitle_count": len(rows),
        "cluster_count": len(clusters),
        "keep_span_count": sum(1 for span in spans if span["decision"] == "keep"),
        "drop_span_count": sum(1 for span in spans if span["decision"] == "drop"),
        "estimated_original_duration_us": source_duration_us,
        "estimated_kept_duration_us": kept_duration,
        "estimated_dropped_duration_us": dropped_duration,
        "estimated_final_duration_us_with_guard": final_with_guard,
        "top_drop_reasons": [{"reason": reason, "count": count} for reason, count in drop_reasons],
        "validation": validation,
        "limitations": [
            "本轮基于字幕文本和上下文选择 best take，不包含真实音频清晰度评分。",
            "本轮未调用 DeepSeek/API；当前输出是本地 dry-run 裁决，适合人工审查和后续接入外部 LLM 前校验 schema。",
        ],
    }

    clusters_path = run_dir / "take_clusters.json"
    decisions_path = run_dir / "deepseek_aroll_decisions.json"
    report_path = run_dir / "aroll_decision_report.json"
    write_json(clusters_path, take_clusters)
    write_json(decisions_path, decisions)
    write_json(report_path, report)
    return run_dir, clusters_path, decisions_path, report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate A-Roll take decision dry-run JSON from subtitle_timeline.json.")
    parser.add_argument("--subtitle-timeline", type=Path, default=DEFAULT_SUBTITLE_SOURCE)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    args = parser.parse_args()
    run_dir, clusters_path, decisions_path, report_path = run_decision_dryrun(args)
    report = read_json(report_path)
    print("status=ok" if not report["validation"]["fatal_reasons"] else "status=blocked")
    print(f"runtime={run_dir}")
    print(f"take_clusters={clusters_path}")
    print(f"decisions={decisions_path}")
    print(f"report={report_path}")
    print(f"subtitle_count={report['subtitle_count']}")
    print(f"cluster_count={report['cluster_count']}")
    print(f"keep_spans={report['keep_span_count']}")
    print(f"drop_spans={report['drop_span_count']}")
    if report["validation"]["fatal_reasons"]:
        print("fatal_reasons=" + ",".join(report["validation"]["fatal_reasons"]))
    if report["validation"]["warnings"]:
        print("warnings=" + ",".join(report["validation"]["warnings"]))
    return 0 if not report["validation"]["fatal_reasons"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
