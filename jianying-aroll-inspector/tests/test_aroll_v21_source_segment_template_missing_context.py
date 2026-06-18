from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_aroll_v21_fresh_draft_source_segment_rebind import (
    STALE_SOURCE_SEGMENT_ID_A,
    bind_video_identity,
)
from tests.test_aroll_v21_real_writeback_backend import preflight_source_templates, run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


class ArollV21SourceSegmentTemplateMissingContextTests(unittest.TestCase):
    def test_missing_source_template_blocker_contains_actionable_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            old_result = bind_video_identity(
                fake_real_draft_result(),
                source_segment_id=STALE_SOURCE_SEGMENT_ID_A,
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
            blocker_context = preflight.blockers[0].context
            self.assertEqual(blocker_context["missing_source_segment_id"], "")
            self.assertEqual(blocker_context["source_material_id"], "")
            self.assertEqual(blocker_context["source_start_us"], report.final_timeline[0].source_start_us)
            self.assertEqual(blocker_context["source_end_us"], report.final_timeline[0].source_end_us)
            self.assertEqual(blocker_context["candidate_count"], 0)
            self.assertEqual(blocker_context["candidate_samples"], [])
            self.assertEqual(
                blocker_context["reason"],
                "no current draft source segment template matches media identity + source range",
            )
            self.assertFalse(preflight.report["commit_performed"])


if __name__ == "__main__":
    unittest.main()
