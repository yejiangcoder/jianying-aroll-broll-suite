from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from tests.test_aroll_v21_fresh_draft_source_segment_rebind import bind_video_identity
from tests.test_aroll_v21_real_writeback_backend import preflight_source_templates, run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


class ArollV21SourceTemplateCandidateIndexTests(unittest.TestCase):
    def test_current_draft_candidate_index_uses_draft_video_track_segments_and_materials(self) -> None:
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
            current_result = replace(current_result, source_segments=[], source_materials=[])
            report = run_report_from_result(old_result)

            preflight = preflight_source_templates(
                draft_dir=draft_dir,
                real_draft_result=current_result,
                run_report=report,
            )

            self.assertTrue(preflight.success)
            self.assertGreater(preflight.report["current_draft_video_track_count"], 0)
            self.assertGreater(preflight.report["current_draft_video_segment_count"], 0)
            self.assertGreater(preflight.report["current_draft_video_material_count"], 0)
            self.assertGreater(preflight.report["current_source_template_candidate_count"], 0)
            self.assertTrue(preflight.report["current_source_template_candidate_samples"])

    def test_empty_current_source_template_candidate_index_has_specific_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            old_result = bind_video_identity(
                fake_real_draft_result(),
                source_segment_id="old_seg_A",
                source_material_id="old_mat_A",
            )
            current_result = fake_real_draft_result(root=root)
            current_result.draft_data["tracks"][0]["segments"] = []
            current_result.draft_data["materials"]["videos"] = []
            current_result = replace(current_result, source_segments=[], source_materials=[])
            report = run_report_from_result(old_result)

            preflight = preflight_source_templates(
                draft_dir=draft_dir,
                real_draft_result=current_result,
                run_report=report,
            )

            self.assertFalse(preflight.success)
            self.assertEqual(preflight.blockers[0].code, "V21_DYNAMIC_BINDING_PRIMARY_VIDEO_MISSING")
            self.assertEqual(preflight.report["current_source_template_candidate_count"], 0)
            self.assertEqual(preflight.report["current_source_template_candidate_samples"], [])


if __name__ == "__main__":
    unittest.main()
