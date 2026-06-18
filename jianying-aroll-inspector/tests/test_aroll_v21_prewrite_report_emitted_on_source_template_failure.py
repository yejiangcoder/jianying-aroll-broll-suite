from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aroll_v21.operator import ArollV21OperatorConfig, run_operator
from tests.test_aroll_v21_fresh_draft_source_segment_rebind import bind_video_identity, two_old_source_segment_report
from tests.test_aroll_v21_real_writeback_backend import run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import FakeAdapter, create_disposable_draft, fake_real_draft_result


class FakeEngineReturningReport:
    def __init__(self, *args, report, **kwargs) -> None:
        self.report = report

    def run(self, *_args, **_kwargs):
        return self.report


class ArollV21PrewriteReportEmittedOnSourceTemplateFailureTests(unittest.TestCase):
    def test_dry_run_emits_prewrite_report_when_source_template_preflight_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            old_result = bind_video_identity(
                fake_real_draft_result(),
                source_segment_id="old_seg_A",
                source_material_id="old_mat_A",
                media_path="C:/media/source_a.mp4",
                duration_us=1_000_000,
            )
            current_result = bind_video_identity(
                fake_real_draft_result(root=root),
                source_segment_id="current_seg",
                source_material_id="current_mat",
                media_path="C:/media/source_a.mp4",
                duration_us=200_000,
            )
            report = run_report_from_result(old_result)

            with patch("aroll_v21.operator.RealDraftIngestAdapter", lambda *a, **k: FakeAdapter(result=current_result)), patch(
                "aroll_v21.operator.ArollEngine",
                lambda *a, **k: FakeEngineReturningReport(report=report),
            ):
                summary = run_operator(ArollV21OperatorConfig(mode="dry-run", run_dir=root / "run", draft_dir=draft_dir))

            self.assertEqual(summary["status"], "blocked")
            self.assertFalse(summary["READY_FOR_DISPOSABLE_WRITE_PRE_AUDIT"])
            prewrite = json.loads((root / "run" / "prewrite_report.json").read_text("utf-8"))
            self.assertEqual(prewrite["source_segment_template_missing_count"], 1)
            self.assertEqual(prewrite["current_draft_video_track_count"], 1)
            self.assertEqual(prewrite["current_draft_video_segment_count"], 1)
            self.assertEqual(prewrite["current_draft_video_material_count"], 1)
            self.assertEqual(prewrite["current_source_template_candidate_count"], 1)
            self.assertEqual(prewrite["block_reason"], "V21_DYNAMIC_BINDING_MISSING")

    def test_dry_run_emits_prewrite_report_when_source_template_preflight_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            current_result = bind_video_identity(
                fake_real_draft_result(root=root),
                source_segment_id="current_primary_seg",
                source_material_id="current_primary_mat",
                duration_us=1_000_000,
            )
            report = two_old_source_segment_report()

            with patch("aroll_v21.operator.RealDraftIngestAdapter", lambda *a, **k: FakeAdapter(result=current_result)), patch(
                "aroll_v21.operator.ArollEngine",
                lambda *a, **k: FakeEngineReturningReport(report=report),
            ):
                summary = run_operator(ArollV21OperatorConfig(mode="dry-run", run_dir=root / "run", draft_dir=draft_dir))

            self.assertEqual(summary["status"], "ok")
            self.assertTrue(summary["READY_FOR_DISPOSABLE_WRITE_PRE_AUDIT"])
            prewrite = json.loads((root / "run" / "prewrite_report.json").read_text("utf-8"))
            self.assertEqual(prewrite["source_segment_template_rebind_count"], 2)
            self.assertEqual(prewrite["source_segment_template_missing_count"], 0)
            self.assertEqual(prewrite["current_source_template_candidate_count"], 1)
            self.assertEqual(
                {row["new_source_segment_id"] for row in prewrite["source_segment_template_rebind_samples"]},
                {"current_primary_seg"},
            )


if __name__ == "__main__":
    unittest.main()
