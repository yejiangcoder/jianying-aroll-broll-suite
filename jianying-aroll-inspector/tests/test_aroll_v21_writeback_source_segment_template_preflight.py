from __future__ import annotations

import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.test_aroll_v21_fresh_draft_source_segment_rebind import (
    STALE_SOURCE_SEGMENT_ID_B,
    bind_video_identity,
)
from tests.test_aroll_v21_real_writeback_backend import preflight_source_templates, run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


class ArollV21WritebackSourceSegmentTemplatePreflightTests(unittest.TestCase):
    def test_logical_source_segment_id_is_rejected_not_exact_matched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = bind_video_identity(
                fake_real_draft_result(root=root),
                source_segment_id="current_seg_A",
                source_material_id="current_mat_A",
            )
            report = run_report_from_result(result)
            exact_final = replace(
                report.final_timeline[0],
                source_segment_id="current_seg_A",
                source_material_id="current_mat_A",
            )
            report = replace(report, final_timeline=[exact_final], resolved_template_map={}, source_binding_report={})

            preflight = preflight_source_templates(
                draft_dir=draft_dir,
                real_draft_result=result,
                run_report=report,
            )

            self.assertFalse(preflight.success)
            self.assertEqual(preflight.blockers[0].code, "V21_DYNAMIC_BINDING_FORBIDS_LOGICAL_SOURCE_SEGMENT_ID")
            self.assertEqual(preflight.report["source_segment_template_exact_match_count"], 0)

    def test_missing_current_template_fails_closed_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            old_result = bind_video_identity(
                fake_real_draft_result(),
                source_segment_id=STALE_SOURCE_SEGMENT_ID_B,
                source_material_id="old_mat_A",
                media_path="C:/media/video_1.mp4",
                duration_us=1_000_000,
            )
            current_result = bind_video_identity(
                fake_real_draft_result(root=root),
                source_segment_id="new_seg_B",
                source_material_id="new_mat_B",
                media_path="C:/media/video_1.mp4",
                duration_us=200_000,
            )
            report = run_report_from_result(old_result)

            preflight = preflight_source_templates(
                draft_dir=draft_dir,
                real_draft_result=current_result,
                run_report=report,
            )

            self.assertFalse(preflight.success)
            self.assertEqual(preflight.blockers[0].code, "V21_DYNAMIC_BINDING_MISSING")
            self.assertEqual(preflight.report["source_segment_template_missing_count"], 1)
            self.assertEqual(preflight.report["candidate_count"], 0)

    def test_multiple_matching_current_templates_fail_closed_as_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            old_result = bind_video_identity(
                fake_real_draft_result(),
                source_segment_id="old_seg_A",
                source_material_id="old_mat_A",
            )
            current_result = bind_video_identity(
                fake_real_draft_result(root=root),
                source_segment_id="new_seg_B",
                source_material_id="new_mat_B",
            )
            second_candidate = copy.deepcopy(current_result.source_segments[0])
            second_candidate["id"] = "new_seg_C"
            current_result.source_segments.append(second_candidate)
            current_result.draft_data["tracks"][0]["segments"].append(second_candidate)
            report = run_report_from_result(old_result)

            preflight = preflight_source_templates(
                draft_dir=draft_dir,
                real_draft_result=current_result,
                run_report=report,
            )

            self.assertFalse(preflight.success)
            self.assertEqual(preflight.blockers[0].code, "V21_DYNAMIC_BINDING_AMBIGUOUS")
            self.assertEqual(preflight.report["source_segment_template_ambiguous_count"], 1)
            self.assertEqual(preflight.report["candidate_count"], 2)
            self.assertGreaterEqual(len(preflight.report["candidate_samples"]), 2)


if __name__ == "__main__":
    unittest.main()
