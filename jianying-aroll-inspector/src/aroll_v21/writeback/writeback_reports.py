from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from aroll_v21.ingest.real_draft_adapter import RealDraftIngestResult
from aroll_v21.ir.models import RunReport
from aroll_v21.validate.rough_cut_quality import build_rough_cut_quality_metrics
from aroll_v21.writeback.source_segment_template_resolver import SOURCE_TEMPLATE_REPORT_DEFAULTS


TimerangeFunc = Callable[[Any], int]


def _finalize_post_write_actual_draft_audit(audit: dict[str, Any]) -> dict[str, Any]:
    failures = list(audit.get("failure_reasons") or [])
    passed = bool(audit.get("executed")) and not failures
    audit["gate_passed"] = passed
    blocker_codes = list(audit.get("blocker_codes") or [])
    if not passed:
        blocker_codes.append("V21_POST_WRITE_ACTUAL_DRAFT_AUDIT_FAILED")
    audit["blocker_codes"] = [] if passed else _unique_strings(blocker_codes)
    audit["post_write_actual_draft_audit_executed"] = bool(audit.get("executed"))
    audit["post_write_actual_draft_audit_gate_passed"] = passed
    audit["post_write_actual_draft_audit_blocker_codes"] = list(audit.get("blocker_codes") or [])
    return audit


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "")
        if text and text not in result:
            result.append(text)
    return result


def _flatten_post_write_actual_draft_audit(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "post_write_actual_draft_audit_required_on_commit": True,
        "post_write_actual_draft_audit_executed": bool(audit.get("executed")),
        "post_write_actual_draft_audit_gate_passed": bool(audit.get("gate_passed")),
        "post_write_actual_draft_audit_blocker_codes": list(audit.get("blocker_codes") or []),
        "post_write_actual_draft_audit_failure_reasons": list(audit.get("failure_reasons") or []),
        "post_write_actual_draft_loaded": bool(audit.get("actual_draft_loaded")),
        "post_write_actual_draft_source": str(audit.get("actual_draft_source") or ""),
        "post_write_actual_video_rows_match_plan": bool(audit.get("actual_video_rows_match_plan")),
        "post_write_actual_caption_rows_match_plan": bool(audit.get("actual_caption_rows_match_plan")),
        "post_write_expected_caption_rows_present": bool(audit.get("expected_caption_rows_present")),
        "post_write_actual_has_no_extra_caption_like_text_segments": bool(audit.get("actual_has_no_extra_caption_like_text_segments")),
        "post_write_actual_caption_rows_exact_match_plan": bool(audit.get("actual_caption_rows_exact_match_plan")),
        "post_write_actual_text_residue_gate_passed": bool(audit.get("actual_text_residue_gate_passed")),
        "post_write_actual_audio_coverage_gate_passed": bool(audit.get("actual_audio_coverage_gate_passed")),
        "post_write_actual_visible_text_repeat_gate_passed": bool(audit.get("actual_visible_text_repeat_gate_passed")),
        "post_write_actual_text_segment_count": int(audit.get("actual_text_segment_count") or 0),
        "post_write_generated_caption_segment_count": int(audit.get("generated_caption_segment_count") or 0),
        "post_write_preserved_non_subtitle_count": int(audit.get("preserved_non_subtitle_count") or 0),
        "post_write_old_subtitle_residue_count": int(audit.get("old_subtitle_residue_count") or 0),
        "post_write_orphan_text_segment_count": int(audit.get("orphan_text_segment_count") or 0),
        "post_write_text_after_final_video_end_count": int(audit.get("text_after_final_video_end_count") or 0),
        "post_write_floating_caption_count": int(audit.get("floating_caption_count") or 0),
        "post_write_audio_coverage_failure_count": int(audit.get("audio_coverage_failure_count") or 0),
        "post_write_heard_but_uncaptioned_word_count": int(audit.get("heard_but_uncaptioned_word_count") or 0),
        "post_write_dropped_but_reintroduced_word_count": int(audit.get("dropped_but_reintroduced_word_count") or 0),
        "post_write_actual_visible_repeat_candidate_count": int(audit.get("actual_visible_repeat_candidate_count") or 0),
        "final_video_end_us": int(audit.get("final_video_end_us") or 0),
        "max_caption_end_us": int(audit.get("max_caption_end_us") or 0),
        "captions_after_final_video_end_count": int(audit.get("captions_after_final_video_end_count") or 0),
        "post_write_video_target_gap_count_gt_300ms": int(audit.get("post_write_video_target_gap_count_gt_300ms") or 0),
        "post_write_total_video_target_gap_us": int(audit.get("post_write_total_video_target_gap_us") or 0),
        "caption_video_drift_count": int(audit.get("caption_video_drift_count") or 0),
        "max_caption_video_drift_us": int(audit.get("max_caption_video_drift_us") or 0),
        "split_caption_container_mismatch_count": int(audit.get("split_caption_container_mismatch_count") or 0),
        "caption_crosses_video_split_gap_count": int(audit.get("caption_crosses_video_split_gap_count") or 0),
        "caption_words_not_covered_by_actual_video_count": int(audit.get("caption_words_not_covered_by_actual_video_count") or 0),
        "jianying_canonical_timeline_sync_gate_passed": bool(audit.get("jianying_canonical_timeline_sync_gate_passed")),
        "post_write_actual_effective_speed_gate_passed": bool(audit.get("actual_effective_speed_gate_passed")),
        "post_write_actual_visual_pacing_gate_passed": bool(audit.get("actual_visual_pacing_gate_passed")),
        "post_write_actual_caption_gui_readability_gate_passed": bool(audit.get("actual_caption_gui_readability_gate_passed")),
        "post_write_actual_final_caption_visible_repeat_gate_passed": bool(audit.get("actual_final_caption_visible_repeat_gate_passed")),
        "post_write_actual_caption_alignment_gate_passed": bool(audit.get("actual_caption_alignment_gate_passed")),
    }


def _base_report(
    *,
    draft_dir: Path | None,
    real_draft_result: RealDraftIngestResult,
    writeback_attempted: bool,
    sacrificial_write_override_used: bool,
) -> dict[str, Any]:
    metadata = real_draft_result.metadata or {}
    timeline_dir = Path(str(metadata.get("timeline_dir") or "")) if metadata.get("timeline_dir") else None
    draft_content_path = Path(str(metadata.get("draft_content_path") or "")) if metadata.get("draft_content_path") else None
    template_path = Path(str(metadata.get("template_path") or "")) if metadata.get("template_path") else None
    return {
        "writeback_attempted": bool(writeback_attempted),
        "writeback_success": False,
        "commit_performed": False,
        "encrypt_success": False,
        "WRITE_SUCCESS": False,
        "ENCRYPT_SUCCESS": False,
        "draft_dir": str(draft_dir or ""),
        "timeline_id": str(metadata.get("timeline_id") or ""),
        "timeline_dir": str(timeline_dir or ""),
        "draft_content_path": str(draft_content_path or ""),
        "template_path": str(template_path or ""),
        "target_writes": {},
        "selected_text_track_id": None,
        "selected_video_track_id": None,
        "sacrificial_write_override_used": bool(sacrificial_write_override_used),
        "postwrite_decrypt_skipped_for_sacrificial_draft": bool(sacrificial_write_override_used),
        "borrowed_v20_low_level_io_reference": True,
        **SOURCE_TEMPLATE_REPORT_DEFAULTS,
    }


def _writeback_rough_cut_quality(
    data: dict[str, Any],
    run_report: RunReport,
    *,
    selected_text_track_id: str,
    subtitle_track_ids: set[str],
    old_subtitle_material_ids: set[str],
    preserved_non_subtitle_text_segment_count: int,
    visible_text_rows: Callable[[dict[str, Any]], list[dict[str, Any]]],
    classified_actual_text_rows: Callable[..., list[dict[str, Any]]],
    template_candidate_material_ids: Callable[[RunReport], set[str]],
    is_text_track: Callable[[dict[str, Any]], bool],
    overlap_count: Callable[[list[dict[str, Any]]], int],
) -> dict[str, Any]:
    new_caption_material_ids = {
        str(row.get("id") or "")
        for row in run_report.material_write_plan.get("materials") or []
        if str(row.get("id") or "")
    }
    visible_caption_track_count = 0
    old_residue_track_ids: set[str] = set()
    overlapping_caption_segments_count = 0
    selected_track_total_segment_count = 0
    selected_canonical_caption_segment_count = 0
    canonical_caption_segment_count = 0
    visible_rows = visible_text_rows(data)
    classified_text_rows = classified_actual_text_rows(
        visible_rows,
        expected_segment_ids={
            str(row.get("id") or "")
            for row in run_report.material_write_plan.get("segments") or []
            if isinstance(row, dict) and str(row.get("id") or "")
        },
        expected_material_ids=new_caption_material_ids,
        template_material_ids=template_candidate_material_ids(run_report),
    )
    residue_text_rows = [row for row in classified_text_rows if row["classification"] == "old_subtitle_residue"]
    for track in data.get("tracks") or []:
        if not isinstance(track, dict) or not is_text_track(track):
            continue
        track_id = str(track.get("id") or "")
        track_segments = [segment for segment in track.get("segments") or [] if isinstance(segment, dict)]
        caption_segments = [
            segment
            for segment in track_segments
            if str(segment.get("material_id") or segment.get("materialId") or "") in new_caption_material_ids
        ]
        if caption_segments:
            visible_caption_track_count += 1
        canonical_caption_segment_count += len(caption_segments)
        if track_id == selected_text_track_id:
            selected_track_total_segment_count = len(track_segments)
            selected_canonical_caption_segment_count = len(caption_segments)
        if any(str(segment.get("material_id") or segment.get("materialId") or "") in old_subtitle_material_ids for segment in track_segments) or any(
            str(row.get("track_id") or "") == track_id for row in residue_text_rows
        ):
            old_residue_track_ids.add(track_id)
        overlapping_caption_segments_count += overlap_count(caption_segments)
    metrics = build_rough_cut_quality_metrics(
        final_timeline=run_report.final_timeline,
        captions=run_report.captions,
        material_write_plan=run_report.material_write_plan,
        visible_caption_track_count=visible_caption_track_count,
        old_subtitle_residue_track_count=len(old_residue_track_ids),
        overlapping_caption_segments_count=overlapping_caption_segments_count,
    )
    metrics["canonical_caption_segment_count"] = canonical_caption_segment_count
    metrics["selected_canonical_caption_segment_count"] = selected_canonical_caption_segment_count
    metrics["selected_text_track_total_segment_count"] = selected_track_total_segment_count
    metrics["preserved_non_subtitle_text_segment_count"] = int(preserved_non_subtitle_text_segment_count)
    metrics["old_subtitle_residue_count"] = len(residue_text_rows)
    metrics["non_subtitle_text_tracks_preserved"] = True
    metrics["non_subtitle_text_segments_preserved"] = True
    metrics["selected_canonical_caption_segments_match_captions"] = selected_canonical_caption_segment_count == metrics["caption_count"]
    metrics["canonical_caption_segments_match_captions"] = canonical_caption_segment_count == metrics["caption_count"]
    metrics["selected_track_total_segment_count_allows_non_subtitle"] = selected_track_total_segment_count >= selected_canonical_caption_segment_count
    metrics["selected_canonical_subtitle_track_segment_count"] = selected_canonical_caption_segment_count
    metrics["selected_canonical_subtitle_track_matches_captions"] = metrics["selected_canonical_caption_segments_match_captions"]
    return metrics


def _assert_writeback_rough_cut_quality(metrics: dict[str, Any], *, error_cls) -> None:
    failed_checks: list[str] = []
    final_timeline_count = int(metrics.get("final_timeline_count") or 0)
    caption_count = int(metrics.get("caption_count") or 0)
    material_count = int(metrics.get("material_count") or 0)
    segment_count = int(metrics.get("segment_count") or 0)
    if final_timeline_count <= 0 or caption_count <= 0 or caption_count < final_timeline_count:
        failed_checks.append("video_caption_count_contract")
    if len({caption_count, material_count, segment_count}) != 1:
        failed_checks.append("caption_material_segment_count_mismatch")
    if int(metrics.get("visible_caption_track_count") or 0) != 1:
        failed_checks.append("visible_caption_track_count")
    if int(metrics.get("old_subtitle_residue_track_count") or 0) != 0:
        failed_checks.append("old_subtitle_residue_track_count")
    if int(metrics.get("old_subtitle_residue_count") or 0) != 0:
        failed_checks.append("old_subtitle_residue_count")
    if int(metrics.get("overlapping_caption_segments_count") or 0) != 0:
        failed_checks.append("overlapping_caption_segments_count")
    if int(metrics.get("canonical_caption_segment_count") or 0) != int(metrics.get("caption_count") or 0):
        failed_checks.append("canonical_caption_segment_count")
    if int(metrics.get("selected_canonical_caption_segment_count") or 0) != int(metrics.get("caption_count") or 0):
        failed_checks.append("selected_canonical_caption_segment_count")
    if int(metrics.get("target_gap_count") or 0) != 0:
        failed_checks.append("target_gap_count")
    if int(metrics.get("target_overlap_count") or 0) != 0:
        failed_checks.append("target_overlap_count")
    if failed_checks:
        raise error_cls(
            "V21_WRITEBACK_ROUGH_CUT_QC_FAILED",
            "post-mutation writeback rough-cut QC failed",
            {"rough_cut_quality": metrics, "failed_checks": failed_checks},
        )


def _overlap_count(
    segments: list[dict[str, Any]],
    *,
    timerange_start: TimerangeFunc,
    timerange_duration: TimerangeFunc,
) -> int:
    ordered = sorted(
        (
            {
                "start": timerange_start(segment.get("target_timerange")),
                "end": timerange_start(segment.get("target_timerange")) + timerange_duration(segment.get("target_timerange")),
            }
            for segment in segments
        ),
        key=lambda row: (row["start"], row["end"]),
    )
    count = 0
    previous_end = None
    for row in ordered:
        if previous_end is not None and row["start"] < previous_end:
            count += 1
        previous_end = row["end"]
    return count
