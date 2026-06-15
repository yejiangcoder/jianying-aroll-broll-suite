from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from aroll_candidate_discovery import discover_semantic_suspicious_units
from aroll_decision_plan_builder import build_aroll_decision_plan
from aroll_intra_segment_breath_cutter import rebase_subtitle_plan
from aroll_semantic_coverage_gate import build_semantic_coverage_report
from aroll_semantic_llm_arbiter import arbitrate_suspicious_units

NONBLOCKING_LLM_CLASSES = {
    "required_clean_unit_covered",
    "dirty_stutter_unit",
    "duplicate_take_covered",
    "micro_cleanup_covered",
    "not_required_filler",
}

BLOCKING_LLM_CLASSES = {"true_missing_required_unit", "manual_review"}
MIN_REPAIR_KEEP_PART_US = 500_000
DIRTY_CANDIDATE_MARKERS = (
    "possible_dirty_stutter",
    "same_phrase_repeated",
    "prefix_fragment",
    "unfinished",
    "restart",
    "damaged",
    "dirty",
    "micro_cleanup_covered",
    "dirty_stutter",
    "stutter",
)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _subtitle_text(row: dict[str, Any]) -> str:
    return str(row.get("subtitle_text") or row.get("fragment_text") or row.get("text") or "")


def _looks_like_dirty_manual_review(arbiter: dict[str, Any]) -> bool:
    if str(arbiter.get("classification") or "") != "manual_review":
        return False
    text = " ".join(
        str(value or "")
        for value in [
            arbiter.get("candidate_reason"),
            arbiter.get("drop_reason_from_decision"),
            arbiter.get("reason"),
        ]
    ).lower()
    return any(marker in text for marker in DIRTY_CANDIDATE_MARKERS)


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return min(a_end, b_end) > max(a_start, b_start)


def _rebase_edl(clips: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    target = 0
    for i, clip in enumerate(sorted(clips, key=lambda row: (int(row.get("source_start_us") or 0), int(row.get("source_end_us") or 0))), start=1):
        cloned = deepcopy(clip)
        start = int(cloned.get("source_start_us") or cloned.get("cut_start_us") or 0)
        end = int(cloned.get("source_end_us") or cloned.get("cut_end_us") or start)
        if end <= start:
            continue
        duration = end - start
        cloned["clip_id"] = str(cloned.get("clip_id") or f"repair_clip_{i:04d}")
        cloned["source_start_us"] = start
        cloned["source_end_us"] = end
        cloned["cut_start_us"] = start
        cloned["cut_end_us"] = end
        cloned["source_timeline_start_us"] = start
        cloned["source_timeline_end_us"] = end
        cloned["target_start_us"] = target
        cloned["target_duration_us"] = duration
        cloned["final_target_start_us"] = target
        cloned["final_target_duration_us"] = duration
        cloned["final_target_end_us"] = target + duration
        out.append(cloned)
        target += duration
    return out


def _source_rows_for_indices(subtitles: list[dict[str, Any]], indices: set[int]) -> list[dict[str, Any]]:
    rows = []
    for row in sorted(subtitles, key=lambda item: int(item.get("subtitle_index") or 0)):
        if int(row.get("subtitle_index") or 0) in indices:
            rows.append(row)
    return rows


def _repair_clip_for_subtitle(row: dict[str, Any], repair_id: int) -> dict[str, Any]:
    start = int(row.get("start_us") or row.get("source_start_us") or 0)
    end = int(row.get("end_us") or (start + int(row.get("duration_us") or 0)))
    return {
        "clip_id": f"semantic_repair_{repair_id:04d}",
        "fragment_id": f"semantic_repair_{repair_id:04d}",
        "source_start_us": start,
        "source_end_us": end,
        "cut_start_us": start,
        "cut_end_us": end,
        "target_start_us": 0,
        "target_duration_us": end - start,
        "source_reason": "force_keep_by_semantic_repair",
        "subtitle_texts": [_subtitle_text(row)],
    }


def _repair_subtitle_for_source(row: dict[str, Any], repair_id: int) -> dict[str, Any]:
    start = int(row.get("start_us") or 0)
    end = int(row.get("end_us") or (start + int(row.get("duration_us") or 0)))
    text = _subtitle_text(row)
    return {
        "fragment_id": f"semantic_repair_sub_{repair_id:04d}",
        "fragment_text": text,
        "text": text,
        "source_subtitle_indices": [int(row.get("subtitle_index") or 0)],
        "source_subtitle_uids": [str(row.get("subtitle_uid") or "")],
        "source_start_us": start,
        "source_end_us": end,
        "target_start_us": 0,
        "target_duration_us": end - start,
        "reason": "force_keep_by_semantic_repair",
        "word_ids": [],
    }


def _subtract_intervals(start: int, end: int, intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    parts = [(start, end)]
    for rs, re in sorted(intervals):
        next_parts: list[tuple[int, int]] = []
        for ps, pe in parts:
            if not _overlaps(ps, pe, rs, re):
                next_parts.append((ps, pe))
                continue
            if ps < rs:
                next_parts.append((ps, min(pe, rs)))
            if re < pe:
                next_parts.append((max(ps, re), pe))
        parts = [(ps, pe) for ps, pe in next_parts if pe > ps]
    return [(ps, pe) for ps, pe in parts if pe - ps >= MIN_REPAIR_KEEP_PART_US]


def _clip_part(clip: dict[str, Any], start: int, end: int, suffix: int) -> dict[str, Any]:
    cloned = deepcopy(clip)
    cloned["clip_id"] = f"{cloned.get('clip_id') or 'clip'}_repair_keep_{suffix:03d}"
    cloned["source_start_us"] = start
    cloned["source_end_us"] = end
    cloned["cut_start_us"] = start
    cloned["cut_end_us"] = end
    cloned["source_timeline_start_us"] = start
    cloned["source_timeline_end_us"] = end
    cloned["target_duration_us"] = end - start
    cloned["final_target_duration_us"] = end - start
    return cloned


def apply_force_keep_repairs(
    edl: list[dict[str, Any]],
    subtitle_plan: list[dict[str, Any]],
    source_subtitles: list[dict[str, Any]],
    force_keep_indices: set[int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not force_keep_indices:
        return edl, subtitle_plan, []
    source_rows = _source_rows_for_indices(source_subtitles, force_keep_indices)
    repair_intervals = [
        (int(row.get("start_us") or 0), int(row.get("end_us") or (int(row.get("start_us") or 0) + int(row.get("duration_us") or 0))))
        for row in source_rows
    ]
    kept_clips = []
    part_id = 1
    for clip in edl:
        cs = int(clip.get("source_start_us") or 0)
        ce = int(clip.get("source_end_us") or cs)
        parts = _subtract_intervals(cs, ce, repair_intervals)
        for ps, pe in parts:
            if ps == cs and pe == ce:
                kept_clips.append(clip)
            else:
                kept_clips.append(_clip_part(clip, ps, pe, part_id))
                part_id += 1
    kept_subs = []
    for sub in subtitle_plan:
        sub_indices = {int(index) for index in sub.get("source_subtitle_indices") or [] if int(index) > 0}
        if sub_indices and not (sub_indices & force_keep_indices):
            kept_subs.append(sub)
            continue
        if sub_indices and (sub_indices & force_keep_indices):
            continue
        ss = int(sub.get("source_start_us") or 0)
        se = int(sub.get("source_end_us") or ss)
        if any(_overlaps(ss, se, rs, re) for rs, re in repair_intervals):
            continue
        kept_subs.append(sub)
    repair_actions: list[dict[str, Any]] = []
    repair_clips = []
    repair_subs = []
    for i, row in enumerate(source_rows, start=1):
        repair_clips.append(_repair_clip_for_subtitle(row, i))
        repair_subs.append(_repair_subtitle_for_source(row, i))
        repair_actions.append(
            {
                "subtitle_index": int(row.get("subtitle_index") or 0),
                "source_text": _subtitle_text(row),
                "start_us": int(row.get("start_us") or 0),
                "end_us": int(row.get("end_us") or 0),
                "action": "force_keep_by_semantic_repair",
            }
        )
    repaired_edl = _rebase_edl(kept_clips + repair_clips)
    repaired_subtitles = rebase_subtitle_plan(kept_subs + repair_subs, repaired_edl)
    return repaired_edl, repaired_subtitles, repair_actions


def apply_llm_coverage_overrides(
    coverage: dict[str, Any],
    results: list[dict[str, Any]],
    repair_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Let the semantic arbiter suppress local false positives after repair.

    The old Python coverage gate is intentionally conservative and tends to
    mark dirty ASR/stutter text as "missing". The LLM arbiter decides whether a
    suspicious unit is a real missing semantic unit or a safe cleanup.
    """
    if not results:
        coverage["llm_arbiter_used"] = False
        coverage["llm_nonblocking_unit_count"] = 0
        coverage["llm_true_missing_required_count"] = 0
        coverage["llm_manual_review_count"] = 0
        coverage["conservative_kept_units"] = repair_actions
        return coverage

    by_id = {str(row.get("unit_id") or ""): row for row in results if row.get("unit_id")}
    remaining_missing: list[dict[str, Any]] = []
    llm_nonblocking: list[dict[str, Any]] = []
    llm_blocking: list[dict[str, Any]] = []
    for unit in coverage.get("missing_required_units") or []:
        unit_id = str(unit.get("unit_id") or "")
        arbiter = by_id.get(unit_id)
        if not arbiter:
            remaining_missing.append(unit)
            continue
        classification = str(arbiter.get("classification") or "")
        enriched = unit | {"llm_arbiter": arbiter}
        if classification in NONBLOCKING_LLM_CLASSES or _looks_like_dirty_manual_review(arbiter):
            llm_nonblocking.append(enriched)
            continue
        if classification in BLOCKING_LLM_CLASSES:
            llm_blocking.append(enriched)
            remaining_missing.append(enriched)
            continue
        remaining_missing.append(enriched)

    covered_units = list(coverage.get("covered_units") or [])
    dirty_units = list(coverage.get("filtered_dirty_units") or [])
    for unit in llm_nonblocking:
        arbiter = unit.get("llm_arbiter") or {}
        classification = str(arbiter.get("classification") or "")
        if classification in {"dirty_stutter_unit", "duplicate_take_covered", "micro_cleanup_covered", "not_required_filler"}:
            dirty_units.append(unit | {"filtered_reason": f"llm_{classification}"})
        else:
            covered_units.append(unit | {"coverage": unit.get("coverage") or {}, "covered_by": "llm_arbiter"})

    fatal_reasons = [str(x) for x in coverage.get("fatal_reasons") or [] if x != "SEMANTIC_COVERAGE_MISSING_REQUIRED_UNITS"]
    if remaining_missing:
        fatal_reasons.append("SEMANTIC_COVERAGE_MISSING_REQUIRED_UNITS")

    true_missing_count = sum(1 for row in results if row.get("classification") == "true_missing_required_unit")
    manual_review_count = sum(1 for row in results if row.get("classification") == "manual_review")
    coverage.update(
        {
            "llm_arbiter_used": True,
            "llm_nonblocking_unit_count": len(llm_nonblocking),
            "llm_nonblocking_units": llm_nonblocking,
            "llm_blocking_units": llm_blocking,
            "llm_true_missing_required_count": true_missing_count,
            "llm_manual_review_count": manual_review_count,
            "conservative_kept_units": repair_actions,
            "missing_required_units": remaining_missing,
            "missing_required_unit_count": len(remaining_missing),
            "covered_units": covered_units,
            "covered_unit_count": len(covered_units),
            "covered_required_unit_count": len(covered_units),
            "filtered_dirty_units": dirty_units,
            "dirty_unit_filtered_count": len(dirty_units),
            "filtered_dirty_unit_count": len(dirty_units),
            "coverage_false_positive_prevented_count": int(coverage.get("coverage_false_positive_prevented_count") or 0)
            + len(llm_nonblocking),
            "fatal_reasons": sorted(set(fatal_reasons)),
        }
    )
    return coverage


def run_semantic_repair_loop(
    *,
    source_subtitles: list[dict[str, Any]],
    initial_edl: list[dict[str, Any]],
    initial_subtitle_plan: list[dict[str, Any]],
    merged: dict[str, Any],
    duplicate_family_report: dict[str, Any],
    script_path: Path | None,
    run_dir: Path,
    max_iterations: int = 3,
    model: str = "deepseek-chat",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    current_edl = initial_edl
    current_subtitles = initial_subtitle_plan
    all_results: list[dict[str, Any]] = []
    all_requests: list[dict[str, Any]] = []
    repair_actions: list[dict[str, Any]] = []
    initial_true_missing = 0
    initial_manual_review = 0
    llm_call_count = 0
    llm_summary: dict[str, Any] = {"llm_used": False, "model": model, "call_count": 0}
    final_coverage: dict[str, Any] = {}
    final_md = ""
    for iteration in range(1, max_iterations + 1):
        iter_dir = run_dir / f"semantic_repair_iter_{iteration:02d}"
        coverage, md = build_semantic_coverage_report(source_subtitles, current_subtitles, merged, duplicate_family_report, script_path)
        write_json(iter_dir / "semantic_coverage_report.json", coverage)
        (iter_dir / "semantic_coverage_review.md").write_text(md, "utf-8")
        final_coverage = coverage
        final_md = md
        if int(coverage.get("missing_required_unit_count") or 0) == 0:
            break
        suspicious = discover_semantic_suspicious_units(source_subtitles, current_subtitles, coverage)
        write_json(iter_dir / "semantic_suspicious_units.json", suspicious)
        if iteration == 1:
            write_json(run_dir / "semantic_suspicious_units.json", suspicious)
        results, summary = arbitrate_suspicious_units(suspicious, iter_dir, model=model)
        llm_summary = summary
        llm_call_count += int(summary.get("call_count") or 0)
        all_results.extend(results)
        all_requests.extend(suspicious)
        if iteration == 1:
            initial_true_missing = int(summary.get("true_missing_required_count") or 0)
            initial_manual_review = int(summary.get("manual_review_count") or 0)
        plan = build_aroll_decision_plan(suspicious, results, iter_dir)
        force_indices = set(int(x) for x in plan.get("force_keep_subtitle_indices") or [])
        if not force_indices:
            break
        current_edl, current_subtitles, actions = apply_force_keep_repairs(current_edl, current_subtitles, source_subtitles, force_indices)
        repair_actions.extend(actions)
        write_json(iter_dir / "repaired_video_edl.json", current_edl)
        write_json(iter_dir / "repaired_display_subtitle_plan.json", current_subtitles)

    tail_repair_actions: list[dict[str, Any]] = []
    tail_repair_rounds = 0
    final_coverage, final_md = build_semantic_coverage_report(source_subtitles, current_subtitles, merged, duplicate_family_report, script_path)
    final_coverage = apply_llm_coverage_overrides(final_coverage, all_results, repair_actions)
    while True:
        tail_missing = final_coverage.get("missing_required_units") or []
        if not (0 < len(tail_missing) <= 5) or tail_repair_rounds >= 10:
            break
        tail_force_indices = {
            int(index)
            for unit in tail_missing
            for index in (unit.get("subtitle_indices") or unit.get("source_subtitle_indices") or [])
            if int(index) > 0
        }
        if not tail_force_indices:
            break
        current_edl, current_subtitles, actions = apply_force_keep_repairs(
            current_edl,
            current_subtitles,
            source_subtitles,
            tail_force_indices,
        )
        tail_repair_rounds += 1
        tail_repair_actions.extend(actions)
        repair_actions.extend(actions)
        write_json(run_dir / f"semantic_tail_repair_{tail_repair_rounds:02d}_video_edl.json", current_edl)
        write_json(run_dir / f"semantic_tail_repair_{tail_repair_rounds:02d}_display_subtitle_plan.json", current_subtitles)
        final_coverage, final_md = build_semantic_coverage_report(
            source_subtitles,
            current_subtitles,
            merged,
            duplicate_family_report,
            script_path,
        )
        final_coverage = apply_llm_coverage_overrides(final_coverage, all_results, repair_actions)
    remaining_suspicious = discover_semantic_suspicious_units(source_subtitles, current_subtitles, final_coverage)
    remaining_true_missing = int(final_coverage.get("missing_required_unit_count") or 0)
    remaining_manual_review = int(final_coverage.get("llm_manual_review_count") or 0)
    report = {
        "iteration_count": min(max_iterations, len([p for p in run_dir.glob("semantic_repair_iter_*") if p.is_dir()])),
        "initial_true_missing_count": initial_true_missing,
        "initial_manual_review_count": initial_manual_review,
        "repaired_true_missing_count": len(repair_actions),
        "conservative_keep_count": len(repair_actions),
        "remaining_true_missing_count": remaining_true_missing,
        "remaining_manual_review_count": remaining_manual_review,
        "repair_actions": repair_actions,
        "tail_repair_actions": tail_repair_actions,
        "tail_repair_rounds": tail_repair_rounds,
        "llm_summary": llm_summary | {"call_count": llm_call_count, "llm_used": bool(all_results), "unit_count": len(all_results)},
    }
    write_json(run_dir / "semantic_llm_arbiter_results.json", all_results)
    write_json(run_dir / "semantic_llm_arbiter_requests.json", all_requests)
    write_json(run_dir / "semantic_repair_loop_report.json", report)
    lines = [
        "# Semantic Repair Loop",
        "",
        f"- iteration_count: {report['iteration_count']}",
        f"- initial_true_missing_count: {initial_true_missing}",
        f"- initial_manual_review_count: {initial_manual_review}",
        f"- repaired_true_missing_count: {report['repaired_true_missing_count']}",
        f"- conservative_keep_count: {report['conservative_keep_count']}",
        f"- remaining_true_missing_count: {remaining_true_missing}",
        "",
        "## Repair Actions",
    ]
    for action in repair_actions:
        lines.append(f"- sub {action['subtitle_index']}: {action['source_text']}")
    (run_dir / "semantic_repair_loop_report.md").write_text("\n".join(lines) + "\n", "utf-8")
    write_json(run_dir / "semantic_coverage_report.json", final_coverage)
    (run_dir / "semantic_coverage_review.md").write_text(final_md, "utf-8")
    write_json(run_dir / "semantic_suspicious_units.final.json", remaining_suspicious)
    return current_edl, current_subtitles, final_coverage, report, report.get("llm_summary") or {}
