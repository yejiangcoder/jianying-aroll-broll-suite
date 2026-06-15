from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from aroll_final_repeat_gate import build_final_repeat_gate_report
from aroll_hidden_audio_repeat_gate import build_hidden_audio_repeat_report
from aroll_safe_cut_boundary_gate import audit_safe_cut_boundaries
from aroll_subtitle_coverage_gate import audit_subtitle_coverage


DEFAULT_RUNTIME = Path(__file__).resolve().parents[1] / "runtime"


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def latest_runtime(pattern: str, runtime_root: Path, exclude: Path | None = None) -> Path | None:
    rows = [path for path in runtime_root.glob(pattern) if path.is_dir()]
    if exclude:
        rows = [path for path in rows if path.resolve() != exclude.resolve()]
    rows.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return rows[0] if rows else None


def previous_runtime(bad_runtime: Path, runtime_root: Path) -> Path | None:
    rows = [path for path in runtime_root.glob("aroll_phase6b_llm_first_decision_*") if path.is_dir()]
    rows.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for path in rows:
        if path.resolve() != bad_runtime.resolve():
            return path
    return None


def summary_from_write_report(path: Path | None) -> dict[str, Any]:
    if not path:
        return {"runtime": None, "write_report_exists": False}
    report = read_json(path / "write_report.json", {})
    residual = read_json(path / "postwrite_residual_repeat_audit.json", {})
    return {
        "runtime": str(path),
        "write_report_exists": bool(report),
        "status": report.get("status"),
        "source_duration_s": report.get("source_duration_s"),
        "final_duration_s": report.get("final_duration_s"),
        "removed_duration_s": report.get("removed_duration_s"),
        "video_segments": report.get("video_segments"),
        "subtitle_segments": report.get("subtitle_segments"),
        "drop_decision_count": report.get("drop_decision_count"),
        "micro_cleanup_count": report.get("micro_cleanup_count"),
        "hidden_audio_cut_count": report.get("hidden_audio_cut_count"),
        "word_timeline_hidden_repeat_cut_count": report.get("word_timeline_hidden_repeat_cut_count"),
        "audio_only_repeat_detection_enabled": report.get("audio_only_repeat_detection_enabled"),
        "postwrite_residual_repeat_issue_count": residual.get("issue_count"),
        "postwrite_high_text_repeat_count": residual.get("high_confidence_text_repeat_count"),
        "postwrite_high_word_hidden_repeat_count": residual.get("high_confidence_word_timeline_hidden_repeat_count"),
        "gate": report.get("gate") or {},
    }


def build_style_snapshot_unavailable_report(output_path: Path) -> dict[str, Any]:
    report = {
        "diagnosis_status": "source_material_snapshot_missing_after_runtime_cleanup",
        "subtitle_style_outlier_count": None,
        "max_font_size": None,
        "max_scale": None,
        "invalid_text_template_count": None,
        "style_integrity_gate_passed": False,
        "blocking_reason": "historical_bad_runtime_does_not_contain_final_text_material_snapshot; production gate now validates before write",
    }
    write_json(output_path, report)
    return report


def write_markdown_report(
    path: Path,
    *,
    bad_runtime: Path,
    previous: Path | None,
    style_report: dict[str, Any],
    coverage_report: dict[str, Any],
    repeat_report: dict[str, Any],
    hidden_report: dict[str, Any],
    boundary_report: dict[str, Any],
    rollback_report: dict[str, Any],
    compare_report: dict[str, Any],
) -> None:
    lines = [
        "# UAT Failure Diagnosis",
        "",
        f"- bad_runtime: `{bad_runtime}`",
        f"- previous_runtime: `{previous}`",
        f"- bad_write_rollback_done: `{rollback_report.get('bad_write_rollback_done')}`",
        f"- can_run_uat: `false`",
        "",
        "## Gate Snapshot",
        "",
        f"- style_integrity_gate_passed: `{style_report.get('style_integrity_gate_passed')}`",
        f"- subtitle_coverage_gate_passed: `{coverage_report.get('subtitle_coverage_gate_passed')}`",
        f"- final_repeat_gate_passed: `{repeat_report.get('final_repeat_gate_passed')}`",
        f"- hidden_audio_repeat_gate_passed: `{hidden_report.get('hidden_audio_repeat_gate_passed')}`",
        f"- safe_cut_boundary_gate_passed: `{boundary_report.get('safe_cut_boundary_gate_passed')}`",
        "",
        "## Key Counts",
        "",
        f"- missing_subtitle_unit_count: `{coverage_report.get('missing_subtitle_unit_count')}`",
        f"- final_text_repeat_high_count: `{repeat_report.get('final_text_repeat_high_count')}`",
        f"- final_text_repeat_medium_count: `{repeat_report.get('final_text_repeat_medium_count')}`",
        f"- final_semantic_repeat_high_count: `{repeat_report.get('final_semantic_repeat_high_count')}`",
        f"- final_hidden_word_repeat_high_count: `{repeat_report.get('final_hidden_word_repeat_high_count')}`",
        f"- word_timeline_hidden_repeat_count: `{hidden_report.get('word_timeline_hidden_repeat_count')}`",
        f"- audio_only_repeat_supported: `{hidden_report.get('audio_only_repeat_supported')}`",
        f"- unsafe_cut_boundary_count: `{boundary_report.get('unsafe_cut_boundary_count')}`",
        f"- cut_inside_word_count: `{boundary_report.get('cut_inside_word_count')}`",
        "",
        "## Conclusion",
        "",
        "This diagnosis is read-only. It does not repair the bad draft and does not run RunFull.",
        "UAT remains blocked until the new prewrite gates pass on a clean source draft.",
        "",
        "## Root Cause Notes",
        "",
        "- Bad runtime source_duration_s=181.66 indicates the tool likely ran on an already processed draft.",
        "- Last known clean-source comparison runtime reports source_duration_s around 257.333.",
        "- Missing source_draft_integrity_gate was the primary process hole: create_baseline_backup could preserve a dirty current draft as baseline.",
        "- Historical subtitle_coverage_gate used coarse range overlap and produced weak missing samples.",
        "- Historical hidden_audio_repeat_gate used a project-specific phrase patch instead of generic repeated-island detection.",
        "- Historical safe_cut_boundary_gate checked drop plans only, not every final_edl source boundary.",
        "",
        "## Runtime Comparison",
        "",
        "```json",
        json.dumps(compare_report, ensure_ascii=False, indent=2),
        "```",
    ]
    path.write_text("\n".join(lines) + "\n", "utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bad-runtime", type=Path, default=None)
    parser.add_argument("--previous-runtime", type=Path, default=None)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME)
    args = parser.parse_args()

    runtime_root = args.runtime_root

    bad_runtime = args.bad_runtime or latest_runtime("aroll_phase6b_llm_first_decision_*", runtime_root)
    if not bad_runtime or not bad_runtime.exists():
        raise SystemExit("BAD_RUNTIME_NOT_FOUND")
    previous = args.previous_runtime or previous_runtime(bad_runtime, runtime_root)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = runtime_root / f"uat_failure_diagnosis_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    display_plan = read_json(bad_runtime / "full_display_subtitle_plan.json", [])
    final_edl = read_json(bad_runtime / "full_video_edl.json", [])
    word_timeline = read_json(bad_runtime / "word_timeline.json", [])
    residual_audit = (
        read_json(bad_runtime / "postwrite_residual_repeat_audit.json", {})
        or read_json(bad_runtime / "full_residual_repeat_audit_after_post_semantic_fix.json", {})
        or read_json(bad_runtime / "full_residual_repeat_audit_after_fix.json", {})
        or {}
    )
    merged = read_json(bad_runtime / "merged_aroll_decisions.json", {})
    repeat_plan = read_json(bad_runtime / "full_repeat_fix_plan.json", {})
    post_semantic_plan = read_json(bad_runtime / "full_post_semantic_repeat_fix_plan.json", {})

    style_report = build_style_snapshot_unavailable_report(out_dir / "subtitle_style_integrity_report.json")
    coverage_report = audit_subtitle_coverage(final_edl, display_plan, word_timeline, output_path=out_dir / "subtitle_coverage_report.json")
    repeat_report = build_final_repeat_gate_report(residual_audit, display_plan, output_path=out_dir / "final_repeat_gate_report.json")
    hidden_report = build_hidden_audio_repeat_report(
        residual_audit,
        display_plan,
        word_timeline,
        output_path=out_dir / "hidden_audio_repeat_report.json",
    )
    boundary_report = audit_safe_cut_boundaries(
        word_timeline,
        merged,
        repeat_plan,
        post_semantic_plan,
        final_edl=final_edl,
        output_path=out_dir / "safe_cut_boundary_report.json",
    )

    rollback_report = {
        "bad_write_rollback_done": False,
        "reason": "user_manual_reset_no_write_performed_by_diagnosis",
        "bad_runtime": str(bad_runtime),
        "available_backup_dir": str(bad_runtime / "backup") if (bad_runtime / "backup").exists() else None,
        "available_baseline_backup_dir": str(bad_runtime / "baseline_backup") if (bad_runtime / "baseline_backup").exists() else None,
        "draft_write_performed": False,
        "encrypt_called": False,
    }
    write_json(out_dir / "bad_write_rollback_report.json", rollback_report)

    compare_report = {
        "bad": summary_from_write_report(bad_runtime),
        "previous": summary_from_write_report(previous),
        "likely_root_causes": [
            "previous_run_baseline_may_have_been_created_from_already_processed_draft",
            "historical_prewrite_gate_did_not_validate_final_subtitle_style_integrity",
            "historical_prewrite_gate_did_not_validate_display_subtitle_coverage_against_final_speech_units",
            "historical_repeat_gate_reported_audio_only_as_unsupported_but_did_not_block_on_word_timeline_hidden_repeat_context",
            "historical_cut_boundary_gate_did_not block all added drop spans before write",
        ],
    }
    write_json(out_dir / "compared_with_previous_runtime_report.json", compare_report)

    write_markdown_report(
        out_dir / "uat_failure_report.md",
        bad_runtime=bad_runtime,
        previous=previous,
        style_report=style_report,
        coverage_report=coverage_report,
        repeat_report=repeat_report,
        hidden_report=hidden_report,
        boundary_report=boundary_report,
        rollback_report=rollback_report,
        compare_report=compare_report,
    )

    print(f"diagnosis_dir={out_dir}")
    print("bad_write_rollback_done=false")
    print("can_run_uat=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
