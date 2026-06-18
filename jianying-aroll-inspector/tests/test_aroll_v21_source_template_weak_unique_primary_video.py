from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_aroll_v21_fresh_draft_source_segment_rebind import bind_video_identity, strip_video_identity
from tests.test_aroll_v21_real_writeback_backend import preflight_source_templates, run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


class ArollV21SourceTemplateWeakUniquePrimaryVideoTests(unittest.TestCase):
    def test_missing_media_identity_uses_weak_unique_primary_video_when_range_is_covered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            old_result = strip_video_identity(
                bind_video_identity(
                    fake_real_draft_result(),
                    source_segment_id="old_seg_A",
                    source_material_id="old_mat_A",
                    duration_us=1_000_000,
                )
            )
            current_result = strip_video_identity(
                bind_video_identity(
                    fake_real_draft_result(root=root),
                    source_segment_id="new_primary_seg",
                    source_material_id="new_primary_mat",
                    duration_us=1_000_000,
                )
            )
            report = run_report_from_result(old_result)

            preflight = preflight_source_templates(
                draft_dir=draft_dir,
                real_draft_result=current_result,
                run_report=report,
            )

            self.assertTrue(preflight.success)
            self.assertEqual(preflight.report["source_segment_template_rebind_count"], 1)
            sample = preflight.report["source_segment_template_rebind_samples"][0]
            self.assertEqual(sample["match_strength"], "weak_unique_primary_video")
            self.assertEqual(sample["new_source_segment_id"], "new_primary_seg")

    def test_candidate_exists_but_source_range_not_covered_still_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            old_result = bind_video_identity(
                fake_real_draft_result(),
                source_segment_id="old_seg_A",
                source_material_id="old_mat_A",
                duration_us=1_000_000,
            )
            current_result = bind_video_identity(
                fake_real_draft_result(root=root),
                source_segment_id="new_primary_seg",
                source_material_id="new_primary_mat",
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
            self.assertGreater(preflight.report["rebind_rejection_reasons"]["source_range_not_covered"], 0)


if __name__ == "__main__":
    unittest.main()
