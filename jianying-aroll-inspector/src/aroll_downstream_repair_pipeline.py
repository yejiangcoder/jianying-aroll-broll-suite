from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aroll_final_target_repeat_repair import propose_final_target_repeat_repairs
from aroll_gate_runner import run_downstream_gates
from aroll_hidden_repeat_repair import propose_hidden_repeat_repairs, rebuild_subtitle_plan_for_edl_words
from aroll_repair_applier import apply_repair_proposals
from aroll_repair_applier import rebase_edl
from aroll_repair_proposal import RepairProposal, proposal_to_dict
from aroll_safe_cut_boundary_resolver import resolve_safe_cut_boundaries
from aroll_subtitle_interval_guard import apply_subtitle_interval_guard


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _drop_wordless_clips(
    final_edl: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for clip in final_edl:
        start = int(clip.get("source_start_us") or clip.get("source_timeline_start_us") or 0)
        end = int(clip.get("source_end_us") or clip.get("source_timeline_end_us") or 0)
        has_word = any(
            start <= int(word.get("start_us") or 0)
            and int(word.get("end_us") or 0) <= end
            for word in word_timeline
        )
        if has_word:
            kept.append(clip)
        else:
            dropped.append({"clip_id": clip.get("clip_id"), "source_start_us": start, "source_end_us": end})
    return rebase_edl(kept), {
        "wordless_clip_before_count": len(dropped) + len(kept),
        "wordless_clip_removed_count": len(dropped),
        "wordless_clip_cleanup_passed": True,
        "removed_clips": dropped[:100],
    }


def run_downstream_repair_pipeline(
    *,
    final_edl: list[dict[str, Any]],
    display_subtitle_plan: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
    run_dir: Path,
    max_iterations: int = 2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    run_dir.mkdir(parents=True, exist_ok=True)
    edl = [dict(row) for row in final_edl]
    subtitles = [dict(row) for row in display_subtitle_plan]
    iteration_reports: list[dict[str, Any]] = []
    total_proposal_count = 0
    total_applied_count = 0
    total_boundary_resolved_count = 0
    initial_gate_passed = False

    for iteration in range(1, max_iterations + 1):
        iter_dir = run_dir / f"iteration_{iteration:02d}"
        gate = run_downstream_gates(
            final_edl=edl,
            display_subtitle_plan=subtitles,
            word_timeline=word_timeline,
            run_dir=iter_dir / "gates_before",
        )
        if iteration == 1:
            initial_gate_passed = bool(gate.get("all_gates_passed"))
        if gate.get("all_gates_passed"):
            report = {
                "pipeline_iterations": iteration - 1,
                "initial_gate_passed": initial_gate_passed,
                "final_gate_passed": True,
                "total_proposal_count": total_proposal_count,
                "total_applied_proposal_count": total_applied_count,
                "total_boundary_resolved_count": total_boundary_resolved_count,
                "remaining_blockers": [],
                "iteration_reports": iteration_reports,
                "final_gate": gate,
            }
            write_json(run_dir / "downstream_repair_pipeline_report.json", report)
            return edl, subtitles, report

        proposals: list[RepairProposal] = []
        proposal_reports: dict[str, Any] = {}
        raw = gate.get("raw_reports") or {}
        if not gate.get("hidden_audio_repeat_gate_passed"):
            hidden_props, hidden_report = propose_hidden_repeat_repairs(
                hidden_repeat_report=raw.get("hidden_repeat") or {},
                display_subtitle_plan=subtitles,
                word_timeline=word_timeline,
            )
            proposals.extend(hidden_props)
            proposal_reports["hidden_repeat"] = hidden_report
        if not gate.get("final_repeat_gate_passed"):
            final_props, final_report = propose_final_target_repeat_repairs(
                final_repeat_gate_report=raw.get("final_repeat") or {},
                display_subtitle_plan=subtitles,
                word_timeline=word_timeline,
            )
            proposals.extend(final_props)
            proposal_reports["final_repeat"] = final_report

        safe_failed = not gate.get("safe_cut_boundary_gate_passed")
        if not proposals and not safe_failed:
            report = {
                "pipeline_iterations": iteration,
                "initial_gate_passed": initial_gate_passed,
                "final_gate_passed": False,
                "total_proposal_count": total_proposal_count,
                "total_applied_proposal_count": total_applied_count,
                "total_boundary_resolved_count": total_boundary_resolved_count,
                "remaining_blockers": gate.get("fatal_reasons") or [],
                "iteration_reports": iteration_reports,
                "block_reason": "gates failed but no repair proposal was generated",
                "final_gate": gate,
            }
            write_json(run_dir / "downstream_repair_pipeline_report.json", report)
            return edl, subtitles, report

        write_json(iter_dir / "repair_proposals.json", [proposal_to_dict(row) for row in proposals])
        total_proposal_count += len(proposals)
        if proposals:
            edl, apply_report = apply_repair_proposals(
                final_edl=edl,
                display_subtitle_plan=subtitles,
                word_timeline=word_timeline,
                proposals=proposals,
            )
        else:
            apply_report = {
                "proposal_count": 0,
                "applied_count": 0,
                "skipped_conservative_keep_count": 0,
                "blocked_count": 0,
                "remove_range_count": 0,
                "unmapped_proposal_count": 0,
                "applier_passed": True,
            }
        write_json(iter_dir / "repair_apply_report.json", apply_report)
        total_applied_count += int(apply_report.get("applied_count") or 0)
        if not apply_report.get("applier_passed"):
            report = {
                "pipeline_iterations": iteration,
                "initial_gate_passed": initial_gate_passed,
                "final_gate_passed": False,
                "total_proposal_count": total_proposal_count,
                "total_applied_proposal_count": total_applied_count,
                "total_boundary_resolved_count": total_boundary_resolved_count,
                "remaining_blockers": ["REPAIR_APPLIER_BLOCKED"],
                "iteration_reports": iteration_reports,
                "proposal_reports": proposal_reports,
                "apply_report": apply_report,
            }
            write_json(run_dir / "downstream_repair_pipeline_report.json", report)
            return edl, subtitles, report

        edl, boundary_report = resolve_safe_cut_boundaries(
            final_edl=edl,
            word_timeline=word_timeline,
            output_path=iter_dir / "safe_cut_boundary_resolve_report.json",
        )
        edl, wordless_report = _drop_wordless_clips(edl, word_timeline)
        write_json(iter_dir / "wordless_clip_cleanup_report.json", wordless_report)
        total_boundary_resolved_count += int(boundary_report.get("resolved_boundary_count") or 0)
        subtitles, rebuild_report = rebuild_subtitle_plan_for_edl_words(edl, word_timeline)
        subtitles, interval_report = apply_subtitle_interval_guard(subtitles)
        write_json(iter_dir / "rebuilt_display_subtitle_plan.json", subtitles)
        write_json(iter_dir / "rebuilt_subtitle_report.json", rebuild_report)
        write_json(iter_dir / "subtitle_interval_guard_report.json", interval_report)
        iteration_reports.append(
            {
                "iteration": iteration,
                "gate_before": {
                    "all_gates_passed": gate.get("all_gates_passed"),
                    "fatal_reasons": gate.get("fatal_reasons") or [],
                    "hidden_audio_repeat_gate_passed": gate.get("hidden_audio_repeat_gate_passed"),
                    "final_repeat_gate_passed": gate.get("final_repeat_gate_passed"),
                    "safe_cut_boundary_gate_passed": gate.get("safe_cut_boundary_gate_passed"),
                    "subtitle_coverage_gate_passed": gate.get("subtitle_coverage_gate_passed"),
                },
                "proposal_reports": proposal_reports,
                "apply_report": apply_report,
                "boundary_report": boundary_report,
                "wordless_clip_cleanup_report": wordless_report,
                "rebuild_report": rebuild_report,
            }
        )

    final_gate = run_downstream_gates(
        final_edl=edl,
        display_subtitle_plan=subtitles,
        word_timeline=word_timeline,
        run_dir=run_dir / "final_gates",
    )
    report = {
        "pipeline_iterations": max_iterations,
        "initial_gate_passed": initial_gate_passed,
        "final_gate_passed": bool(final_gate.get("all_gates_passed")),
        "total_proposal_count": total_proposal_count,
        "total_applied_proposal_count": total_applied_count,
        "total_boundary_resolved_count": total_boundary_resolved_count,
        "remaining_blockers": final_gate.get("fatal_reasons") or [],
        "iteration_reports": iteration_reports,
        "final_gate": final_gate,
    }
    write_json(run_dir / "downstream_repair_pipeline_report.json", report)
    return edl, subtitles, report
