from __future__ import annotations

from pathlib import Path
from typing import Any
import unittest


def assert_run_summary_contract(
    case: unittest.TestCase,
    summary: dict[str, Any],
    *,
    writeback_report: dict[str, Any] | None = None,
) -> None:
    required = {
        "status",
        "write_status",
        "write_allowed",
        "semantic_unresolved_count",
        "validator_write_allowed",
        "commit_performed",
        "writeback_success",
        "ready_for_user_manual_qc",
        "writer_fallback_count",
        "blocker_codes",
    }
    case.assertTrue(required <= set(summary), sorted(required - set(summary)))
    if summary["commit_performed"]:
        case.assertTrue(summary["writeback_success"])
        case.assertRegex(str(summary["write_status"]), r"committed|success")
    if summary["writeback_success"] and writeback_report is not None:
        case.assertTrue(writeback_report.get("target_writes"))
    if int(summary.get("semantic_unresolved_count") or 0) > 0:
        case.assertFalse(summary["write_allowed"])
    if int(summary.get("writer_fallback_count") or 0) > 0:
        case.assertFalse(summary["write_allowed"])
    if summary.get("ready_for_user_manual_qc"):
        case.assertTrue(summary["commit_performed"])
        case.assertTrue(summary["writeback_success"])
    if summary["status"] == "ok":
        case.assertEqual(summary.get("blocker_codes") or [], [])


def assert_writeback_report_contract(case: unittest.TestCase, report: dict[str, Any]) -> None:
    required = {
        "writeback_attempted",
        "writeback_success",
        "draft_dir",
        "timeline_id",
        "timeline_dir",
        "draft_content_path",
        "template_path",
        "plain_modified_path",
        "encrypted_out_path",
        "target_writes",
        "selected_text_track_id",
        "selected_video_track_id",
        "old_subtitle_segment_count",
        "old_subtitle_material_count",
        "new_caption_segment_count",
        "new_caption_material_count",
        "non_subtitle_text_tracks_preserved",
        "root_mirror_required",
        "root_mirror_written",
        "timeline_integrity_checks",
        "video_preflight",
        "audio_preflight",
        "filter_preflight",
        "source_mapping_mode",
        "source_segment_template_exact_match_count",
        "source_segment_template_rebind_count",
        "source_segment_template_missing_count",
        "source_segment_template_ambiguous_count",
        "current_draft_video_track_count",
        "current_draft_video_segment_count",
        "current_draft_video_material_count",
        "current_source_template_candidate_count",
        "current_source_template_candidate_samples",
        "rebind_rejection_reasons",
        "sacrificial_write_override_used",
        "postwrite_decrypt_skipped_for_sacrificial_draft",
        "rough_cut_quality",
    }
    case.assertTrue(required <= set(report), sorted(required - set(report)))
    if report.get("writeback_success"):
        target_writes = report.get("target_writes") or {}
        case.assertGreaterEqual(len(target_writes), 2)
        case.assertTrue(any(str(path).endswith("draft_content.json") for path in target_writes))
        case.assertTrue(any(str(path).endswith("template-2.tmp") for path in target_writes))
        case.assertTrue(all(bool(value) for value in target_writes.values()))
        case.assertTrue(str(report.get("selected_text_track_id") or ""))
        case.assertTrue(str(report.get("selected_video_track_id") or ""))
        case.assertTrue(report.get("non_subtitle_text_tracks_preserved"))
        rough = report.get("rough_cut_quality") or {}
        case.assertIn("visible_caption_track_count", rough)
        case.assertEqual(rough.get("visible_caption_track_count"), 1)
        case.assertEqual(rough.get("old_subtitle_residue_track_count"), 0)
        case.assertEqual(rough.get("overlapping_caption_segments_count"), 0)
        case.assertTrue(rough.get("selected_canonical_subtitle_track_matches_captions"))
        case.assertTrue(Path(str(report.get("plain_modified_path"))).exists())
        case.assertTrue(Path(str(report.get("encrypted_out_path"))).exists())


def assert_material_caption_timeline_contract(
    case: unittest.TestCase,
    final_timeline: list[dict[str, Any]],
    captions: list[dict[str, Any]],
    material_write_plan: dict[str, Any],
) -> None:
    case.assertGreater(len(final_timeline), 0)
    case.assertEqual(len(final_timeline), len(captions))
    case.assertEqual(len(material_write_plan.get("segments") or []), len(captions))
    case.assertEqual(len(material_write_plan.get("materials") or []), len(captions))
    previous_end = 0
    for index, segment in enumerate(final_timeline):
        case.assertTrue(segment.get("word_ids"), segment)
        start = int(segment.get("target_start_us") or 0)
        end = int(segment.get("target_end_us") or 0)
        case.assertGreater(end, start, segment)
        if index:
            case.assertGreaterEqual(start, previous_end, segment)
        previous_end = end
    timeline_ids = {str(row.get("segment_id") or "") for row in final_timeline}
    for caption in captions:
        case.assertTrue(set(caption.get("timeline_segment_ids") or []) <= timeline_ids)
        case.assertTrue(caption.get("word_ids"))
    for segment in material_write_plan.get("segments") or []:
        case.assertTrue(str(segment.get("material_id") or segment.get("materialId") or ""), segment)
