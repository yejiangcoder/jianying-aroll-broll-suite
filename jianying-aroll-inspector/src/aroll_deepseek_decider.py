from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

from aroll_decision_dryrun import (
    DEFAULT_RUNTIME,
    DEFAULT_SUBTITLE_SOURCE,
    LEAD_GUARD_US,
    NORMAL_PAUSE_MS,
    TAIL_GUARD_US,
    clean_text,
    estimate_final_with_guard_us,
    estimate_span_duration_us,
    load_source_duration_us,
    read_json,
    validate_spans,
    write_json,
)
from deepseek_client import (
    DEFAULT_CONFIG,
    DeepSeekConfig,
    extract_json_object,
    extract_message_content,
    load_deepseek_config,
    post_chat_completions,
)


ALLOWED_CLUSTER_TYPES = {
    "repeated_take",
    "self_correction",
    "ng_restart",
    "semantic_duplicate",
    "single_clean_take",
}
ALLOWED_DECISIONS = {"keep", "drop"}


def subtitle_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "uid": row["subtitle_uid"],
            "index": int(row["subtitle_index"]),
            "text": str(row.get("subtitle_text") or ""),
            "start_us": int(row["start_us"]),
            "duration_us": int(row["duration_us"]),
            "end_us": int(row["end_us"]),
        }
        for row in rows
    ]


def build_prompt(rows: list[dict[str, Any]], source_duration_us: int, compact_drop_only: bool = False) -> list[dict[str, str]]:
    subtitles = subtitle_payload(rows)
    system = (
        "你是 A-Roll 剪辑裁决器，不是文案润色器。"
        "你只根据自动识别字幕和上下文，判断哪些是正式 take，哪些是重复、NG、重说、废句、自我修正。"
        "字幕可能有口音错字、断句不准、长短不均，不要因为错字直接判废。"
        "你不能听音频，所以只能用字幕完整度、语义顺畅度、上下文衔接、duration/text 比例代理判断清晰度。"
        "必须只输出 JSON object，不要 markdown，不要解释。"
    )
    user = {
        "task": "对 115 条字幕做 take_cluster best_take 裁决 dry-run。",
        "source": "subtitle_timeline",
        "subtitle_count": len(rows),
        "estimated_original_duration_us": source_duration_us,
        "rules": {
            "keep_priority": [
                "语义最完整的一遍",
                "上下文最顺的一遍",
                "最像最终正式表达的一遍",
                "明显修正后的版本",
                "多遍相近时通常保留最后一遍",
                "字幕识别更完整、句子更连贯的一遍",
            ],
            "drop_must": [
                "明显 NG",
                "自我修正句",
                "同一句前面的失败 take",
                "半句话、说到一半被重说的句子",
                "跟后文重复但更弱的一遍",
                "明显口癖、无内容填充",
                "不构成有效表达的残句",
            ],
            "coverage": [
                "deepseek_aroll_decisions.spans 必须完整覆盖 subtitle_index 1 到 115。",
                "每个字幕 index 只能被一个 span 覆盖。",
                "所有 span 按 index 递增，不能重叠，不能缺失。",
                "不允许输出 material_id、track_id、draft_content 字段。",
                "所有 uid 必须来自输入。",
            ],
        },
        "output_mode": "compact_drop_only" if compact_drop_only else "full_clusters_and_decisions",
        "output_schema": {
            "take_clusters": {
                "source": "subtitle_timeline",
                "subtitle_count": 115,
                "clusters": [
                    {
                        "cluster_id": "tc_001",
                        "intent_summary": "同一意图摘要",
                        "cluster_type": "repeated_take|self_correction|ng_restart|semantic_duplicate|single_clean_take",
                        "candidates": [
                            {
                                "take_id": "tc_001_take_01",
                                "subtitle_start_uid": "sub_000001",
                                "subtitle_end_uid": "sub_000001",
                                "subtitle_start_index": 1,
                                "subtitle_end_index": 1,
                                "text": "候选 take 文本",
                                "quality_score": 80,
                                "quality_reasons": ["为什么质量较高"],
                                "problems": ["若有问题写这里"],
                            }
                        ],
                        "best_take_id": "tc_001_take_01",
                        "drop_take_ids": [],
                        "decision_reason": "为什么选择 best_take",
                    }
                ],
            },
            "deepseek_aroll_decisions": {
                "source": "subtitle_timeline",
                "decision_mode": "real_deepseek_take_cluster_best_take_selection",
                "model": "deepseek-reasoner",
                "spans": [
                    {
                        "span_id": "sp_001",
                        "subtitle_start_uid": "sub_000001",
                        "subtitle_end_uid": "sub_000001",
                        "subtitle_start_index": 1,
                        "subtitle_end_index": 1,
                        "decision": "keep|drop",
                        "cluster_id": "tc_001",
                        "take_id": "tc_001_take_01",
                        "pause_after_ms": 60,
                        "pause_type": "normal|none",
                        "mapped_text": "span 覆盖文本",
                        "reason": "best take in repeated cluster | dropped duplicate / less clean take | single clean take",
                    }
                ],
            },
        },
        "cluster_guidance": [
            "对明显重复/NG/自我修正，建立一个 cluster，候选 take 可以覆盖一条或连续多条字幕。",
            "对没有重复风险的字幕，也要输出 single_clean_take cluster，保证 coverage 完整。",
            "如果一句话被拆成多条字幕但属于同一正式表达，可以作为一个 keep span。",
            "drop span 的 pause_after_ms 必须为 0，pause_type 为 none。",
            "keep span 默认 pause_after_ms 为 60，pause_type 为 normal。",
        ],
        "subtitles": subtitles,
    }
    if compact_drop_only:
        user["task"] = "对 115 条字幕做 take_cluster best_take 裁决 dry-run，但只输出存在 drop_take_ids 的重复/NG/自我修正 cluster。"
        user["compact_drop_only_rules"] = [
            "只输出 repeated_take/self_correction/ng_restart/semantic_duplicate 中需要删除至少一个候选 take 的 cluster。",
            "不要输出 single_clean_take。",
            "不要输出没有 drop_take_ids 的 cluster。",
            "不要输出 deepseek_aroll_decisions。",
            "Python 会把未出现在 cluster 中的字幕确定性补全为 single_clean_take keep，以避免输出过长。",
            "这一步只裁决核心重复 take，不要为了凑数输出不确定 drop。",
        ]
        user["output_schema"] = {
            "take_clusters": {
                "source": "subtitle_timeline",
                "subtitle_count": 115,
                "clusters": [
                    {
                        "cluster_id": "tc_001",
                        "intent_summary": "同一意图摘要",
                        "cluster_type": "repeated_take|self_correction|ng_restart|semantic_duplicate",
                        "candidates": [
                            {
                                "take_id": "tc_001_take_01",
                                "subtitle_start_uid": "sub_000006",
                                "subtitle_end_uid": "sub_000006",
                                "subtitle_start_index": 6,
                                "subtitle_end_index": 6,
                                "text": "候选 take 文本",
                                "quality_score": 72,
                                "quality_reasons": ["质量判断"],
                                "problems": ["问题"],
                            }
                        ],
                        "best_take_id": "tc_001_take_02",
                        "drop_take_ids": ["tc_001_take_01"],
                        "decision_reason": "为什么选择 best_take",
                    }
                ],
            }
        }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def build_payload(
    model: str,
    rows: list[dict[str, Any]],
    source_duration_us: int,
    response_format: bool,
    compact_drop_only: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 16000 if not compact_drop_only else 8192,
        "messages": build_prompt(rows, source_duration_us, compact_drop_only=compact_drop_only),
    }
    if response_format:
        payload["response_format"] = {"type": "json_object"}
    return payload


def make_single_clean_candidate(cluster_id: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "take_id": f"{cluster_id}_take_01",
        "subtitle_start_uid": row["subtitle_uid"],
        "subtitle_end_uid": row["subtitle_uid"],
        "subtitle_start_index": int(row["subtitle_index"]),
        "subtitle_end_index": int(row["subtitle_index"]),
        "text": clean_text(row.get("subtitle_text") or ""),
        "quality_score": 80,
        "quality_reasons": ["未被 DeepSeek 标记为重复/NG，默认保留以保证完整内容"],
        "problems": [],
    }


def decision_span_from_candidate(
    span_no: int,
    cluster_id: str,
    candidate: dict[str, Any],
    decision: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "span_id": f"sp_{span_no:03d}",
        "subtitle_start_uid": candidate["subtitle_start_uid"],
        "subtitle_end_uid": candidate["subtitle_end_uid"],
        "subtitle_start_index": int(candidate["subtitle_start_index"]),
        "subtitle_end_index": int(candidate["subtitle_end_index"]),
        "decision": decision,
        "cluster_id": cluster_id,
        "take_id": candidate["take_id"],
        "pause_after_ms": NORMAL_PAUSE_MS if decision == "keep" else 0,
        "pause_type": "normal" if decision == "keep" else "none",
        "mapped_text": candidate.get("text") or "",
        "reason": reason,
    }


def expand_compact_outputs(
    take_clusters: dict[str, Any],
    rows: list[dict[str, Any]],
    model: str,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    warnings = ["COMPACT_DROP_ONLY_USED", "SINGLE_CLEAN_TAKE_COMPLETED_BY_PYTHON"]
    rows_by_index = {int(row["subtitle_index"]): row for row in rows}
    clusters = take_clusters.get("clusters") or []
    if not isinstance(clusters, list):
        raise RuntimeError("take_clusters.clusters is not a list")

    used_indices: set[int] = set()
    for cluster in clusters:
        for candidate in cluster.get("candidates") or []:
            start = int(candidate.get("subtitle_start_index"))
            end = int(candidate.get("subtitle_end_index"))
            used_indices.update(range(start, end + 1))

    next_cluster_no = len(clusters) + 1
    for index in sorted(set(rows_by_index) - used_indices):
        cluster_id = f"tc_{next_cluster_no:03d}"
        next_cluster_no += 1
        candidate = make_single_clean_candidate(cluster_id, rows_by_index[index])
        clusters.append(
            {
                "cluster_id": cluster_id,
                "intent_summary": candidate["text"][:40],
                "cluster_type": "single_clean_take",
                "candidates": [candidate],
                "best_take_id": candidate["take_id"],
                "drop_take_ids": [],
                "decision_reason": "DeepSeek 未标记为重复/NG，Python 确定性补全为保留。",
            }
        )
    clusters.sort(
        key=lambda cluster: min(int(candidate.get("subtitle_start_index") or 0) for candidate in cluster.get("candidates") or [{"subtitle_start_index": 999999}])
    )
    take_clusters["clusters"] = clusters
    take_clusters["source"] = "subtitle_timeline"
    take_clusters["subtitle_count"] = len(rows)

    spans: list[dict[str, Any]] = []
    for cluster in clusters:
        cluster_id = str(cluster.get("cluster_id") or "")
        best_take_id = str(cluster.get("best_take_id") or "")
        drop_take_ids = set(str(item) for item in cluster.get("drop_take_ids") or [])
        for candidate in cluster.get("candidates") or []:
            take_id = str(candidate.get("take_id") or "")
            decision = "keep" if take_id == best_take_id else "drop" if take_id in drop_take_ids else "keep"
            reason = (
                "best take in repeated cluster"
                if decision == "keep" and drop_take_ids
                else "single clean take / preserve content"
                if decision == "keep"
                else "dropped duplicate / less clean take"
            )
            spans.append(decision_span_from_candidate(0, cluster_id, candidate, decision, reason))
    spans.sort(key=lambda item: (int(item["subtitle_start_index"]), int(item["subtitle_end_index"])))
    for index, span in enumerate(spans, start=1):
        span["span_id"] = f"sp_{index:03d}"
    decisions = {
        "source": "subtitle_timeline",
        "decision_mode": "real_deepseek_take_cluster_best_take_selection",
        "model": model,
        "spans": spans,
    }
    return take_clusters, decisions, warnings


def normalize_outputs(parsed: dict[str, Any], model: str) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    warnings: list[str] = []
    take_clusters = parsed.get("take_clusters") or parsed.get("clusters")
    decisions = parsed.get("deepseek_aroll_decisions") or parsed.get("decisions")
    if isinstance(take_clusters, list):
        take_clusters = {
            "source": "subtitle_timeline",
            "subtitle_count": 0,
            "clusters": take_clusters,
        }
        warnings.append("MODEL_RETURNED_CLUSTERS_ARRAY_WRAPPED")
    if isinstance(decisions, list):
        decisions = {
            "source": "subtitle_timeline",
            "decision_mode": "real_deepseek_take_cluster_best_take_selection",
            "model": model,
            "spans": decisions,
        }
        warnings.append("MODEL_RETURNED_SPANS_ARRAY_WRAPPED")
    if not isinstance(take_clusters, dict):
        raise RuntimeError("Missing take_clusters object")
    if not isinstance(decisions, dict):
        raise RuntimeError("Missing deepseek_aroll_decisions object")
    take_clusters.setdefault("source", "subtitle_timeline")
    decisions.setdefault("source", "subtitle_timeline")
    decisions["decision_mode"] = "real_deepseek_take_cluster_best_take_selection"
    decisions["model"] = model
    spans = decisions.get("spans")
    if not isinstance(spans, list):
        raise RuntimeError("deepseek_aroll_decisions.spans is not a list")
    spans.sort(key=lambda item: (int(item.get("subtitle_start_index") or 0), int(item.get("subtitle_end_index") or 0)))
    for index, span in enumerate(spans, start=1):
        span["span_id"] = span.get("span_id") or f"sp_{index:03d}"
        span["decision"] = str(span.get("decision") or "").lower().strip()
        if span["decision"] == "keep":
            span.setdefault("pause_after_ms", NORMAL_PAUSE_MS)
            span.setdefault("pause_type", "normal")
        elif span["decision"] == "drop":
            span["pause_after_ms"] = 0
            span["pause_type"] = "none"
    return take_clusters, decisions, warnings


def validate_clusters(take_clusters: dict[str, Any]) -> list[str]:
    fatal_reasons: list[str] = []
    clusters = take_clusters.get("clusters")
    if not isinstance(clusters, list):
        return ["TAKE_CLUSTERS_NOT_LIST"]
    seen_cluster_ids: set[str] = set()
    seen_take_ids: set[str] = set()
    for c_index, cluster in enumerate(clusters, start=1):
        cluster_id = str(cluster.get("cluster_id") or "")
        if not cluster_id:
            fatal_reasons.append(f"CLUSTER_MISSING_ID:{c_index}")
        if cluster_id in seen_cluster_ids:
            fatal_reasons.append(f"CLUSTER_DUPLICATE_ID:{cluster_id}")
        seen_cluster_ids.add(cluster_id)
        cluster_type = str(cluster.get("cluster_type") or "")
        if cluster_type not in ALLOWED_CLUSTER_TYPES:
            fatal_reasons.append(f"CLUSTER_INVALID_TYPE:{cluster_id}:{cluster_type}")
        candidates = cluster.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            fatal_reasons.append(f"CLUSTER_MISSING_CANDIDATES:{cluster_id}")
            continue
        candidate_ids = set()
        for t_index, candidate in enumerate(candidates, start=1):
            take_id = str(candidate.get("take_id") or "")
            if not take_id:
                fatal_reasons.append(f"TAKE_MISSING_ID:{cluster_id}:{t_index}")
            if take_id in seen_take_ids:
                fatal_reasons.append(f"TAKE_DUPLICATE_ID:{take_id}")
            seen_take_ids.add(take_id)
            candidate_ids.add(take_id)
            try:
                start = int(candidate.get("subtitle_start_index"))
                end = int(candidate.get("subtitle_end_index"))
                if start > end:
                    fatal_reasons.append(f"TAKE_REVERSED_INDEX:{take_id}")
            except Exception:
                fatal_reasons.append(f"TAKE_INVALID_INDEX:{take_id}")
        best_take_id = str(cluster.get("best_take_id") or "")
        if best_take_id not in candidate_ids:
            fatal_reasons.append(f"CLUSTER_BEST_TAKE_NOT_IN_CANDIDATES:{cluster_id}:{best_take_id}")
        for drop_take_id in cluster.get("drop_take_ids") or []:
            if str(drop_take_id) not in candidate_ids:
                fatal_reasons.append(f"CLUSTER_DROP_TAKE_NOT_IN_CANDIDATES:{cluster_id}:{drop_take_id}")
    return fatal_reasons


def validate_decision_fields(decisions: dict[str, Any]) -> list[str]:
    fatal_reasons: list[str] = []
    for span in decisions.get("spans") or []:
        span_id = span.get("span_id")
        decision = span.get("decision")
        if decision not in ALLOWED_DECISIONS:
            fatal_reasons.append(f"SPAN_INVALID_DECISION:{span_id}:{decision}")
        for forbidden in ("material_id", "track_id", "draft_content"):
            if forbidden in span:
                fatal_reasons.append(f"SPAN_FORBIDDEN_FIELD:{span_id}:{forbidden}")
    return fatal_reasons


def validate_take_span_consistency(take_clusters: dict[str, Any], decisions: dict[str, Any]) -> list[str]:
    take_decisions: dict[str, str] = {}
    for cluster in take_clusters.get("clusters") or []:
        best_take_id = str(cluster.get("best_take_id") or "")
        if best_take_id:
            take_decisions[best_take_id] = "keep"
        for drop_take_id in cluster.get("drop_take_ids") or []:
            take_decisions[str(drop_take_id)] = "drop"
    fatal_reasons: list[str] = []
    for span in decisions.get("spans") or []:
        take_id = str(span.get("take_id") or "")
        expected = take_decisions.get(take_id)
        if expected and expected != span.get("decision"):
            fatal_reasons.append(f"SPAN_TAKE_DECISION_CONFLICT:{span.get('span_id')}:{take_id}:{span.get('decision')}!={expected}")
    return fatal_reasons


def estimate_outputs(decisions: dict[str, Any], rows: list[dict[str, Any]], source_duration_us: int) -> dict[str, Any]:
    rows_by_index = {int(row["subtitle_index"]): row for row in rows}
    spans = decisions.get("spans") or []
    kept_duration = sum(estimate_span_duration_us(span, rows_by_index) for span in spans if span.get("decision") == "keep")
    dropped_duration = sum(estimate_span_duration_us(span, rows_by_index) for span in spans if span.get("decision") == "drop")
    final_with_guard = estimate_final_with_guard_us(spans, rows_by_index)
    drop_reasons = Counter(span.get("reason") or "" for span in spans if span.get("decision") == "drop").most_common()
    return {
        "estimated_original_duration_us": source_duration_us,
        "estimated_kept_duration_us": kept_duration,
        "estimated_dropped_duration_us": dropped_duration,
        "estimated_final_duration_us_with_guard": final_with_guard,
        "top_drop_reasons": [{"reason": reason, "count": count} for reason, count in drop_reasons],
    }


def build_human_review(take_clusters: dict[str, Any], decisions: dict[str, Any]) -> str:
    clusters_by_id = {cluster.get("cluster_id"): cluster for cluster in take_clusters.get("clusters") or []}
    candidates_by_take_id: dict[str, dict[str, Any]] = {}
    best_by_cluster: dict[str, dict[str, Any]] = {}
    for cluster in take_clusters.get("clusters") or []:
        for candidate in cluster.get("candidates") or []:
            candidates_by_take_id[candidate.get("take_id")] = candidate
            if candidate.get("take_id") == cluster.get("best_take_id"):
                best_by_cluster[cluster.get("cluster_id")] = candidate

    lines = ["# A-Roll Drop Review", ""]
    drop_no = 1
    for span in decisions.get("spans") or []:
        if span.get("decision") != "drop":
            continue
        cluster_id = span.get("cluster_id")
        cluster = clusters_by_id.get(cluster_id) or {}
        dropped = candidates_by_take_id.get(span.get("take_id")) or {}
        kept = best_by_cluster.get(cluster_id) or {}
        drop_score = int(dropped.get("quality_score") or 0)
        keep_score = int(kept.get("quality_score") or 0)
        diff = keep_score - drop_score
        confidence = "high" if diff >= 12 else "medium" if diff >= 5 else "low"
        lines.extend(
            [
                f"## Drop {drop_no:03d}",
                "",
                f"- Drop span: {span.get('subtitle_start_uid')} -> {span.get('subtitle_end_uid')}",
                f"- Drop text: {span.get('mapped_text') or dropped.get('text') or ''}",
                f"- Kept instead: {kept.get('subtitle_start_uid', '')} -> {kept.get('subtitle_end_uid', '')}",
                f"- Kept text: {kept.get('text', '')}",
                f"- Reason: {cluster.get('decision_reason') or span.get('reason') or ''}",
                f"- Confidence: {confidence}",
                "",
            ]
        )
        drop_no += 1
    if drop_no == 1:
        lines.append("No drop spans.")
    return "\n".join(lines).strip() + "\n"


def save_failure_report(
    run_dir: Path,
    rows: list[dict[str, Any]],
    source_duration_us: int,
    config: DeepSeekConfig,
    attempts: list[dict[str, Any]],
    fatal_reasons: list[str],
) -> Path:
    report = {
        "subtitle_count": len(rows),
        "model": attempts[-1].get("model") if attempts else None,
        "used_real_deepseek": bool(attempts),
        "fallback_used": len(attempts) > 1,
        "cluster_count": 0,
        "keep_span_count": 0,
        "drop_span_count": 0,
        "estimated_original_duration_us": source_duration_us,
        "estimated_kept_duration_us": 0,
        "estimated_dropped_duration_us": 0,
        "estimated_final_duration_us_with_guard": 0,
        "deepseek_config": {
            "base_url": config.base_url,
            "config_path": str(config.config_path).replace("\\", "/"),
            "api_key_loaded": bool(config.api_key),
        },
        "attempts": attempts,
        "top_drop_reasons": [],
        "validation": {
            "uid_index_valid": False,
            "no_overlap": False,
            "coverage_summary": "",
            "fatal_reasons": sorted(set(fatal_reasons)),
            "warnings": [],
        },
        "limitations": ["本轮 best_take 基于字幕文本和上下文，不包含真实音频清晰度评分。"],
    }
    report_path = run_dir / "aroll_decision_report.json"
    write_json(report_path, report)
    return report_path


def run_deepseek_decision(args: argparse.Namespace) -> tuple[Path, Path, Path, Path, Path]:
    run_dir = args.runtime / f"aroll_deepseek_decision_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    rows = sorted(read_json(args.subtitle_timeline), key=lambda item: int(item["subtitle_index"]))
    source_duration_us = load_source_duration_us(args.subtitle_timeline, rows)
    config = load_deepseek_config(args.deepseek_config)

    attempt_specs = [
        ("deepseek-reasoner", True, True),
        ("deepseek-chat", True, True),
        ("deepseek-reasoner", True, False),
        ("deepseek-chat", True, False),
        ("deepseek-chat", False, False),
    ]
    attempts: list[dict[str, Any]] = []
    last_error = ""
    parsed: dict[str, Any] | None = None
    selected_model = ""
    selected_response_format = False
    selected_compact_drop_only = False
    raw_records: list[dict[str, Any]] = []
    extra_warnings: list[str] = []

    for model, response_format, compact_drop_only in attempt_specs:
        attempt: dict[str, Any] = {
            "model": model,
            "response_format": response_format,
            "compact_drop_only": compact_drop_only,
            "success": False,
            "error": "",
        }
        try:
            payload = build_payload(model, rows, source_duration_us, response_format, compact_drop_only=compact_drop_only)
            response = post_chat_completions(config, payload, timeout_sec=args.timeout_sec)
            content, meta = extract_message_content(response)
            raw_records.append(
                {
                    "model": model,
                    "response_format": response_format,
                    "message_content": content,
                    "meta": meta,
                }
            )
            parsed_candidate = extract_json_object(content)
            if compact_drop_only:
                take_clusters_obj = parsed_candidate.get("take_clusters") or parsed_candidate.get("clusters")
                if isinstance(take_clusters_obj, list):
                    take_clusters_obj = {
                        "source": "subtitle_timeline",
                        "subtitle_count": len(rows),
                        "clusters": take_clusters_obj,
                    }
                if not isinstance(take_clusters_obj, dict):
                    raise RuntimeError("Missing take_clusters object in compact output")
                take_clusters, decisions, warnings = expand_compact_outputs(take_clusters_obj, rows, model)
            else:
                take_clusters, decisions, warnings = normalize_outputs(parsed_candidate, model)
            cluster_fatals = validate_clusters(take_clusters)
            decision_fatals = validate_decision_fields(decisions)
            validation = validate_spans(decisions.get("spans") or [], rows)
            consistency_fatals = validate_take_span_consistency(take_clusters, decisions)
            all_fatals = (
                cluster_fatals
                + decision_fatals
                + consistency_fatals
                + list(validation.get("fatal_reasons") or [])
            )
            if all_fatals:
                raise RuntimeError(";".join(all_fatals[:20]))
            parsed = {
                "take_clusters": take_clusters,
                "deepseek_aroll_decisions": decisions,
                "warnings": warnings + list(validation.get("warnings") or []),
                "validation": validation,
            }
            selected_model = model
            selected_response_format = response_format
            selected_compact_drop_only = compact_drop_only
            attempt["success"] = True
            attempts.append(attempt)
            break
        except Exception as exc:
            last_error = str(exc)
            attempt["error"] = last_error[:1200]
            attempts.append(attempt)
            continue

    raw_response_path = run_dir / "deepseek_raw_response.json"
    write_json(
        raw_response_path,
        {
            "config": {
                "base_url": config.base_url,
                "config_path": str(config.config_path).replace("\\", "/"),
                "api_key_loaded": bool(config.api_key),
            },
            "attempts": attempts,
            "responses": raw_records,
        },
    )

    if parsed is None:
        report_path = save_failure_report(
            run_dir=run_dir,
            rows=rows,
            source_duration_us=source_duration_us,
            config=config,
            attempts=attempts,
            fatal_reasons=[last_error or "DEEPSEEK_DECISION_FAILED"],
        )
        raise RuntimeError(f"DEEPSEEK_DECISION_FAILED:{last_error}; report={report_path}")

    take_clusters = parsed["take_clusters"]
    decisions = parsed["deepseek_aroll_decisions"]
    validation = parsed["validation"]
    extra_warnings = parsed["warnings"]
    estimates = estimate_outputs(decisions, rows, source_duration_us)
    cluster_count = len(take_clusters.get("clusters") or [])
    keep_count = sum(1 for span in decisions.get("spans") or [] if span.get("decision") == "keep")
    drop_count = sum(1 for span in decisions.get("spans") or [] if span.get("decision") == "drop")
    report = {
        "subtitle_count": len(rows),
        "model": selected_model,
        "used_real_deepseek": True,
        "fallback_used": selected_model != "deepseek-reasoner" or len(attempts) > 1,
        "response_format_used": selected_response_format,
        "compact_drop_only_used": selected_compact_drop_only,
        "deepseek_config": config.public_dict(selected_model, selected_response_format),
        "attempts": attempts,
        "cluster_count": cluster_count,
        "keep_span_count": keep_count,
        "drop_span_count": drop_count,
        **estimates,
        "validation": {
            **validation,
            "warnings": sorted(set(list(validation.get("warnings") or []) + extra_warnings)),
        },
        "limitations": ["本轮 best_take 基于字幕文本和上下文，不包含真实音频清晰度评分。"],
    }

    take_clusters_path = run_dir / "take_clusters.json"
    decisions_path = run_dir / "deepseek_aroll_decisions.json"
    report_path = run_dir / "aroll_decision_report.json"
    review_path = run_dir / "human_review_drops.md"
    write_json(take_clusters_path, take_clusters)
    write_json(decisions_path, decisions)
    write_json(report_path, report)
    review_path.write_text(build_human_review(take_clusters, decisions), "utf-8")
    return run_dir, raw_response_path, take_clusters_path, decisions_path, report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Real DeepSeek A-Roll take decision dry-run.")
    parser.add_argument("--subtitle-timeline", type=Path, default=DEFAULT_SUBTITLE_SOURCE)
    parser.add_argument("--deepseek-config", type=Path, default=Path(r"D:\idea-project\videoDataCatcher\src\main\resources\application.yaml"))
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--timeout-sec", type=int, default=240)
    args = parser.parse_args()

    run_dir, raw_path, clusters_path, decisions_path, report_path = run_deepseek_decision(args)
    report = read_json(report_path)
    print("status=ok" if not report["validation"]["fatal_reasons"] else "status=blocked")
    print(f"runtime={run_dir}")
    print(f"deepseek_raw_response={raw_path}")
    print(f"take_clusters={clusters_path}")
    print(f"decisions={decisions_path}")
    print(f"report={report_path}")
    print(f"model={report['model']}")
    print(f"fallback_used={report['fallback_used']}")
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
