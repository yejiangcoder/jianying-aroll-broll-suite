from __future__ import annotations

from typing import Any

from aroll_script_reference_matcher import load_script_text, match_script_reference
from aroll_text_normalize import normalize_text


LLM_TYPES = {
    "drop_span",
    "micro_cleanup",
    "duplicate_take",
    "possible_missing",
    "semantic_overlap",
    "dirty_stutter",
}


def _fragment_text(row: dict[str, Any]) -> str:
    return str(row.get("fragment_text") or row.get("text") or row.get("subtitle_text") or "")


def _source_by_index(source_subtitles: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(row.get("subtitle_index") or 0): row for row in source_subtitles if int(row.get("subtitle_index") or 0) > 0}


def _context_by_index(source_subtitles: list[dict[str, Any]], indices: list[int], radius: int = 2) -> list[dict[str, Any]]:
    if not indices:
        return []
    by_index = _source_by_index(source_subtitles)
    lo = max(1, min(indices) - radius)
    hi = max(indices) + radius
    out = []
    for idx in range(lo, hi + 1):
        row = by_index.get(idx)
        if row:
            out.append({"subtitle_index": idx, "text": row.get("subtitle_text"), "start_us": row.get("start_us")})
    return out


def _nearby_final(final_plan: list[dict[str, Any]], source_start_us: int, radius: int = 3) -> list[dict[str, Any]]:
    if not final_plan:
        return []
    ordered = sorted(final_plan, key=lambda row: int(row.get("source_start_us") or 0))
    best_i = 0
    best_d = 10**18
    for i, row in enumerate(ordered):
        d = abs(int(row.get("source_start_us") or 0) - source_start_us)
        if d < best_d:
            best_d = d
            best_i = i
    out = []
    for row in ordered[max(0, best_i - radius) : min(len(ordered), best_i + radius + 1)]:
        out.append(
            {
                "text": _fragment_text(row),
                "source_start_us": row.get("source_start_us"),
                "source_end_us": row.get("source_end_us"),
                "target_start_us": row.get("target_start_us"),
            }
        )
    return out


def _source_text(source_subtitles: list[dict[str, Any]], indices: list[int]) -> str:
    by_index = _source_by_index(source_subtitles)
    return " ".join(str((by_index.get(idx) or {}).get("subtitle_text") or "") for idx in indices).strip()


def _source_start(source_subtitles: list[dict[str, Any]], indices: list[int]) -> int:
    by_index = _source_by_index(source_subtitles)
    starts = [int((by_index.get(idx) or {}).get("start_us") or 0) for idx in indices if by_index.get(idx)]
    return min(starts) if starts else 0


def _source_end(source_subtitles: list[dict[str, Any]], indices: list[int]) -> int:
    by_index = _source_by_index(source_subtitles)
    ends = [int((by_index.get(idx) or {}).get("end_us") or 0) for idx in indices if by_index.get(idx)]
    return max(ends) if ends else 0


def _source_ranges(source_subtitles: list[dict[str, Any]], indices: list[int]) -> list[dict[str, Any]]:
    by_index = _source_by_index(source_subtitles)
    ranges: list[dict[str, int]] = []
    for idx in indices:
        row = by_index.get(idx)
        if not row:
            continue
        start = int(row.get("start_us") or 0)
        end = int(row.get("end_us") or 0)
        if end > start:
            ranges.append(
                {
                    "subtitle_index": idx,
                    "subtitle_uid": row.get("subtitle_uid"),
                    "text": row.get("subtitle_text"),
                    "start_us": start,
                    "end_us": end,
                }
            )
    return ranges


def _final_matches(final_plan: list[dict[str, Any]], source_text: str) -> list[dict[str, Any]]:
    source_norm = normalize_text(source_text)
    if not source_norm:
        return []
    matches: list[dict[str, Any]] = []
    for row in final_plan:
        text = _fragment_text(row)
        norm = normalize_text(text)
        if source_norm in norm or norm in source_norm:
            matches.append({"text": text, "source_start_us": row.get("source_start_us"), "target_start_us": row.get("target_start_us")})
    return matches[:5]


def _candidate_key(candidate_type: str, indices: list[int], text: str) -> str:
    return candidate_type + "|" + ",".join(str(i) for i in indices) + "|" + normalize_text(text)[:80]


def build_candidate(
    *,
    seq: int,
    candidate_type: str,
    source_subtitles: list[dict[str, Any]],
    final_plan: list[dict[str, Any]],
    source_subtitle_indices: list[int],
    source_text: str,
    proposed_action: str,
    risk_level: str,
    python_reason: str,
    python_guess: str,
    python_confidence: str,
    script_text: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    indices = [int(x) for x in source_subtitle_indices if int(x) > 0]
    start = _source_start(source_subtitles, indices)
    end = _source_end(source_subtitles, indices)
    source_ranges = _source_ranges(source_subtitles, indices)
    script_ref = match_script_reference(source_text, script_text)
    candidate_type = candidate_type or "drop_span"
    return {
        "candidate_id": f"cand_{seq:04d}",
        "unit_id": f"cand_{seq:04d}",
        "candidate_type": candidate_type,
        "source_subtitle_indices": indices,
        "source_text": source_text,
        "normalized_text": normalize_text(source_text),
        "source_start_us": start,
        "source_end_us": end,
        "source_subtitle_ranges": source_ranges,
        "proposed_action": proposed_action,
        "requires_llm": candidate_type in LLM_TYPES,
        "risk_level": risk_level,
        "python_reason": python_reason,
        "candidate_reason": python_reason,
        "python_guess": python_guess,
        "python_confidence": python_confidence,
        "nearby_source_context": _context_by_index(source_subtitles, indices),
        "source_context_before": _context_by_index(source_subtitles, indices)[:2],
        "source_context_after": _context_by_index(source_subtitles, indices)[-2:],
        "nearby_final_context": _nearby_final(final_plan, start),
        "final_context_nearby": _nearby_final(final_plan, start),
        "candidate_final_matches": _final_matches(final_plan, source_text),
        **script_ref,
        **(extra or {}),
    }


def discover_aroll_candidates(
    *,
    source_subtitles: list[dict[str, Any]],
    final_plan: list[dict[str, Any]],
    repeat_clusters: list[dict[str, Any]],
    merged: dict[str, Any],
    duplicate_family_report: dict[str, Any] | None = None,
    semantic_coverage_report: dict[str, Any] | None = None,
    semantic_overlap_report: dict[str, Any] | None = None,
    residual_repeat_audit: dict[str, Any] | None = None,
    script_path: Any = None,
    max_candidates: int = 120,
) -> list[dict[str, Any]]:
    script_text = load_script_text(script_path)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(candidate_type: str, indices: list[int], text: str, action: str, reason: str, guess: str, confidence: str, risk: str = "high", extra: dict[str, Any] | None = None) -> None:
        if not text.strip() and indices:
            text_value = _source_text(source_subtitles, indices)
        else:
            text_value = text.strip()
        key = _candidate_key(candidate_type, indices, text_value)
        if key in seen or not text_value:
            return
        seen.add(key)
        candidates.append(
            build_candidate(
                seq=len(candidates) + 1,
                candidate_type=candidate_type,
                source_subtitles=source_subtitles,
                final_plan=final_plan,
                source_subtitle_indices=indices,
                source_text=text_value,
                proposed_action=action,
                risk_level=risk,
                python_reason=reason,
                python_guess=guess,
                python_confidence=confidence,
                script_text=script_text,
                extra=extra,
            )
        )

    for row in merged.get("drop_decisions") or []:
        idx = int(row.get("subtitle_index") or 0)
        add("drop_span", [idx], str(row.get("drop_text") or ""), "drop", str(row.get("reason") or row.get("source") or ""), "drop", "medium")

    for row in merged.get("micro_cleanups") or []:
        idx = int(row.get("subtitle_index") or 0)
        add(
            "micro_cleanup",
            [idx],
            str(row.get("original_text") or ""),
            "micro_cleanup",
            str(row.get("reason") or row.get("source") or ""),
            "micro_cleanup",
            "medium",
            extra={"proposed_final_text": str(row.get("kept_text") or "")},
        )

    for cluster in repeat_clusters:
        indices = [int(x) for x in cluster.get("window_indices") or [] if int(x) > 0]
        if not indices:
            indices = sorted(
                {
                    int(index)
                    for candidate in (cluster.get("candidates") or [])
                    for index in (candidate.get("subtitle_indices") or [])
                    if int(index) > 0
                }
            )
        text = " ".join(str(item.get("text") or "") for item in cluster.get("items") or [])
        action = str(cluster.get("suggested_action") or "")
        proposed = action if action in {"drop_left", "drop_right", "keep_both"} else "micro_cleanup" if action == "micro_cleanup" else "self_review"
        add(
            "dirty_stutter" if "repeat" in str(cluster.get("cluster_type") or "") or "fragment" in str(cluster.get("cluster_type") or "") else "duplicate_take",
            indices,
            text,
            proposed,
            str(cluster.get("reason") or cluster.get("cluster_type") or ""),
            str(cluster.get("cluster_type") or ""),
            str(cluster.get("confidence") or "medium"),
            risk="medium",
            extra={
                "repeat_cluster": cluster,
                "source_subtitle_indices_from_take_cluster": bool(cluster.get("source") == "take_clusterer" and indices),
                "suggested_keep_uid": cluster.get("suggested_keep_uid"),
                "suggested_drop_uids": cluster.get("suggested_drop_uids") or [],
            },
        )

    for family in (duplicate_family_report or {}).get("families") or []:
        for candidate in family.get("candidates") or []:
            indices = [int(x) for x in candidate.get("subtitle_indices") or [] if int(x) > 0]
            add(
                "duplicate_take",
                indices,
                str(candidate.get("text") or ""),
                "self_review",
                f"duplicate family {family.get('family_id')}",
                "keep_one_complete_take",
                "medium",
                extra={"duplicate_family_id": family.get("family_id"), "duplicate_take_id": candidate.get("take_id")},
            )

    for unit in (semantic_coverage_report or {}).get("missing_required_units") or []:
        add("possible_missing", [int(x) for x in unit.get("subtitle_indices") or []], str(unit.get("source_text") or ""), "keep", "coverage possible missing", "true_missing_required_unit", "medium", risk="high", extra={"coverage": unit.get("coverage") or {}})
    for unit in (semantic_coverage_report or {}).get("filtered_dirty_units") or []:
        add("dirty_stutter", [int(x) for x in unit.get("subtitle_indices") or []], str(unit.get("source_text") or ""), "drop", str(unit.get("filtered_reason") or "dirty candidate"), "dirty_stutter_unit", "medium", risk="medium", extra={"coverage": unit.get("equivalent_coverage") or {}})

    for issue in (semantic_overlap_report or {}).get("issues") or []:
        ids = [int(x) for x in issue.get("source_subtitle_indices") or [] if str(x).isdigit()]
        text = str(issue.get("left_text") or issue.get("right_text") or "")
        add("semantic_overlap", ids, text, str(issue.get("new_action") or "self_review"), str(issue.get("reason") or "semantic overlap"), "semantic_overlap", "medium", risk="high", extra={"issue": issue})

    for issue in (residual_repeat_audit or {}).get("issues") or []:
        ids = [int(x) for x in issue.get("source_subtitle_indices") or [] if str(x).isdigit()]
        text = str(issue.get("left_text") or issue.get("right_text") or "")
        add("semantic_overlap", ids, text, "drop", str(issue.get("reason") or "residual repeat"), "duplicate_take_covered", "medium", risk="high", extra={"issue": issue})

    return candidates[:max_candidates]


def discover_semantic_suspicious_units(
    source_subtitles: list[dict[str, Any]],
    final_plan: list[dict[str, Any]],
    semantic_coverage_report: dict[str, Any],
    *,
    max_units: int = 60,
) -> list[dict[str, Any]]:
    return discover_aroll_candidates(
        source_subtitles=source_subtitles,
        final_plan=final_plan,
        repeat_clusters=[],
        merged={"drop_decisions": [], "micro_cleanups": []},
        semantic_coverage_report=semantic_coverage_report,
        max_candidates=max_units,
    )
