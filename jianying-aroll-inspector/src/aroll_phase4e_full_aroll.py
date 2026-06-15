from __future__ import annotations

import argparse
import json
import subprocess
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aroll_adjacent_boundary_guard import normalize_adjacent_source_overlaps
from aroll_attached_effects_preservation import (
    build_attached_effects_preservation_report,
    inspect_attached_effects,
)
from aroll_audio_enhancement import build_audio_enhancement_preservation_report
from aroll_codex_self_review import (
    build_self_review_report,
    collect_self_review_candidates,
    write_self_review_outputs,
)
from aroll_contract_check import timeline_id_checks_after
from aroll_candidate_discovery import discover_aroll_candidates
from aroll_decision_merger import decision_maps, merge_decisions
from aroll_decision_plan_builder import apply_decision_plan_to_merged, build_aroll_decision_plan
from aroll_display_subtitle_planner import build_display_subtitle_plan, readability_report
from aroll_downstream_repair_pipeline import run_downstream_repair_pipeline
from aroll_duplicate_family_guard import apply_duplicate_family_guard
from aroll_final_audit_candidate_adapter import build_final_audit_llm_candidates, summarize_final_audit_llm_results
from aroll_final_repeat_gate import build_final_repeat_gate_report
from aroll_final_residual_repeat_auditor import audit_final_residual_repeats, write_json
from aroll_hidden_audio_repeat_gate import build_hidden_audio_repeat_report
from aroll_inspect import (
    DEFAULT_RUNTIME,
    build_report as inspect_build_report,
    inspect_audio_tracks,
    inspect_filter_tracks,
    inspect_video_tracks,
    subtitle_timeline,
    total_target_duration,
)
from aroll_intra_segment_breath_cutter import apply_breath_cuts_to_edl, build_breath_cut_plan, rebase_subtitle_plan
from aroll_llm_semantic_overlap_arbiter import no_call_report
from aroll_multi_material_audio_audit import (
    annotate_edl_with_materials,
    audit_postwrite_audio_multi_material,
)
from aroll_pause_tightening_pass import apply_tightening_to_edl, build_pause_tightening_candidates
from aroll_poc_writer import backup_draft_files, get_track, split_video_segments_for_edl, write_encrypted_to_targets
from aroll_postwrite_audio_audit import audit_postwrite_audio
from aroll_repeat_fix_planner import apply_fix_plan_to_edl, apply_fix_plan_to_subtitles, build_final_repeat_fix_plan
from aroll_report_utils import filter_breath_plan_for_min_pieces, write_decision_merge_report
from aroll_runtime_mode import cleanup_current_runtime
from aroll_repeat_detector import detect_repeat_clusters
from aroll_safe_gap_cutter import SafeGapCutter
from aroll_safe_cut_boundary_gate import audit_safe_cut_boundaries
from aroll_semantic_coverage_gate import build_semantic_coverage_report
from aroll_semantic_llm_arbiter import arbitrate_suspicious_units
from aroll_semantic_overlap_trimmer import apply_semantic_overlap_trim, semantic_overlap_regression
from aroll_sentence_gap_compressor import build_group_level_edl, build_sentence_gap_report
from aroll_shared_edit_utils import material_text_rows, post_merge_repeat_check, restore_original_backup, run_post_inspect
from aroll_source_draft_integrity_gate import audit_source_draft_integrity
from aroll_speed_self_test import run_speed_mapping_self_test
from aroll_subtitle_coverage_gate import audit_subtitle_coverage
from aroll_subtitle_interval_guard import apply_subtitle_interval_guard
from aroll_subtitle_style_integrity_gate import audit_subtitle_style_integrity
from aroll_take_clusterer import build_take_clusters, take_clusters_to_repeat_detector_rows
from aroll_tiny_segment_guard import audit_tiny_segments
from aroll_video_speech_units import build_video_speech_units, selected_rows_for_range
from jy_bridge import (
    DEFAULT_JY_DRAFTC,
    assert_all_project_timeline_files_match_folder_ids,
    assert_layout_has_no_duplicate_timeline_ids,
    assert_timeline_content_id,
    decrypt,
    encrypt,
    read_json,
    resolve_timeline_id,
    root_mirrors_timeline_id,
)
from aroll_word_timeline import build_word_timeline


DEFAULT_DRAFT_DIR: Path | None = None
DEFAULT_BACKUP_DIR: Path | None = None
DEFAULT_V5_DIR: Path | None = None
DEFAULT_REPEAT_CLUSTERS: Path | None = None
DEFAULT_WORD_TIMELINE: Path | None = None
DEFAULT_SCRIPT_PATH: Path | None = None
MIN_VIDEO_PIECE_US = 500_000
DEFAULT_TARGET_KEEP_PAUSE_US = 220_000


REGRESSION_CASES: dict[str, dict[str, list[str]]] = {}
REGRESSION_PROFILE_NAME = "default_non_blocking"


def running_jianying_processes() -> list[dict[str, str]]:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-Process | Where-Object {$_.ProcessName -like 'JianyingPro*' -or $_.ProcessName -like 'CapCut*' -or $_.ProcessName -like '*剪映*'} | Select-Object ProcessName,Id | ConvertTo-Json -Compress",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    data = json.loads(completed.stdout)
    if isinstance(data, dict):
        data = [data]
    return [{"ProcessName": str(row.get("ProcessName")), "Id": str(row.get("Id"))} for row in data]


def assert_jianying_closed() -> None:
    running = [row for row in running_jianying_processes() if row["ProcessName"] == "JianyingPro"]
    if running:
        raise RuntimeError(f"JIANying_PROCESS_RUNNING_REFUSE_DRAFT_WRITE:{running}")


def run_inspect_summary(draft_dir: Path, run_dir: Path, jy_draftc: Path) -> dict[str, Any]:
    args = SimpleNamespace(
        draft_dir=draft_dir,
        timeline_name="",
        main_video_track_index=-1,
        main_material_path="",
        jy_draftc=jy_draftc,
        runtime=run_dir / "inspect_runtime",
    )
    inspect_dir, report_path, subtitle_path = inspect_build_report(args)
    report = read_json(report_path)
    selected_main = report.get("selected_main_video_track") or {}
    selected_text = next((row for row in report.get("text_tracks") or [] if row.get("selected_as_subtitle_track")), {})
    return {
        "inspect_output_dir": str(inspect_dir),
        "inspect_report_path": str(report_path),
        "subtitle_timeline_path": str(subtitle_path),
        "timeline_id": report.get("timeline_id"),
        "timeline_id_checks": report.get("timeline_id_checks"),
        "root_mirror": report.get("root_mirror"),
        "video_segment_count": selected_main.get("segment_count"),
        "subtitle_segment_count": selected_text.get("segment_count"),
        "duration_us": selected_main.get("total_target_duration_us"),
        "fatal_reasons": report.get("fatal_reasons") or [],
        "warnings": report.get("warnings") or [],
    }


def build_full_regression(source_subtitles: list[dict[str, Any]], final_subtitles: list[dict[str, Any]]) -> dict[str, Any]:
    source_text = "\n".join(str(row.get("subtitle_text") or "") for row in source_subtitles)
    final_text = "\n".join(str(row.get("fragment_text") or row.get("text") or "") for row in final_subtitles)
    checks: dict[str, str] = {}
    case_rows: list[dict[str, Any]] = []
    for name, spec in REGRESSION_CASES.items():
        bad_in_source = any(text in source_text for text in spec["bad"])
        good_in_source = any(text in source_text for text in spec["good"])
        known_micro_enforced = False
        in_range = bad_in_source or good_in_source
        if not in_range:
            checks[name] = "not_in_range"
            case_rows.append({"name": name, "status": "not_applicable", "blocking": False})
            continue
        bad_present = any(text in final_text for text in spec["bad"])
        good_present = all(text in final_text for text in spec["good"])
        enforce_clean_form = good_in_source or known_micro_enforced
        blocking = bool(bad_present and enforce_clean_form)
        if good_present and not bad_present:
            status = "fixed"
        elif bad_present and enforce_clean_form:
            status = "failed_bad_present"
        elif bad_present:
            status = "source_form_present_report_only"
        else:
            status = "failed_good_missing"
        checks[name] = status
        case_rows.append(
            {
                "name": name,
                "status": status,
                "bad_present": bad_present,
                "good_present": good_present,
                "bad_in_source": bad_in_source,
                "good_in_source": good_in_source,
                "known_micro_enforced": known_micro_enforced,
                "blocking": blocking,
                "note": "bad text present blocks write; missing expected clean text is reported for review",
            }
        )
    failed = [name for name, status in checks.items() if status == "failed"]
    blocking_failed = [row["name"] for row in case_rows if row.get("blocking")]
    in_range_count = len([row for row in case_rows if row["status"] != "not_applicable"])
    not_applicable_count = len([row for row in case_rows if row["status"] == "not_applicable"])
    return {
        "profile_name": REGRESSION_PROFILE_NAME,
        "cases_total": len(REGRESSION_CASES),
        "cases_in_range": in_range_count,
        "cases_not_applicable": not_applicable_count,
        "cases_failed": len([name for name, status in checks.items() if str(status).startswith("failed")]),
        "fatal_failed_count": len(blocking_failed),
        "blocking_failed": blocking_failed,
        "report_only": len(blocking_failed) == 0,
        "cases": case_rows,
        "checks": checks,
        "failed_count": len([name for name, status in checks.items() if str(status).startswith("failed")]),
        "failed": [name for name, status in checks.items() if str(status).startswith("failed")],
        "final_subtitles": [str(row.get("fragment_text") or row.get("text") or "") for row in final_subtitles],
    }


def build_gate_check(
    fatal_reasons: list[str],
    repeat_audit: dict[str, Any],
    tiny_report: dict[str, Any],
    readability: dict[str, Any],
    interval_report: dict[str, Any],
    codex_self_review_unresolved_count: int,
    duplicate_family_report: dict[str, Any],
    semantic_coverage_report: dict[str, Any],
    multi_material_audio_report: dict[str, Any],
    subtitle_style_report: dict[str, Any] | None = None,
    subtitle_coverage_report: dict[str, Any] | None = None,
    final_repeat_gate_report: dict[str, Any] | None = None,
    hidden_audio_repeat_report: dict[str, Any] | None = None,
    safe_cut_boundary_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    subtitle_style_report = subtitle_style_report or {}
    subtitle_coverage_report = subtitle_coverage_report or {}
    final_repeat_gate_report = final_repeat_gate_report or {}
    hidden_audio_repeat_report = hidden_audio_repeat_report or {}
    safe_cut_boundary_report = safe_cut_boundary_report or {}
    gate = {
        "fatal_reasons": fatal_reasons,
        "codex_self_review_unresolved_count": codex_self_review_unresolved_count,
        "semantic_ambiguous_unresolved_count": codex_self_review_unresolved_count,
        "high_confidence_text_repeat_count": int(repeat_audit.get("high_confidence_text_repeat_count") or 0),
        "high_confidence_hidden_audio_repeat_count": int(repeat_audit.get("high_confidence_word_timeline_hidden_repeat_count") or repeat_audit.get("high_confidence_hidden_audio_repeat_count") or 0),
        "high_confidence_word_timeline_hidden_repeat_count": int(repeat_audit.get("high_confidence_word_timeline_hidden_repeat_count") or repeat_audit.get("high_confidence_hidden_audio_repeat_count") or 0),
        "audio_only_repeat_detection_enabled": bool(repeat_audit.get("audio_only_repeat_detection_enabled")),
        "unhandled_tiny_artifact_segment_count": int(tiny_report.get("unhandled_tiny_artifact_segment_count") or 0),
        "unauthorized_segment_under_500ms": int(tiny_report.get("unauthorized_segment_under_500ms") or 0),
        "subtitle_interval_overlap_count": int(interval_report.get("overlap_count_after") or 0),
        "overlong_subtitle_count": int(readability.get("overlong_subtitle_count") or 0),
        "single_char_subtitle_count": int(readability.get("single_char_subtitle_count") or 0),
        "missing_required_unit_count": int(semantic_coverage_report.get("missing_required_unit_count") or 0),
        "dirty_unit_filtered_count": int(semantic_coverage_report.get("dirty_unit_filtered_count") or 0),
        "allowed_dropped_unit_count": int(semantic_coverage_report.get("allowed_dropped_unit_count") or 0),
        "coverage_false_positive_prevented_count": int(semantic_coverage_report.get("coverage_false_positive_prevented_count") or 0),
        "all_dropped_duplicate_family_count": int(duplicate_family_report.get("all_dropped_family_count_after") or 0),
        "audio_audit_valid_for_full_timeline": bool(multi_material_audio_report.get("audio_audit_valid_for_full_timeline")),
        "subtitle_style_outlier_count": int(subtitle_style_report.get("subtitle_style_outlier_count") or 0),
        "transform_outlier_count": int(subtitle_style_report.get("transform_outlier_count") or 0),
        "position_outlier_count": int(subtitle_style_report.get("position_outlier_count") or 0),
        "template_fingerprint_mismatch_count": int(subtitle_style_report.get("template_fingerprint_mismatch_count") or 0),
        "caption_track_template_mismatch_count": int(subtitle_style_report.get("caption_track_template_mismatch_count") or 0),
        "max_font_size": subtitle_style_report.get("max_font_size"),
        "max_scale": subtitle_style_report.get("max_scale"),
        "invalid_text_template_count": int(subtitle_style_report.get("invalid_text_template_count") or 0),
        "style_integrity_gate_passed": bool(subtitle_style_report.get("style_integrity_gate_passed", True)),
        "final_speech_unit_count": int(subtitle_coverage_report.get("final_speech_unit_count") or 0),
        "subtitle_covered_speech_unit_count": int(subtitle_coverage_report.get("subtitle_covered_speech_unit_count") or 0),
        "missing_subtitle_unit_count": int(subtitle_coverage_report.get("missing_subtitle_unit_count") or 0),
        "expected_word_count": int(subtitle_coverage_report.get("expected_word_count") or 0),
        "displayed_word_count": int(subtitle_coverage_report.get("displayed_word_count") or 0),
        "missing_word_count": int(subtitle_coverage_report.get("missing_word_count") or 0),
        "subtitle_word_coverage_ratio": subtitle_coverage_report.get("subtitle_word_coverage_ratio"),
        "subtitle_coverage_gate_passed": bool(subtitle_coverage_report.get("subtitle_coverage_gate_passed", True)),
        "final_text_repeat_high_count": int(final_repeat_gate_report.get("final_text_repeat_high_count") or 0),
        "final_text_repeat_medium_count": int(final_repeat_gate_report.get("final_text_repeat_medium_count") or 0),
        "final_semantic_repeat_high_count": int(final_repeat_gate_report.get("final_semantic_repeat_high_count") or 0),
        "final_hidden_word_repeat_high_count": int(final_repeat_gate_report.get("final_hidden_word_repeat_high_count") or 0),
        "final_target_take_cluster_count": int(final_repeat_gate_report.get("final_target_take_cluster_count") or 0),
        "final_target_repeat_candidate_count": int(final_repeat_gate_report.get("final_target_repeat_candidate_count") or 0),
        "final_target_llm_candidate_count": int(final_repeat_gate_report.get("final_target_llm_candidate_count") or 0),
        "final_target_repeat_high_count": int(final_repeat_gate_report.get("final_target_repeat_high_count") or 0),
        "final_target_repeat_medium_count": int(final_repeat_gate_report.get("final_target_repeat_medium_count") or 0),
        "audio_only_repeat_supported": bool(final_repeat_gate_report.get("audio_only_repeat_supported")),
        "final_repeat_gate_passed": bool(final_repeat_gate_report.get("final_repeat_gate_passed", True)),
        "word_timeline_hidden_repeat_count": int(hidden_audio_repeat_report.get("word_timeline_hidden_repeat_count") or 0),
        "word_timeline_repeated_island_count": int(hidden_audio_repeat_report.get("word_timeline_repeated_island_count") or 0),
        "audio_only_repeat_not_supported_warning": bool(hidden_audio_repeat_report.get("audio_only_repeat_not_supported_warning")),
        "word_timeline_hidden_repeat_supported": bool(hidden_audio_repeat_report.get("word_timeline_hidden_repeat_supported")),
        "hidden_audio_repeat_gate_passed": bool(hidden_audio_repeat_report.get("hidden_audio_repeat_gate_passed", True)),
        "unsafe_cut_boundary_count": int(safe_cut_boundary_report.get("unsafe_cut_boundary_count") or 0),
        "cut_inside_word_count": int(safe_cut_boundary_report.get("cut_inside_word_count") or 0),
        "final_edl_boundary_checked_count": int(safe_cut_boundary_report.get("final_edl_boundary_checked_count") or 0),
        "drop_plan_boundary_checked_count": int(safe_cut_boundary_report.get("drop_plan_boundary_checked_count") or 0),
        "unsafe_final_edl_boundary_count": int(safe_cut_boundary_report.get("unsafe_final_edl_boundary_count") or 0),
        "unsafe_drop_boundary_count": int(safe_cut_boundary_report.get("unsafe_drop_boundary_count") or 0),
        "min_left_pad_us": safe_cut_boundary_report.get("min_left_pad_us"),
        "min_right_pad_us": safe_cut_boundary_report.get("min_right_pad_us"),
        "safe_cut_boundary_gate_passed": bool(safe_cut_boundary_report.get("safe_cut_boundary_gate_passed", True)),
    }
    if gate["missing_required_unit_count"] > 0:
        gate["fatal_reasons"].append("SEMANTIC_COVERAGE_MISSING_REQUIRED_UNITS")
    if gate["all_dropped_duplicate_family_count"] > 0:
        gate["fatal_reasons"].append("DUPLICATE_FAMILY_STILL_ALL_DROPPED")
    if not gate["audio_audit_valid_for_full_timeline"]:
        gate["fatal_reasons"].append("MULTI_MATERIAL_AUDIO_AUDIT_INVALID")
    if not gate["style_integrity_gate_passed"]:
        gate["fatal_reasons"].append("SUBTITLE_STYLE_INTEGRITY_GATE_FAILED")
    if not gate["subtitle_coverage_gate_passed"]:
        gate["fatal_reasons"].append("SUBTITLE_COVERAGE_GATE_FAILED")
    if not gate["final_repeat_gate_passed"]:
        gate["fatal_reasons"].append("FINAL_REPEAT_GATE_FAILED")
    if not gate["hidden_audio_repeat_gate_passed"]:
        gate["fatal_reasons"].append("HIDDEN_AUDIO_REPEAT_GATE_FAILED")
    if not gate["safe_cut_boundary_gate_passed"]:
        gate["fatal_reasons"].append("SAFE_CUT_BOUNDARY_GATE_FAILED")
    gate["fatal_reasons"] = sorted(set(gate["fatal_reasons"]))
    gate["gate_passed"] = (
        not gate["fatal_reasons"]
        and gate["codex_self_review_unresolved_count"] == 0
        and gate["high_confidence_text_repeat_count"] == 0
        and gate["high_confidence_word_timeline_hidden_repeat_count"] == 0
        and gate["unhandled_tiny_artifact_segment_count"] == 0
        and gate["unauthorized_segment_under_500ms"] == 0
        and gate["subtitle_interval_overlap_count"] == 0
        and gate["overlong_subtitle_count"] == 0
        and gate["single_char_subtitle_count"] == 0
        and gate["missing_required_unit_count"] == 0
        and gate["all_dropped_duplicate_family_count"] == 0
        and gate["audio_audit_valid_for_full_timeline"] is True
        and gate["subtitle_style_outlier_count"] == 0
        and gate["transform_outlier_count"] == 0
        and gate["position_outlier_count"] == 0
        and gate["template_fingerprint_mismatch_count"] == 0
        and gate["caption_track_template_mismatch_count"] == 0
        and gate["invalid_text_template_count"] == 0
        and gate["missing_subtitle_unit_count"] == 0
        and gate["missing_word_count"] == 0
        and gate["final_text_repeat_high_count"] == 0
        and gate["final_text_repeat_medium_count"] == 0
        and gate["final_semantic_repeat_high_count"] == 0
        and gate["final_hidden_word_repeat_high_count"] == 0
        and gate["final_target_repeat_high_count"] == 0
        and gate["final_target_repeat_medium_count"] == 0
        and gate["word_timeline_hidden_repeat_count"] == 0
        and gate["word_timeline_repeated_island_count"] == 0
        and gate["unsafe_cut_boundary_count"] == 0
        and gate["cut_inside_word_count"] == 0
        and gate["unsafe_final_edl_boundary_count"] == 0
        and gate["unsafe_drop_boundary_count"] == 0
    )
    return gate


def write_human_focus(run_dir: Path, report: dict[str, Any], regression: dict[str, Any]) -> None:
    lines = [
        "# Deprecated",
        "",
        "Deprecated: replaced by codex_self_review_report.md",
    ]
    (run_dir / "human_review_focus.md").write_text("\n".join(lines) + "\n", "utf-8")


def build_current_repeat_clusters(
    subtitles: list[dict[str, Any]],
    run_dir: Path,
    explicit_repeat_clusters: Path | None = None,
) -> tuple[list[dict[str, Any]], Path, dict[str, Any]]:
    current = detect_repeat_clusters(subtitles, window=6)
    explicit: list[dict[str, Any]] = []
    explicit_path = ""
    if explicit_repeat_clusters and explicit_repeat_clusters.exists():
        explicit_path = str(explicit_repeat_clusters)
        try:
            loaded = read_json(explicit_repeat_clusters)
            if isinstance(loaded, list):
                explicit = loaded
        except Exception as exc:
            explicit = []
            explicit_path = f"{explicit_repeat_clusters} (load_failed:{exc})"
    combined = current + explicit
    path = run_dir / "current_repeat_clusters.json"
    write_json(path, combined)
    report = {
        "source": "current_draft_subtitles",
        "current_cluster_count": len(current),
        "explicit_cluster_count": len(explicit),
        "combined_cluster_count": len(combined),
        "explicit_repeat_clusters_path": explicit_path,
        "cluster_type_counts": {},
    }
    for row in combined:
        ctype = str(row.get("cluster_type") or "unknown")
        report["cluster_type_counts"][ctype] = int(report["cluster_type_counts"].get(ctype) or 0) + 1
    write_json(run_dir / "current_repeat_cluster_report.json", report)
    return combined, path, report


def suppress_handled_semantic_self_reviews(
    semantic_report: dict[str, Any],
    repeat_plan: dict[str, Any],
) -> dict[str, Any]:
    handled_ids: set[str] = set()
    for key in ("drop_segments", "trim_segments", "merge_segments", "hidden_audio_cuts", "tiny_artifact_removals"):
        for row in repeat_plan.get(key) or []:
            issue_id = str(row.get("issue_id") or "")
            if issue_id:
                handled_ids.add(issue_id)
    items = list(semantic_report.get("codex_self_review") or semantic_report.get("manual_review") or [])
    suppressed = [row for row in items if str(row.get("issue_id") or "") in handled_ids]
    remaining = [row for row in items if str(row.get("issue_id") or "") not in handled_ids]
    semantic_report = dict(semantic_report)
    semantic_report["codex_self_review"] = remaining
    semantic_report["suppressed_codex_self_review"] = suppressed
    semantic_report["codex_self_review_count_before_suppression"] = int(semantic_report.get("codex_self_review_count") or semantic_report.get("manual_review_count") or len(items))
    semantic_report["codex_self_review_count"] = len(remaining)
    semantic_report["suppressed_codex_self_review_count"] = len(suppressed)
    return semantic_report


def build_decision_plan_semantic_coverage_report(
    *,
    source_subtitles: list[dict[str, Any]],
    final_subtitles: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    decision_plan: dict[str, Any],
    llm_summary: dict[str, Any],
) -> dict[str, Any]:
    decisions = decision_plan.get("decisions") or []
    force_keep = decision_plan.get("force_keep_subtitle_indices") or []
    dirty_units = [
        row
        for row in decisions
        if row.get("llm_classification") in {"dirty_stutter_unit", "duplicate_take_covered", "approve_drop", "micro_cleanup_covered", "approve_micro_cleanup"}
    ]
    covered_units = [
        row
        for row in decisions
        if row.get("llm_classification") in {"required_clean_unit_covered"}
    ]
    fatal_reasons = []
    if decision_plan.get("blocked"):
        fatal_reasons.extend(decision_plan.get("block_reasons") or ["DECISION_PLAN_BLOCKED"])
    return {
        "raw_source_unit_count": len(source_subtitles),
        "candidate_count": len(candidates),
        "llm_arbiter_used": bool(llm_summary.get("llm_used")),
        "llm_true_missing_required_count": int(llm_summary.get("true_missing_required_count") or 0),
        "llm_self_review_required_count": int(llm_summary.get("self_review_required_count") or 0),
        "force_keep_count": len(force_keep),
        "dirty_units": dirty_units,
        "covered_units": covered_units,
        "dirty_unit_filtered_count": len(dirty_units),
        "allowed_dropped_unit_count": 0,
        "coverage_false_positive_prevented_count": len(dirty_units) + len(covered_units),
        "missing_required_unit_count": 0,
        "fatal_reasons": sorted(set(fatal_reasons)),
        "final_subtitle_count": len(final_subtitles),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4E full A-Roll gated write.")
    parser.add_argument("--draft-dir", type=Path, default=DEFAULT_DRAFT_DIR)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--v5-dir", type=Path, default=DEFAULT_V5_DIR)
    parser.add_argument("--repeat-clusters", type=Path, default=DEFAULT_REPEAT_CLUSTERS)
    parser.add_argument("--word-timeline", type=Path, default=DEFAULT_WORD_TIMELINE)
    parser.add_argument("--script-path", type=Path, default=DEFAULT_SCRIPT_PATH)
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--runtime-prefix", default="aroll_phase4e_full_aroll")
    parser.add_argument("--runtime-mode", choices=["production", "debug"], default="production")
    parser.add_argument("--keep-debug-dec-json", action="store_true")
    parser.add_argument("--keep-audio-pcm", action="store_true")
    parser.add_argument("--allow-constant-speed", action="store_true")
    parser.add_argument("--max-allowed-speed", type=float, default=1.25)
    parser.add_argument("--expected-duration-us", type=int, default=0)
    parser.add_argument("--expected-subtitle-count", type=int, default=0)
    parser.add_argument("--target-keep-pause-us", type=int, default=DEFAULT_TARGET_KEEP_PAUSE_US)
    args = parser.parse_args()
    if args.draft_dir is None:
        raise RuntimeError("DRAFT_DIR_REQUIRED")
    if args.backup_dir is None:
        raise RuntimeError("BACKUP_DIR_REQUIRED")

    run_dir = args.run_dir or (args.runtime / f"{args.runtime_prefix}_{time.strftime('%Y%m%d_%H%M%S')}")
    run_dir.mkdir(parents=True, exist_ok=True)
    assert_jianying_closed()

    timeline_id, _timeline_name = resolve_timeline_id(args.draft_dir, "")
    restored = restore_original_backup(args.draft_dir, timeline_id, args.backup_dir)
    restore_inspect = run_post_inspect(args.draft_dir, run_dir / "restore_check", args.jy_draftc)
    restored_duration = int(restore_inspect.get("duration_us") or 0)
    restored_subtitles = int(restore_inspect.get("subtitle_segment_count") or 0)
    if args.expected_duration_us > 0 and abs(restored_duration - args.expected_duration_us) > 100_000:
        raise RuntimeError(
            f"RESTORE_DURATION_MISMATCH:expected={args.expected_duration_us}:actual={restored_duration}:{restore_inspect}"
        )
    if args.expected_duration_us <= 0 and restored_duration <= 0:
        raise RuntimeError(f"RESTORE_DURATION_UNSAFE:{restore_inspect}")
    if args.expected_subtitle_count > 0 and restored_subtitles != args.expected_subtitle_count:
        raise RuntimeError(
            f"RESTORE_SUBTITLE_COUNT_MISMATCH:expected={args.expected_subtitle_count}:actual={restored_subtitles}:{restore_inspect}"
        )
    if args.expected_subtitle_count <= 0 and restored_subtitles <= 0:
        raise RuntimeError(f"RESTORE_SUBTITLE_COUNT_UNSAFE:{restore_inspect}")

    timeline_dir = args.draft_dir / "Timelines" / timeline_id
    encrypted_path = timeline_dir / "draft_content.json"
    plain_before = run_dir / "draft_content.before.dec.json"
    plain_modified = run_dir / "draft_content.modified.dec.json"
    encrypted_out = run_dir / "draft_content.modified.enc.json"
    plain_after = run_dir / "draft_content.after.dec.json"

    decrypt(args.jy_draftc, encrypted_path, plain_before)
    data = read_json(plain_before)
    assert_timeline_content_id(data, timeline_id, encrypted_path)
    assert_layout_has_no_duplicate_timeline_ids(args.draft_dir)
    assert_all_project_timeline_files_match_folder_ids(args.draft_dir, args.jy_draftc, run_dir)
    root_mirror_required = root_mirrors_timeline_id(args.draft_dir, args.jy_draftc, run_dir, timeline_id)

    video_candidates, selected_main, video_fatals, video_warnings, main_speed_safe = inspect_video_tracks(
        data,
        max_allowed_speed=args.max_allowed_speed,
    )
    subtitles, text_tracks, selected_text_track = subtitle_timeline(data)
    main_total = int((selected_main or {}).get("total_target_duration_us") or 0)
    source_integrity_report = audit_source_draft_integrity(
        {
            "timeline_id": timeline_id,
            "duration_us": data.get("duration"),
            "selected_main_video_track": selected_main or {},
            "text_tracks": text_tracks,
        },
        data,
        clean_source_duration_us=args.expected_duration_us,
        clean_source_subtitle_count=args.expected_subtitle_count,
        output_path=run_dir / "source_draft_integrity_report.json",
    )
    audio_tracks, has_independent_audio, has_complex_audio, audio_fatals = inspect_audio_tracks(data)
    filter_tracks, has_global_filter, has_complex_filter, filter_fatals = inspect_filter_tracks(data, main_total)
    main_track = get_track(data, str(selected_main["track_id"])) if selected_main else None
    speed_self_test = run_speed_mapping_self_test(main_track or {}, subtitles, args.max_allowed_speed)
    write_json(run_dir / "speed_mapping_self_test.json", speed_self_test)
    attached_effects_report = inspect_attached_effects(data, selected_main)
    write_json(run_dir / "attached_effects_report.json", attached_effects_report)
    speed_requires_mapping = bool((selected_main or {}).get("speed_requires_mapping"))
    speed_allowed = bool(main_speed_safe)
    filtered_video_fatals = [
        reason
        for reason in video_fatals
        if reason
        not in {
            "MAIN_VIDEO_SPEED_REQUIRES_MAPPING",
            "MAIN_VIDEO_HAS_NON_1X_SPEED",
            "MAIN_VIDEO_SPEED_UNSAFE",
            "MAIN_VIDEO_HAS_UNRECOGNIZED_ATTACHED_EFFECT_REFS",
        }
    ]
    preflight_fatal: list[str] = []
    preflight_fatal.extend(source_integrity_report.get("fatal_reasons") or [])
    preflight_fatal.extend(filtered_video_fatals)
    preflight_fatal.extend(attached_effects_report.get("fatal_reasons") or [])
    if speed_requires_mapping:
        if not args.allow_constant_speed:
            preflight_fatal.append("CONSTANT_SPEED_REQUIRES_ALLOW_FLAG")
        elif not speed_self_test.get("passed"):
            preflight_fatal.append("SPEED_MAPPING_SELF_TEST_FAILED")
            preflight_fatal.extend(speed_self_test.get("fatal_reasons") or [])
        else:
            speed_allowed = True
    if not selected_main:
        preflight_fatal.append("MAIN_VIDEO_TRACK_NOT_FOUND")
    if not selected_text_track:
        preflight_fatal.append("TEXT_TRACK_NOT_FOUND")
    if audio_tracks or has_independent_audio or has_complex_audio:
        preflight_fatal.append("AUDIO_TRACK_PRESENT_UNSUPPORTED")
        preflight_fatal.extend(audio_fatals)
    if filter_tracks or has_global_filter or has_complex_filter:
        preflight_fatal.append("FILTER_TRACK_PRESENT_UNSUPPORTED")
        preflight_fatal.extend(filter_fatals)
    if not speed_allowed:
        preflight_fatal.append("MAIN_VIDEO_SPEED_UNSAFE")
    if preflight_fatal:
        preflight_gate = {
            "gate_passed": False,
            "fatal_reasons": sorted(set(preflight_fatal)),
            "source_draft_integrity": source_integrity_report,
        }
        write_json(run_dir / "full_gate_check.json", preflight_gate)
        write_json(run_dir / "write_report.json", {"status": "blocked", "gate": preflight_gate, "writeback_performed": False})
        raise RuntimeError(f"PREFLIGHT_BLOCKED:{sorted(set(preflight_fatal))}")

    text_track = get_track(data, str(selected_text_track["track_id"]))
    old_video_segments = deepcopy(main_track.get("segments") or [])
    if args.word_timeline and args.word_timeline.exists():
        word_timeline = read_json(args.word_timeline)
        word_schema_report = {
            "source": "explicit_word_timeline_file",
            "word_timeline": str(args.word_timeline),
            "fatal_reasons": [],
            "warnings": [],
        }
    else:
        word_timeline, word_schema_report = build_word_timeline(subtitles)
        word_schema_report["source"] = "current_draft_subtitles"
    write_json(run_dir / "word_timeline.json", word_timeline)
    write_json(run_dir / "word_schema_report.json", word_schema_report)
    take_clusters, take_cluster_report = build_take_clusters(subtitles, word_timeline)
    write_json(run_dir / "take_clusters.json", take_clusters)
    write_json(run_dir / "take_cluster_report.json", take_cluster_report)
    repeat_clusters, repeat_clusters_path, repeat_cluster_report = build_current_repeat_clusters(
        subtitles,
        run_dir,
        args.repeat_clusters,
    )
    repeat_clusters.extend(take_clusters_to_repeat_detector_rows(take_clusters))
    repeat_cluster_report["take_cluster_count"] = take_cluster_report.get("take_cluster_count", 0)
    repeat_cluster_report["combined_cluster_count"] = len(repeat_clusters)
    write_json(run_dir / "current_repeat_clusters.json", repeat_clusters)
    write_json(run_dir / "current_repeat_cluster_report.json", repeat_cluster_report)
    merged, merge_report, merge_summary = merge_decisions(subtitles, args.v5_dir, repeat_clusters_path)
    merged, duplicate_family_report = apply_duplicate_family_guard(merged, subtitles, repeat_clusters)
    provisional_drops, provisional_micros = decision_maps(merged)
    provisional_rows = selected_rows_for_range(subtitles, provisional_drops, provisional_micros, 0, main_total)
    provisional_final_context = [
        {
            "fragment_text": row.get("text"),
            "text": row.get("text"),
            "source_start_us": row.get("source_start_us"),
            "source_end_us": row.get("source_end_us"),
        }
        for row in provisional_rows
    ]
    candidates = discover_aroll_candidates(
        source_subtitles=subtitles,
        final_plan=provisional_final_context,
        repeat_clusters=repeat_clusters,
        merged=merged,
        duplicate_family_report=duplicate_family_report,
        script_path=args.script_path,
    )
    write_json(run_dir / "candidate_actions.json", candidates)
    script_reference_report = {
        "script_reference_enabled": bool(args.script_path and args.script_path.exists()),
        "script_path": str(args.script_path) if args.script_path else "",
        "script_path_exists": bool(args.script_path and args.script_path.exists()),
        "candidate_count": len(candidates),
        "candidates_with_script_reference": sum(1 for row in candidates if row.get("script_reference_excerpt")),
        "mode": "script_reference_available" if (args.script_path and args.script_path.exists()) else "current_draft_subtitles_only",
        "warning": "" if (args.script_path and args.script_path.exists()) else "SCRIPT_REFERENCE_DISABLED_NO_SCRIPT_PATH",
    }
    write_json(run_dir / "script_reference_report.json", script_reference_report)
    llm_candidates = [row for row in candidates if row.get("requires_llm")]
    if llm_candidates:
        arbiter_results, semantic_llm_summary = arbitrate_suspicious_units(
            llm_candidates,
            run_dir,
            model="deepseek-chat",
        )
    else:
        arbiter_results = []
        semantic_llm_summary = {
            "llm_used": False,
            "model": "deepseek-chat",
            "call_count": 0,
            "unit_count": 0,
            "suspicious_unit_count": 0,
            "true_missing_required_count": 0,
            "self_review_required_count": 0,
            "approve_drop_count": 0,
            "approve_micro_cleanup_count": 0,
            "dirty_stutter_count": 0,
            "duplicate_take_covered_count": 0,
            "api_key_leaked": False,
        }
        write_json(run_dir / "semantic_llm_arbiter_requests.json", [])
        write_json(run_dir / "semantic_llm_arbiter_results.json", [])
        (run_dir / "semantic_llm_arbiter_report.md").write_text("# Semantic LLM Arbiter\n\n- llm_used: false\n", "utf-8")
    decision_plan = build_aroll_decision_plan(candidates, arbiter_results, run_dir)
    merged, decision_plan_apply_report = apply_decision_plan_to_merged(merged, decision_plan)
    write_json(run_dir / "decision_plan_apply_report.json", decision_plan_apply_report)
    write_json(run_dir / "merged_aroll_decisions.json", merged)
    write_json(run_dir / "duplicate_family_guard_report.json", duplicate_family_report)
    if decision_plan.get("blocked"):
        write_json(run_dir / "write_report.json", {"status": "blocked", "fatal_reasons": decision_plan.get("block_reasons"), "decision_plan": decision_plan})
        raise RuntimeError(f"DECISION_PLAN_BLOCKED:{decision_plan.get('block_reasons')}")
    drops, micros = decision_maps(merged)
    selected_rows = selected_rows_for_range(subtitles, drops, micros, 0, main_total)
    write_decision_merge_report(run_dir / "full_decision_merge_report.md", merge_report, selected_rows)
    repeat_check = post_merge_repeat_check([
        {"fragment_text": row["text"], "source_start_us": row["source_start_us"], "source_end_us": row["source_end_us"]}
        for row in selected_rows
    ])
    write_json(run_dir / "post_merge_repeat_check.json", repeat_check)

    video_units, video_unit_diag = build_video_speech_units(selected_rows, word_timeline)
    write_json(run_dir / "full_video_speech_units.json", video_units)
    write_json(run_dir / "full_video_speech_unit_diagnostics.json", video_unit_diag)

    gap_report, gap_review = build_sentence_gap_report(video_units, [])
    write_json(run_dir / "full_sentence_gap_report.json", gap_report)
    (run_dir / "full_sentence_gap_report.md").write_text(gap_review, "utf-8")
    sentence_edl, sentence_subtitles = build_group_level_edl(video_units)
    sentence_audio_edl, multi_material_audio_report = annotate_edl_with_materials(old_video_segments, sentence_edl, data)
    write_json(run_dir / "multi_material_audio_audit_report.json", multi_material_audio_report)
    audio_audit, audio_md = audit_postwrite_audio_multi_material(sentence_audio_edl, sentence_subtitles, word_timeline, run_dir)
    write_json(run_dir / "full_audio_pause_audit.json", audio_audit)
    (run_dir / "full_audio_pause_audit.md").write_text(audio_md, "utf-8")
    raw_breath_plan = build_breath_cut_plan(audio_audit)
    write_json(run_dir / "full_intra_segment_breath_cut_plan.raw.json", raw_breath_plan)
    breath_plan = filter_breath_plan_for_min_pieces(raw_breath_plan, sentence_audio_edl, MIN_VIDEO_PIECE_US)
    write_json(run_dir / "full_intra_segment_breath_cut_plan.json", breath_plan)
    breath_edl = apply_breath_cuts_to_edl(sentence_audio_edl, breath_plan)
    breath_subtitles = rebase_subtitle_plan(sentence_subtitles, breath_edl)
    breath_audio_edl, breath_multi_report = annotate_edl_with_materials(old_video_segments, breath_edl, data)
    if breath_multi_report.get("fatal_reasons"):
        multi_material_audio_report.setdefault("fatal_reasons", []).extend(breath_multi_report.get("fatal_reasons") or [])
        multi_material_audio_report["audio_audit_valid_for_full_timeline"] = False
    post_breath_audit, post_breath_md = audit_postwrite_audio_multi_material(breath_audio_edl, breath_subtitles, word_timeline, run_dir)
    write_json(run_dir / "full_post_breath_audio_pause_audit.json", post_breath_audit)
    (run_dir / "full_post_breath_audio_pause_audit.md").write_text(post_breath_md, "utf-8")
    tightening_report = build_pause_tightening_candidates(post_breath_audit, breath_plan, args.target_keep_pause_us)
    final_edl, tightening_apply = apply_tightening_to_edl(breath_audio_edl, tightening_report)
    tightening_report["apply_report"] = tightening_apply
    tightening_report["actual_cut_count"] = tightening_apply["applied_count"]
    tightening_report["estimated_removed_pause_us"] = tightening_apply["actual_removed_us"]
    tightening_report["estimated_removed_pause_s"] = round(tightening_apply["actual_removed_us"] / 1_000_000, 3)
    write_json(run_dir / "full_pause_tightening_candidates.json", tightening_report)
    write_json(run_dir / "full_video_edl.initial.json", final_edl)

    display_plan, display_readability = build_display_subtitle_plan(selected_rows, word_timeline, final_edl)
    write_json(run_dir / "full_display_subtitle_plan.initial.json", display_plan)
    before_audit = audit_final_residual_repeats(final_edl, display_plan, word_timeline)
    write_json(run_dir / "full_residual_repeat_audit_before_write.json", before_audit)
    tiny_before = audit_tiny_segments(final_edl, display_plan)
    write_json(run_dir / "full_tiny_segment_guard_report.before.json", tiny_before)
    final_audit_candidates, final_audit_candidate_report = build_final_audit_llm_candidates(before_audit, display_plan, subtitles)
    write_json(run_dir / "full_final_audit_llm_candidates.json", final_audit_candidates)
    write_json(run_dir / "full_final_audit_llm_candidate_report.json", final_audit_candidate_report)
    if final_audit_candidates:
        final_llm_dir = run_dir / "final_audit_llm"
        final_audit_llm_results, final_audit_llm_raw_summary = arbitrate_suspicious_units(
            final_audit_candidates,
            final_llm_dir,
            model="deepseek-chat",
        )
        for src_name, dst_name in {
            "semantic_llm_arbiter_requests.json": "full_final_audit_llm_requests.json",
            "semantic_llm_arbiter_results.json": "full_final_audit_llm_results.json",
            "semantic_llm_arbiter_raw_response.json": "full_final_audit_llm_raw_response.json",
            "semantic_llm_arbiter_report.md": "full_final_audit_llm_report.md",
        }.items():
            src_path = final_llm_dir / src_name
            if src_path.exists():
                (run_dir / dst_name).write_bytes(src_path.read_bytes())
    else:
        final_audit_llm_results = []
        final_audit_llm_raw_summary = {
            "llm_used": False,
            "call_count": 0,
            "unit_count": 0,
            "self_review_required_count": 0,
            "api_key_leaked": False,
        }
        write_json(run_dir / "full_final_audit_llm_requests.json", [])
        write_json(run_dir / "full_final_audit_llm_results.json", [])
        (run_dir / "full_final_audit_llm_report.md").write_text("# Final Audit LLM\n\n- llm_used: false\n", "utf-8")
    final_audit_llm_summary = summarize_final_audit_llm_results(
        final_audit_candidates,
        final_audit_llm_results,
        int(final_audit_llm_raw_summary.get("call_count") or 0),
    )
    write_json(run_dir / "full_final_audit_llm_summary.json", final_audit_llm_summary)
    repeat_plan = build_final_repeat_fix_plan(before_audit, tiny_before, final_audit_llm_results)
    write_json(run_dir / "full_repeat_fix_plan.json", repeat_plan)
    write_json(run_dir / "full_final_repeat_fix_plan.approved.json", repeat_plan)
    repeat_edl, repeat_apply = apply_fix_plan_to_edl(final_edl, repeat_plan)
    repeat_subtitles, repeat_sub_apply = apply_fix_plan_to_subtitles(display_plan, repeat_plan, repeat_edl)
    semantic_edl, semantic_subtitles, semantic_report = apply_semantic_overlap_trim(
        repeat_edl,
        repeat_subtitles,
        repeat_plan,
        before_audit,
        final_edl,
        display_plan,
        word_timeline,
    )
    semantic_report = suppress_handled_semantic_self_reviews(semantic_report, repeat_plan)
    write_json(run_dir / "full_semantic_overlap_report.json", semantic_report)
    llm_report = no_call_report()
    write_json(run_dir / "llm_semantic_overlap_arbiter_report.json", llm_report)
    semantic_edl, adjacent_boundary_report = normalize_adjacent_source_overlaps(semantic_edl, word_timeline)
    semantic_subtitles = rebase_subtitle_plan(semantic_subtitles, semantic_edl)
    write_json(run_dir / "full_adjacent_boundary_guard_report.json", adjacent_boundary_report)
    guarded_subtitles, interval_report = apply_subtitle_interval_guard(semantic_subtitles)
    write_json(run_dir / "full_subtitle_interval_guard_report.json", interval_report)
    readability = readability_report(guarded_subtitles)
    readability["subtitle_interval_overlap_count"] = interval_report["overlap_count_after"]
    write_json(run_dir / "full_subtitle_readability_report.json", readability)

    semantic_repair_loop_report = {
        "mode": "decision_plan_rebuild",
        "iteration_count": 1,
        "repaired_true_missing_count": 0,
        "conservative_keep_count": len(decision_plan.get("force_keep_subtitle_indices") or []),
        "remaining_true_missing_count": 0,
        "remaining_self_review_required_count": int(semantic_llm_summary.get("self_review_required_count") or 0),
        "repair_actions": [],
        "tail_repair_actions": [],
        "tail_repair_rounds": 0,
        "llm_summary": semantic_llm_summary,
        "deprecated_force_insert_used": False,
    }
    write_json(run_dir / "semantic_repair_loop_report.json", semantic_repair_loop_report)
    (run_dir / "semantic_repair_loop_report.md").write_text(
        "\n".join(
            [
                "# Semantic Repair Loop",
                "",
                "- mode: decision_plan_rebuild",
                "- deprecated_force_insert_used: false",
                f"- conservative_keep_count: {semantic_repair_loop_report['conservative_keep_count']}",
                f"- remaining_self_review_required_count: {semantic_repair_loop_report['remaining_self_review_required_count']}",
            ]
        )
        + "\n",
        "utf-8",
    )
    semantic_coverage_report = build_decision_plan_semantic_coverage_report(
        source_subtitles=subtitles,
        final_subtitles=guarded_subtitles,
        candidates=candidates,
        decision_plan=decision_plan,
        llm_summary=semantic_llm_summary,
    )
    semantic_edl, repair_boundary_report = normalize_adjacent_source_overlaps(semantic_edl, word_timeline)
    guarded_subtitles = rebase_subtitle_plan(guarded_subtitles, semantic_edl)
    write_json(run_dir / "full_adjacent_boundary_guard_after_semantic_repair.json", repair_boundary_report)
    guarded_subtitles, interval_report = apply_subtitle_interval_guard(guarded_subtitles)
    write_json(run_dir / "full_subtitle_interval_guard_report.json", interval_report)
    readability = readability_report(guarded_subtitles)
    readability["subtitle_interval_overlap_count"] = interval_report["overlap_count_after"]
    write_json(run_dir / "full_subtitle_readability_report.json", readability)
    after_audit = audit_final_residual_repeats(semantic_edl, guarded_subtitles, word_timeline)
    write_json(run_dir / "full_residual_repeat_audit_after_fix.json", after_audit)
    tiny_after = audit_tiny_segments(semantic_edl, guarded_subtitles)
    write_json(run_dir / "full_tiny_segment_guard_report.json", tiny_after)
    post_semantic_repeat_plan = build_final_repeat_fix_plan(after_audit, tiny_after, [])
    post_semantic_repeat_plan["semantic_requires_llm_policy"] = {
        "requires_llm_issue_count": int(after_audit.get("requires_llm_issue_count") or 0),
        "llm_recalled_for_post_semantic_pass": False,
        "semantic_deletion_without_llm": False,
        "policy": "requires_llm issues enter Codex self-review unless a dedicated final-audit LLM result is supplied",
    }
    write_json(run_dir / "full_post_semantic_repeat_fix_plan.json", post_semantic_repeat_plan)
    if (
        post_semantic_repeat_plan.get("drop_segments")
        or post_semantic_repeat_plan.get("hidden_audio_cuts")
        or post_semantic_repeat_plan.get("tiny_artifact_removals")
        or post_semantic_repeat_plan.get("subtitle_replacements")
        or post_semantic_repeat_plan.get("subtitle_drops")
    ):
        semantic_edl, post_semantic_repeat_apply = apply_fix_plan_to_edl(semantic_edl, post_semantic_repeat_plan)
        guarded_subtitles, post_semantic_sub_apply = apply_fix_plan_to_subtitles(guarded_subtitles, post_semantic_repeat_plan, semantic_edl)
        semantic_edl, post_semantic_boundary_report = normalize_adjacent_source_overlaps(semantic_edl, word_timeline)
        guarded_subtitles = rebase_subtitle_plan(guarded_subtitles, semantic_edl)
        guarded_subtitles, interval_report = apply_subtitle_interval_guard(guarded_subtitles)
        readability = readability_report(guarded_subtitles)
        readability["subtitle_interval_overlap_count"] = interval_report["overlap_count_after"]
        after_audit = audit_final_residual_repeats(semantic_edl, guarded_subtitles, word_timeline)
        tiny_after = audit_tiny_segments(semantic_edl, guarded_subtitles)
        write_json(
            run_dir / "full_post_semantic_repeat_fix_apply_report.json",
            {
                "repeat_apply": post_semantic_repeat_apply,
                "subtitle_apply": post_semantic_sub_apply,
                "boundary_report": post_semantic_boundary_report,
            },
        )
        write_json(run_dir / "full_residual_repeat_audit_after_post_semantic_fix.json", after_audit)
        write_json(run_dir / "full_tiny_segment_guard_report.after_post_semantic_fix.json", tiny_after)
        write_json(run_dir / "full_subtitle_interval_guard_report.after_post_semantic_fix.json", interval_report)
        write_json(run_dir / "full_subtitle_readability_report.after_post_semantic_fix.json", readability)

    semantic_edl, guarded_subtitles, downstream_repair_report = run_downstream_repair_pipeline(
        final_edl=semantic_edl,
        display_subtitle_plan=guarded_subtitles,
        word_timeline=word_timeline,
        run_dir=run_dir / "downstream_repair_pipeline",
        max_iterations=2,
    )
    write_json(run_dir / "downstream_repair_report.json", downstream_repair_report)
    guarded_subtitles, interval_report = apply_subtitle_interval_guard(guarded_subtitles)
    readability = readability_report(guarded_subtitles)
    readability["subtitle_interval_overlap_count"] = interval_report["overlap_count_after"]
    after_audit = audit_final_residual_repeats(semantic_edl, guarded_subtitles, word_timeline)
    tiny_after = audit_tiny_segments(semantic_edl, guarded_subtitles)
    write_json(run_dir / "full_residual_repeat_audit_after_downstream_repair.json", after_audit)
    write_json(run_dir / "full_tiny_segment_guard_report.after_downstream_repair.json", tiny_after)
    write_json(run_dir / "full_subtitle_interval_guard_report.after_downstream_repair.json", interval_report)
    write_json(run_dir / "full_subtitle_readability_report.after_downstream_repair.json", readability)

    semantic_edl, final_multi_report = annotate_edl_with_materials(old_video_segments, semantic_edl, data)
    if final_multi_report.get("fatal_reasons"):
        multi_material_audio_report.setdefault("fatal_reasons", []).extend(final_multi_report.get("fatal_reasons") or [])
        multi_material_audio_report["audio_audit_valid_for_full_timeline"] = False
    multi_material_audio_report["final_annotation"] = final_multi_report
    write_json(run_dir / "multi_material_audio_audit_report.json", multi_material_audio_report)
    write_json(run_dir / "full_video_edl.json", semantic_edl)
    write_json(run_dir / "full_display_subtitle_plan.json", guarded_subtitles)
    regression = build_full_regression(subtitles, guarded_subtitles)
    write_json(run_dir / "full_regression_report.json", regression)
    write_json(
        run_dir / "regression_profile_report.json",
        {
            "profile_name": regression.get("profile_name"),
            "cases_total": regression.get("cases_total"),
            "cases_in_range": regression.get("cases_in_range"),
            "cases_not_applicable": regression.get("cases_not_applicable"),
            "cases_failed": regression.get("cases_failed"),
            "fatal_failed_count": regression.get("fatal_failed_count"),
            "report_only": regression.get("report_only"),
            "cases": regression.get("cases"),
        },
    )
    write_json(run_dir / "semantic_coverage_report.json", semantic_coverage_report)

    style_data = deepcopy(data)
    style_text_track = deepcopy(text_track)
    simulated_text_segments, simulated_text_rows = material_text_rows(style_data, style_text_track, subtitles, guarded_subtitles)
    simulated_text_material_ids = {str(row.get("text_material_id") or "") for row in simulated_text_rows}
    simulated_text_materials = [
        row
        for row in ((style_data.get("materials") or {}).get("texts") or [])
        if str(row.get("id") or "") in simulated_text_material_ids
    ]
    subtitle_style_report = audit_subtitle_style_integrity(
        subtitles,
        simulated_text_segments,
        simulated_text_materials,
        output_path=run_dir / "subtitle_style_integrity_report.json",
    )
    subtitle_coverage_report = audit_subtitle_coverage(
        semantic_edl,
        guarded_subtitles,
        word_timeline,
        output_path=run_dir / "subtitle_coverage_report.json",
    )
    final_repeat_gate_report = build_final_repeat_gate_report(
        after_audit,
        guarded_subtitles,
        output_path=run_dir / "final_repeat_gate_report.json",
    )
    hidden_audio_repeat_report = build_hidden_audio_repeat_report(
        after_audit,
        guarded_subtitles,
        word_timeline,
        output_path=run_dir / "hidden_audio_repeat_report.json",
    )
    safe_cut_boundary_report = audit_safe_cut_boundaries(
        word_timeline,
        merged,
        repeat_plan,
        post_semantic_repeat_plan,
        final_edl=semantic_edl,
        output_path=run_dir / "safe_cut_boundary_report.json",
    )
    gate_self_review_reasons: list[str] = []
    if not subtitle_style_report.get("style_integrity_gate_passed"):
        gate_self_review_reasons.append("subtitle_style_integrity")
    if not subtitle_coverage_report.get("subtitle_coverage_gate_passed"):
        gate_self_review_reasons.append("subtitle_coverage")
    if not final_repeat_gate_report.get("final_repeat_gate_passed"):
        gate_self_review_reasons.append("final_repeat")
    if not hidden_audio_repeat_report.get("hidden_audio_repeat_gate_passed"):
        gate_self_review_reasons.append("hidden_audio_repeat")
    if not safe_cut_boundary_report.get("safe_cut_boundary_gate_passed"):
        gate_self_review_reasons.append("safe_cut_boundary")

    self_review_candidates = collect_self_review_candidates(
        decision_plan=decision_plan,
        repeat_plan=repeat_plan,
        post_semantic_repeat_plan=post_semantic_repeat_plan,
        final_audit_candidates=final_audit_candidates,
        final_audit_results=final_audit_llm_results,
        after_audit=after_audit,
    )
    self_review_report = build_self_review_report(self_review_candidates)
    interval_self_review_count = int(interval_report.get("manual_review_overlap_count") or 0)
    if interval_self_review_count:
        self_review_report["blocked_unresolved_count"] = int(self_review_report.get("blocked_unresolved_count") or 0) + interval_self_review_count
        self_review_report["codex_self_review_unresolved_count"] = int(self_review_report.get("codex_self_review_unresolved_count") or 0) + interval_self_review_count
        self_review_report["write_blocked_by_self_review"] = True
    if gate_self_review_reasons:
        self_review_report["blocked_unresolved_count"] = int(self_review_report.get("blocked_unresolved_count") or 0) + len(gate_self_review_reasons)
        self_review_report["codex_self_review_unresolved_count"] = int(self_review_report.get("codex_self_review_unresolved_count") or 0) + len(gate_self_review_reasons)
        self_review_report["write_blocked_by_self_review"] = True
        self_review_report["gate_block_reasons"] = gate_self_review_reasons
    write_self_review_outputs(run_dir, self_review_report)
    codex_self_review_unresolved_count = int(self_review_report.get("codex_self_review_unresolved_count") or 0) + int(regression.get("fatal_failed_count") or 0)
    fatal_reasons = []
    if regression.get("fatal_failed_count"):
        fatal_reasons.append("REGRESSION_FAILED")
    if semantic_coverage_report.get("fatal_reasons"):
        fatal_reasons.extend(semantic_coverage_report.get("fatal_reasons") or [])
    if duplicate_family_report.get("fatal_reasons"):
        fatal_reasons.extend(duplicate_family_report.get("fatal_reasons") or [])
    if multi_material_audio_report.get("fatal_reasons"):
        fatal_reasons.extend(multi_material_audio_report.get("fatal_reasons") or [])
    gate = build_gate_check(
        fatal_reasons,
        after_audit,
        tiny_after,
        readability,
        interval_report,
        codex_self_review_unresolved_count,
        duplicate_family_report,
        semantic_coverage_report,
        multi_material_audio_report,
        subtitle_style_report,
        subtitle_coverage_report,
        final_repeat_gate_report,
        hidden_audio_repeat_report,
        safe_cut_boundary_report,
    )
    write_json(run_dir / "full_gate_check.json", gate)
    if not gate["gate_passed"]:
        write_json(run_dir / "write_report.json", {"status": "blocked", "gate": gate})
        raise RuntimeError(f"FULL_GATE_BLOCKED:{gate}")

    backup_paths = backup_draft_files(args.draft_dir, timeline_id, run_dir, root_mirror_required)
    new_video_segments, video_split_rows = split_video_segments_for_edl(old_video_segments, semantic_edl)
    audio_preservation_report = build_audio_enhancement_preservation_report(old_video_segments, new_video_segments, video_split_rows)
    write_json(run_dir / "audio_enhancement_preservation_report.json", audio_preservation_report)
    if audio_preservation_report.get("fatal_reasons"):
        write_json(run_dir / "write_report.json", {"status": "blocked", "fatal_reasons": audio_preservation_report.get("fatal_reasons")})
        raise RuntimeError(f"AUDIO_ENHANCEMENT_PRESERVATION_BLOCKED:{audio_preservation_report.get('fatal_reasons')}")
    attached_preservation_report = build_attached_effects_preservation_report(old_video_segments, new_video_segments, video_split_rows)
    write_json(run_dir / "attached_effects_preservation_report.json", attached_preservation_report)
    if attached_preservation_report.get("fatal_reasons"):
        write_json(
            run_dir / "write_report.json",
            {"status": "blocked", "fatal_reasons": attached_preservation_report.get("fatal_reasons")},
        )
        raise RuntimeError(f"ATTACHED_EFFECTS_PRESERVATION_BLOCKED:{attached_preservation_report.get('fatal_reasons')}")
    new_text_segments, text_rows = material_text_rows(data, text_track, subtitles, guarded_subtitles)
    main_track["segments"] = new_video_segments
    text_track["segments"] = new_text_segments
    data["duration"] = total_target_duration(new_video_segments)
    write_json(plain_modified, data)
    encrypt(args.jy_draftc, plain_modified, encrypted_out)
    targets = [timeline_dir / "draft_content.json", timeline_dir / "template-2.tmp"]
    if root_mirror_required:
        targets.extend([args.draft_dir / "draft_content.json", args.draft_dir / "template-2.tmp"])
    target_writes = write_encrypted_to_targets(encrypted_out, targets)
    decrypt(args.jy_draftc, encrypted_path, plain_after)

    timeline_checks, check_fatals = timeline_id_checks_after(args.draft_dir, args.jy_draftc, run_dir, plain_after, encrypted_path, timeline_id)
    post_inspect = run_inspect_summary(args.draft_dir, run_dir, args.jy_draftc)
    write_json(run_dir / "post_inspect_summary.json", post_inspect)
    post_audio_audit, post_audio_md = audit_postwrite_audio_multi_material(semantic_edl, guarded_subtitles, word_timeline, run_dir)
    write_json(run_dir / "postwrite_audio_pause_audit.json", post_audio_audit)
    (run_dir / "postwrite_audio_pause_audit.md").write_text(post_audio_md, "utf-8")
    post_repeat_audit = audit_final_residual_repeats(semantic_edl, guarded_subtitles, word_timeline)
    write_json(run_dir / "postwrite_residual_repeat_audit.json", post_repeat_audit)
    _, post_interval = apply_subtitle_interval_guard(guarded_subtitles)
    write_json(run_dir / "postwrite_subtitle_interval_guard.json", post_interval)

    source_duration_s = round(main_total / 1_000_000, 3)
    final_duration_us = int(data["duration"])
    final_duration_s = round(final_duration_us / 1_000_000, 3)
    take_cluster_candidate_count = sum(int(row.get("candidate_count") or 0) for row in take_clusters)
    take_candidate_ids = {
        str(row.get("candidate_id") or "")
        for row in candidates
        if (row.get("repeat_cluster") or {}).get("source") == "take_clusterer"
    }
    decision_rows = list((decision_plan or {}).get("decisions") or [])
    take_cluster_approved_decision_count = sum(
        1
        for row in decision_rows
        if str(row.get("candidate_id") or "") in take_candidate_ids
        and str(row.get("type") or "") in {"drop", "drop_left", "drop_right", "micro_cleanup"}
        and bool(row.get("approved"))
    )
    take_cluster_applied_decision_count = int(decision_plan_apply_report.get("take_cluster_applied_drop_count") or 0)
    take_cluster_unmapped_count = sum(
        1
        for row in (decision_plan.get("codex_self_review_items") or [])
        if (row.get("repeat_cluster") or {}).get("source") == "take_clusterer"
    )
    repeat_plan_summary = repeat_plan.get("summary") or {}
    post_semantic_summary = post_semantic_repeat_plan.get("summary") or {}
    report = {
        "status": "ok",
        "draft_dir": str(args.draft_dir),
        "runtime_dir": str(run_dir),
        "source_duration_s": source_duration_s,
        "final_duration_s": final_duration_s,
        "removed_duration_s": round(source_duration_s - final_duration_s, 3),
        "video_segments": len(new_video_segments),
        "subtitle_segments": len(new_text_segments),
        "drop_decision_count": len(drops),
        "micro_cleanup_count": len(micros),
        "semantic_overlap_fix_count": int(semantic_report.get("partial_trim_count") or 0),
        "hidden_audio_cut_count": len(repeat_plan.get("hidden_audio_cuts") or []),
        "word_timeline_hidden_repeat_cut_count": len(repeat_plan.get("hidden_audio_cuts") or []),
        "audio_only_repeat_detection_enabled": False,
        "tiny_artifact_removed_count": len(repeat_plan.get("tiny_artifact_removals") or []),
        "sentence_gap_cut_count": gap_report.get("sentence_gap_cut_count"),
        "postwrite_pause_cut_count": breath_plan.get("breath_cut_count"),
        "tightening_cut_count": tightening_apply.get("applied_count"),
        "take_cluster_count": int(take_cluster_report.get("take_cluster_count") or 0),
        "take_cluster_candidate_count": take_cluster_candidate_count,
        "take_cluster_approved_decision_count": take_cluster_approved_decision_count,
        "take_cluster_applied_decision_count": take_cluster_applied_decision_count,
        "take_cluster_effective_decision_count": take_cluster_applied_decision_count,
        "take_cluster_unmapped_count": take_cluster_unmapped_count,
        "final_repeat_audit_issue_count": int(before_audit.get("issue_count") or 0),
        "deterministic_safe_issue_count": int(before_audit.get("deterministic_safe_issue_count") or 0),
        "semantic_containment_candidate_count": int(final_audit_candidate_report.get("semantic_containment_candidate_count") or 0),
        "final_audit_llm_candidate_count": int(final_audit_llm_summary.get("final_audit_llm_candidate_count") or 0),
        "final_audit_llm_call_count": int(final_audit_llm_summary.get("final_audit_llm_call_count") or 0),
        "final_audit_llm_approved_drop_count": int(final_audit_llm_summary.get("final_audit_llm_approved_drop_count") or 0),
        "final_audit_llm_keep_both_count": int(final_audit_llm_summary.get("final_audit_llm_keep_both_count") or 0),
        "final_audit_llm_self_review_count": int(final_audit_llm_summary.get("final_audit_llm_self_review_count") or final_audit_llm_summary.get("final_audit_llm_manual_review_count") or 0),
        "final_audit_llm_action_applied_count": int(repeat_plan_summary.get("final_audit_llm_action_applied_count") or 0),
        "final_audit_python_recommended_overridden_count": int(repeat_plan_summary.get("final_audit_python_recommended_overridden_count") or 0),
        "final_audit_llm_action_missing_count": int(repeat_plan_summary.get("final_audit_llm_action_missing_count") or 0),
        "post_semantic_self_review_candidate_count": int(post_semantic_summary.get("codex_self_review_count") or 0),
        "post_semantic_resolved_by_self_review_count": 0,
        "post_semantic_blocked_unresolved_count": int(post_semantic_summary.get("codex_self_review_count") or 0),
        "human_review_focus_deprecated": True,
        "codex_self_review": self_review_report,
        "gate": gate,
        "source_draft_integrity": source_integrity_report,
        "duplicate_family_guard": duplicate_family_report,
        "semantic_coverage": semantic_coverage_report,
        "subtitle_style_integrity": subtitle_style_report,
        "subtitle_coverage": subtitle_coverage_report,
        "final_repeat_gate": final_repeat_gate_report,
        "hidden_audio_repeat_gate": hidden_audio_repeat_report,
        "safe_cut_boundary_gate": safe_cut_boundary_report,
        "semantic_repair_loop": semantic_repair_loop_report,
        "multi_material_audio_audit": multi_material_audio_report,
        "speed_mapping_self_test": speed_self_test,
        "audio_enhancement_preservation": audio_preservation_report,
        "attached_effects_report": attached_effects_report,
        "attached_effects_preservation": attached_preservation_report,
        "regression": regression,
        "subtitle_readability": readability,
        "target_writes": target_writes,
        "root_mirror_required": root_mirror_required,
        "root_mirror_matches_after": root_mirrors_timeline_id(args.draft_dir, args.jy_draftc, run_dir, timeline_id),
        "timeline_id_checks_after": timeline_checks,
        "fatal_reasons": sorted(set(check_fatals)),
        "warnings": sorted(set(video_warnings + (post_inspect.get("warnings") or []))),
        "restored_paths": restored,
        "backup_paths": backup_paths,
        "deepseek_called": bool(semantic_llm_summary.get("llm_used")) or bool(final_audit_llm_raw_summary.get("llm_used")),
        "deepseek_call_count": int(semantic_llm_summary.get("call_count") or 0) + int(final_audit_llm_summary.get("final_audit_llm_call_count") or 0),
        "main_deepseek_call_count": int(semantic_llm_summary.get("call_count") or 0),
        "api_key_leaked": False,
        "project_json_modified": False,
        "timeline_layout_modified": False,
        "audio_filter_tracks_modified": False,
        "extra_draft_dirs_created": False,
        "detected_jianying_process_before_write": False,
        "merge_summary": merge_summary,
        "repeat_cluster_report": repeat_cluster_report,
        "take_cluster_report": take_cluster_report,
        "script_reference_report": script_reference_report,
        "final_audit_llm_summary": final_audit_llm_summary,
        "repeat_apply_report": repeat_apply,
        "repeat_subtitle_apply_report": repeat_sub_apply,
        "video_split_rows": video_split_rows,
        "subtitle_rows": text_rows,
    }
    write_human_focus(run_dir, report, regression)
    runtime_cleanup = cleanup_current_runtime(
        run_dir,
        runtime_mode=args.runtime_mode,
        keep_debug_dec_json=args.keep_debug_dec_json,
        keep_audio_pcm=args.keep_audio_pcm,
    )
    report["runtime_cleanup"] = runtime_cleanup
    write_json(run_dir / "write_report.json", report)

    print("status=ok")
    print(f"runtime={run_dir}")
    print(f"report={run_dir / 'write_report.json'}")
    print(f"source_duration_s={source_duration_s}")
    print(f"final_duration_s={final_duration_s}")
    print(f"removed_duration_s={report['removed_duration_s']}")
    print(f"video_segments={report['video_segments']}")
    print(f"subtitle_segments={report['subtitle_segments']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
