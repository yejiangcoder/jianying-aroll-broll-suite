from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aroll_repeat_detector import repeated_prefix_cleanup_text
from aroll_text_normalize import compact_text


WEAK_PARTIAL_KEEP = {"就", "就是", "这个", "那个", "然后", "但", "但是", "所以", "啊", "呃", "嗯"}


def current_text_matches(expected: str, current: str) -> bool:
    expected_norm = compact_text(expected)
    current_norm = compact_text(current)
    if not expected_norm:
        return True
    return expected_norm == current_norm


def cluster_item_text_matches(cluster: dict[str, Any], index: int, current_text: str) -> bool:
    for item in cluster.get("items") or []:
        if int(item.get("subtitle_index") or 0) != index:
            continue
        return current_text_matches(str(item.get("text") or ""), current_text)
    return False


def meaningful_partial_keep(text: str) -> bool:
    norm = compact_text(text)
    if len(norm) < 3:
        return False
    if norm in WEAK_PARTIAL_KEEP:
        return False
    return True


def longest_common_substring(a: str, b: str) -> str:
    a = compact_text(a)
    b = compact_text(b)
    best = ""
    for start in range(len(a)):
        for end in range(start + 2, len(a) + 1):
            piece = a[start:end]
            if len(piece) <= len(best):
                continue
            if piece in b:
                best = piece
    return best


def self_repair_suffix(text: str) -> str:
    norm = compact_text(text)
    if len(norm) < 6:
        return ""
    max_seed = min(4, len(norm) // 2)
    for seed_len in range(max_seed, 1, -1):
        seed = norm[:seed_len]
        pos = norm.find(seed, 1)
        if pos <= 0:
            continue
        candidate = norm[pos:]
        if meaningful_partial_keep(candidate) and len(candidate) < len(norm):
            return candidate
    return ""


def partial_keep_text(drop_text: str, keep_text: str) -> str:
    drop_norm = compact_text(drop_text)
    keep_norm = compact_text(keep_text)
    if not drop_norm or not keep_norm:
        return ""

    common = longest_common_substring(drop_norm, keep_norm)
    if len(common) >= 2:
        pos = drop_norm.find(common)
        suffix = drop_norm[pos:]
        if suffix == keep_norm and meaningful_partial_keep(suffix):
            return suffix
        prefix = drop_norm[:pos]
        if meaningful_partial_keep(prefix):
            return prefix

    repaired = self_repair_suffix(drop_norm)
    if repaired:
        return repaired
    return ""


def read_json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def subtitle_index_by_uid(subtitles: list[dict[str, Any]]) -> dict[str, int]:
    return {str(row.get("subtitle_uid") or ""): int(row.get("subtitle_index") or 0) for row in subtitles}


def subtitle_text_by_index(subtitles: list[dict[str, Any]]) -> dict[int, str]:
    return {int(row.get("subtitle_index") or 0): str(row.get("subtitle_text") or "") for row in subtitles}


def load_v5_sources(v5_dir: Path | None) -> dict[str, Any]:
    sources: dict[str, Any] = {
        "system_cleanup_decisions": None,
        "candidate_decisions": None,
        "candidate_report": None,
        "searched_files": [],
    }
    if not v5_dir or not v5_dir.exists():
        return sources

    system_path = v5_dir / "system_cleanup_decisions.json"
    if system_path.exists():
        sources["system_cleanup_decisions"] = read_json(system_path)
        sources["searched_files"].append(str(system_path))

    best_report_path = v5_dir / "best_candidate_report.json"
    candidate_dir = None
    if best_report_path.exists():
        best = read_json(best_report_path)
        candidate_dir = Path(str(best.get("runtime_dir") or ""))
        sources["candidate_report"] = best
        sources["searched_files"].append(str(best_report_path))
    if not candidate_dir or not candidate_dir.exists():
        candidate_txt = v5_dir / "final_written_candidate.txt"
        if candidate_txt.exists():
            candidate_dir = v5_dir / candidate_txt.read_text("utf-8").strip()
    if candidate_dir and candidate_dir.exists():
        decisions_path = candidate_dir / "candidate_decisions.json"
        report_path = candidate_dir / "candidate_report.json"
        if decisions_path.exists():
            sources["candidate_decisions"] = read_json(decisions_path)
            sources["searched_files"].append(str(decisions_path))
        if report_path.exists() and sources["candidate_report"] is None:
            sources["candidate_report"] = read_json(report_path)
            sources["searched_files"].append(str(report_path))
    for pattern in [
        "*candidate_decisions*.json",
        "*reviewed*decisions*.json",
        "*corrective*v5*edl*.json",
        "*dropped_transcript_review*.md",
        "*residual_scan*.json",
    ]:
        sources["searched_files"].extend(str(path) for path in v5_dir.rglob(pattern))
    sources["searched_files"] = sorted(set(sources["searched_files"]))
    return sources


def merge_decisions(
    subtitles: list[dict[str, Any]],
    v5_dir: Path | None,
    repeat_clusters_path: Path,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    text_by_index = subtitle_text_by_index(subtitles)
    v5 = load_v5_sources(v5_dir)
    repeat_clusters = read_json(repeat_clusters_path)

    drop_by_index: dict[int, dict[str, Any]] = {}
    micro_by_index: dict[int, dict[str, Any]] = {}
    protected_keep_indices: set[int] = set()
    semantic_guard_blocks: list[dict[str, Any]] = []
    duplicate_conflict_resolutions: list[dict[str, Any]] = []
    partial_drop_conversions: list[dict[str, Any]] = []
    v5_drop_count = 0
    v5_micro_count = 0
    phase4_repeat_count = 0

    system = v5.get("system_cleanup_decisions") or {}
    for cleanup in system.get("micro_cleanups") or []:
        index = int(cleanup.get("subtitle_index") or 0)
        kept_text = str(cleanup.get("kept_text") or "")
        original_text = str(cleanup.get("original_text") or "")
        current_text = text_by_index.get(index, "")
        if index > 0 and kept_text and current_text_matches(original_text, current_text):
            micro_by_index[index] = {
                "subtitle_index": index,
                "subtitle_uid": cleanup.get("subtitle_uid"),
                "original_text": original_text or current_text,
                "kept_text": kept_text,
                "source": "v5_system_cleanup",
                "reason": cleanup.get("reason") or cleanup.get("cleanup_type") or "",
            }
            v5_micro_count += 1

    for span in system.get("drop_spans") or []:
        start = int(span.get("subtitle_start_index") or 0)
        end = int(span.get("subtitle_end_index") or start)
        keep_uid = str(span.get("keep_instead_uid") or "")
        keep_text = str(span.get("keep_instead_text") or "")
        if start <= 0 or end <= 0:
            continue
        drop_text = str(span.get("drop_text") or "")
        if start == end and not current_text_matches(drop_text, text_by_index.get(start, "")):
            semantic_guard_blocks.append({
                "subtitle_index": start,
                "blocked_source": "v5_drop_span",
                "reason": "stale v5 drop span text does not match current subtitle",
                "span": span,
                "current_text": text_by_index.get(start, ""),
            })
            continue
        if start == end and keep_uid == str(span.get("subtitle_start_uid") or "") and keep_text:
            micro_by_index[start] = {
                "subtitle_index": start,
                "subtitle_uid": span.get("subtitle_start_uid"),
                "original_text": drop_text or text_by_index.get(start, ""),
                "kept_text": keep_text,
                "source": "v5_drop_span_as_micro",
                "reason": span.get("reason") or span.get("reason_type") or "",
            }
            v5_micro_count += 1
            continue
        if start == end and keep_text:
            original_text = str(drop_text or text_by_index.get(start, ""))
            partial = partial_keep_text(original_text, keep_text)
            if partial:
                micro_by_index[start] = {
                    "subtitle_index": start,
                    "subtitle_uid": span.get("subtitle_start_uid"),
                    "original_text": original_text,
                    "kept_text": partial,
                    "source": "v5_partial_drop_as_micro",
                    "reason": span.get("reason") or span.get("reason_type") or "",
                }
                partial_drop_conversions.append({
                    "subtitle_index": start,
                    "subtitle_uid": span.get("subtitle_start_uid"),
                    "original_text": original_text,
                    "keep_instead_text": keep_text,
                    "partial_kept_text": partial,
                    "source": "v5_system_cleanup",
                    "reason": "convert unsafe full drop into partial micro cleanup",
                })
                v5_micro_count += 1
                continue
        try:
            keep_index = int(keep_uid.split("_")[-1]) if keep_uid else 0
        except Exception:
            keep_index = 0
        for index in range(start, end + 1):
            if keep_index == index:
                semantic_guard_blocks.append({
                    "subtitle_index": index,
                    "blocked_source": "v5_drop_span",
                    "reason": "keep_instead_uid is inside drop span; preserve kept subtitle",
                    "span": span,
                })
                continue
            if index in protected_keep_indices:
                semantic_guard_blocks.append({
                    "subtitle_index": index,
                    "blocked_source": "v5_drop_span",
                    "reason": "protected by user hard feedback / phase4 regression",
                    "span": span,
                })
                continue
            original_text = text_by_index.get(index, "")
            partial = partial_keep_text(original_text, keep_text)
            if partial:
                micro_by_index[index] = {
                    "subtitle_index": index,
                    "subtitle_uid": f"sub_{index:06d}",
                    "original_text": original_text,
                    "kept_text": partial,
                    "source": "v5_partial_drop_as_micro",
                    "reason": span.get("reason") or span.get("reason_type") or "",
                }
                partial_drop_conversions.append({
                    "subtitle_index": index,
                    "subtitle_uid": f"sub_{index:06d}",
                    "original_text": original_text,
                    "keep_instead_text": keep_text,
                    "partial_kept_text": partial,
                    "source": "v5_system_cleanup",
                    "reason": "convert unsafe multi-row drop into partial micro cleanup",
                })
                v5_micro_count += 1
                continue
            drop_by_index[index] = {
                "subtitle_index": index,
                "subtitle_uid": f"sub_{index:06d}",
                "drop_text": original_text,
                "keep_instead_text": keep_text,
                "source": "v5_system_cleanup",
                "reason": span.get("reason") or span.get("reason_type") or "",
            }
            v5_drop_count += 1

    for cluster in repeat_clusters:
        ctype = str(cluster.get("cluster_type") or "")
        action = str(cluster.get("suggested_action") or "")
        if ctype in {
            "pronoun_variant_duplicate",
            "near_duplicate",
            "exact_duplicate",
            "prefix_fragment",
            "weak_prefix_fragment",
            "dirty_expanded_fragment",
            "dirty_prefix_fragment",
        } and action in {"drop_left", "drop_right"}:
            for uid in cluster.get("suggested_drop_uids") or []:
                try:
                    index = int(str(uid).split("_")[-1])
                except Exception:
                    continue
                if not cluster_item_text_matches(cluster, index, text_by_index.get(index, "")):
                    semantic_guard_blocks.append({
                        "subtitle_index": index,
                        "blocked_source": "phase4_repeat_detector",
                        "reason": "stale repeat cluster text does not match current subtitle",
                        "cluster": cluster,
                        "current_text": text_by_index.get(index, ""),
                    })
                    continue
                if index in protected_keep_indices:
                    continue
                drop_by_index.setdefault(index, {
                    "subtitle_index": index,
                    "subtitle_uid": uid,
                    "drop_text": text_by_index.get(index, ""),
                    "keep_instead_text": "",
                    "source": "phase4_repeat_detector",
                    "reason": cluster.get("reason") or ctype,
                })
                phase4_repeat_count += 1
        elif ctype in {
            "same_subtitle_repeated_phrase",
            "same_subtitle_restart_fragment",
            "semantic_replacement_candidate",
            "boundary_overlap_cleanup",
        }:
            uid = str(cluster.get("suggested_keep_uid") or "")
            try:
                index = int(uid.split("_")[-1])
            except Exception:
                continue
            if not cluster_item_text_matches(cluster, index, text_by_index.get(index, "")):
                semantic_guard_blocks.append({
                    "subtitle_index": index,
                    "blocked_source": "phase4_repeat_detector",
                    "reason": "stale repeat cluster text does not match current subtitle",
                    "cluster": cluster,
                    "current_text": text_by_index.get(index, ""),
                })
                continue
            text = text_by_index.get(index, "")
            kept = str(cluster.get("micro_cleanup_text") or "") or repeated_prefix_cleanup_text(text)
            if kept and kept != text:
                micro_by_index[index] = {
                    "subtitle_index": index,
                    "subtitle_uid": uid,
                    "original_text": text,
                    "kept_text": kept,
                    "source": "phase4_repeat_detector",
                    "reason": cluster.get("reason") or ctype,
                }
                phase4_repeat_count += 1

    # Generic same-subtitle repeated prefix cleanups always win for the same row.
    for index, text in text_by_index.items():
        kept = repeated_prefix_cleanup_text(text)
        if kept and kept != text:
            micro_by_index[index] = {
                "subtitle_index": index,
                "subtitle_uid": f"sub_{index:06d}",
                "original_text": text,
                "kept_text": kept,
                "source": "generic_repeated_prefix_cleanup",
                "reason": "generic same-subtitle repeated prefix cleanup",
            }
    for index in list(micro_by_index):
        if index in drop_by_index:
            removed = drop_by_index.pop(index)
            duplicate_conflict_resolutions.append(
                {
                    "subtitle_index": index,
                    "restored_text": text_by_index.get(index, ""),
                    "micro_kept_text": micro_by_index[index].get("kept_text"),
                    "removed_drop_decision": removed,
                    "reason": "micro cleanup is safer than dropping a repairable subtitle",
                }
            )

    # Guard against cross-source conflicts: one source may choose to drop the
    # first occurrence of an exact duplicate while another source drops the
    # second. Without this, a complete repeated line can be deleted entirely.
    for cluster in repeat_clusters:
        if str(cluster.get("cluster_type") or "") != "exact_duplicate":
            continue
        items = cluster.get("items") or []
        item_indices: list[int] = []
        for item in items:
            try:
                item_indices.append(int(item.get("subtitle_index") or 0))
            except Exception:
                continue
        item_indices = [index for index in item_indices if index > 0]
        if len(item_indices) < 2:
            continue
        if not all(index in drop_by_index for index in item_indices):
            continue
        keep_uid = str(cluster.get("suggested_keep_uid") or "")
        try:
            restore_index = int(keep_uid.split("_")[-1]) if keep_uid else 0
        except Exception:
            restore_index = 0
        if restore_index not in item_indices:
            restore_index = max(item_indices)
        restored = drop_by_index.pop(restore_index, None)
        duplicate_conflict_resolutions.append(
            {
                "cluster_id": cluster.get("cluster_id"),
                "cluster_type": cluster.get("cluster_type"),
                "item_indices": item_indices,
                "restored_index": restore_index,
                "restored_text": text_by_index.get(restore_index, ""),
                "removed_drop_decision": restored,
                "reason": "prevent all occurrences of an exact duplicate group from being dropped",
            }
        )

    merged = {
        "source": "phase4c2_decision_merger",
        "v5_dir": str(v5_dir),
        "repeat_clusters": str(repeat_clusters_path),
        "drop_decisions": [drop_by_index[index] for index in sorted(drop_by_index)],
        "micro_cleanups": [micro_by_index[index] for index in sorted(micro_by_index)],
        "semantic_guard_blocks": semantic_guard_blocks,
        "duplicate_conflict_resolutions": duplicate_conflict_resolutions,
        "partial_drop_conversions": partial_drop_conversions,
        "summary": {
            "inherited_v5_drop_count": v5_drop_count,
            "inherited_v5_micro_cleanup_count": v5_micro_count,
            "phase4_repeat_decision_count": phase4_repeat_count,
            "semantic_guard_block_count": len(semantic_guard_blocks),
            "duplicate_conflict_resolution_count": len(duplicate_conflict_resolutions),
            "partial_drop_conversion_count": len(partial_drop_conversions),
            "final_drop_count": len(drop_by_index),
            "final_micro_cleanup_count": len(micro_by_index),
            "searched_v5_files": v5["searched_files"],
        },
    }
    report_lines = [
        "# Phase 4C-2 Decision Merge Report",
        "",
        f"- Phase 4C 是否漏继承 v5 决策：是。上一版 word-level PoC 未完整继承 v5 drop/micro decisions。",
        f"- 本轮继承 v5 drop：{v5_drop_count}",
        f"- 本轮继承 v5 micro cleanup：{v5_micro_count}",
        f"- 本轮新增 Phase 4 repeat decisions：{phase4_repeat_count}",
        f"- semantic guard 拦截：{len(semantic_guard_blocks)}",
        f"- duplicate conflict 恢复：{len(duplicate_conflict_resolutions)}",
        f"- partial drop 转 micro cleanup：{len(partial_drop_conversions)}",
        f"- 最终 drop：{len(drop_by_index)}",
        f"- 最终 micro cleanup：{len(micro_by_index)}",
        "",
        "## Duplicate Conflict Resolutions",
    ]
    for row in duplicate_conflict_resolutions:
        report_lines.append(
            f"- {row.get('cluster_id')}: restore sub_{int(row.get('restored_index') or 0):06d} "
            f"{row.get('restored_text')} | {row.get('reason')}"
        )
    report_lines.extend([
        "",
        "## Partial Drop Conversions",
    ])
    for row in partial_drop_conversions:
        report_lines.append(
            f"- sub_{int(row.get('subtitle_index') or 0):06d}: "
            f"{row.get('original_text')} -> {row.get('partial_kept_text')} | "
            f"keep_instead={row.get('keep_instead_text')}"
        )
    report_lines.extend([
        "",
        "## Final Drops",
    ])
    for row in merged["drop_decisions"]:
        report_lines.append(f"- sub_{int(row['subtitle_index']):06d}: {row.get('drop_text')} | source={row.get('source')} | reason={row.get('reason')}")
    report_lines.extend(["", "## Final Micro Cleanups"])
    for row in merged["micro_cleanups"]:
        report_lines.append(f"- sub_{int(row['subtitle_index']):06d}: {row.get('original_text')} -> {row.get('kept_text')} | source={row.get('source')}")
    return merged, "\n".join(report_lines) + "\n", merged["summary"]


def decision_maps(merged: dict[str, Any]) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    drops = {int(row["subtitle_index"]): row for row in merged.get("drop_decisions") or []}
    micros = {int(row["subtitle_index"]): row for row in merged.get("micro_cleanups") or []}
    return drops, micros
