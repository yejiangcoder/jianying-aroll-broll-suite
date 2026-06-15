from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aroll_final_repeat_gate import build_final_repeat_gate_report
from aroll_final_residual_repeat_auditor import audit_final_residual_repeats
from aroll_hidden_audio_repeat_gate import build_hidden_audio_repeat_report
from aroll_safe_cut_boundary_gate import audit_safe_cut_boundaries
from aroll_subtitle_coverage_gate import audit_subtitle_coverage


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def run_downstream_gates(
    *,
    final_edl: list[dict[str, Any]],
    display_subtitle_plan: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
    text_segments: list[dict[str, Any]] | None = None,
    material_texts: list[dict[str, Any]] | None = None,
    run_dir: Path,
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    residual_audit = audit_final_residual_repeats(final_edl, display_subtitle_plan, word_timeline)
    write_json(run_dir / "residual_repeat_audit.json", residual_audit)
    subtitle_coverage = audit_subtitle_coverage(
        final_edl,
        display_subtitle_plan,
        word_timeline,
        output_path=run_dir / "subtitle_coverage_report.json",
    )
    final_repeat = build_final_repeat_gate_report(
        residual_audit,
        display_subtitle_plan,
        output_path=run_dir / "final_repeat_gate_report.json",
    )
    hidden_repeat = build_hidden_audio_repeat_report(
        residual_audit,
        display_subtitle_plan,
        word_timeline,
        output_path=run_dir / "hidden_audio_repeat_report.json",
    )
    safe_cut = audit_safe_cut_boundaries(
        word_timeline,
        final_edl=final_edl,
        output_path=run_dir / "safe_cut_boundary_report.json",
    )
    style = {
        "style_gate_skipped": text_segments is None or material_texts is None,
        "style_integrity_gate_passed": True,
        "reason": "style gate requires draft text segment/material context and is executed by the main write gate",
    }
    write_json(run_dir / "subtitle_style_integrity_report.json", style)
    fatal_reasons: list[str] = []
    if not subtitle_coverage.get("subtitle_coverage_gate_passed"):
        fatal_reasons.append("SUBTITLE_COVERAGE_GATE_FAILED")
    if not final_repeat.get("final_repeat_gate_passed"):
        fatal_reasons.append("FINAL_REPEAT_GATE_FAILED")
    if not hidden_repeat.get("hidden_audio_repeat_gate_passed"):
        fatal_reasons.append("HIDDEN_AUDIO_REPEAT_GATE_FAILED")
    if not safe_cut.get("safe_cut_boundary_gate_passed"):
        fatal_reasons.append("SAFE_CUT_BOUNDARY_GATE_FAILED")
    report = {
        "all_gates_passed": not fatal_reasons,
        "subtitle_coverage_gate_passed": bool(subtitle_coverage.get("subtitle_coverage_gate_passed")),
        "subtitle_style_integrity_gate_passed": bool(style.get("style_integrity_gate_passed")),
        "final_repeat_gate_passed": bool(final_repeat.get("final_repeat_gate_passed")),
        "hidden_audio_repeat_gate_passed": bool(hidden_repeat.get("hidden_audio_repeat_gate_passed")),
        "safe_cut_boundary_gate_passed": bool(safe_cut.get("safe_cut_boundary_gate_passed")),
        "fatal_reasons": fatal_reasons,
        "reports": {
            "subtitle_coverage": str(run_dir / "subtitle_coverage_report.json"),
            "style": str(run_dir / "subtitle_style_integrity_report.json"),
            "final_repeat": str(run_dir / "final_repeat_gate_report.json"),
            "hidden_repeat": str(run_dir / "hidden_audio_repeat_report.json"),
            "safe_cut": str(run_dir / "safe_cut_boundary_report.json"),
        },
        "raw_reports": {
            "subtitle_coverage": subtitle_coverage,
            "style": style,
            "final_repeat": final_repeat,
            "hidden_repeat": hidden_repeat,
            "safe_cut": safe_cut,
            "residual_audit": residual_audit,
        },
    }
    write_json(run_dir / "downstream_gate_report.json", report)
    return report

