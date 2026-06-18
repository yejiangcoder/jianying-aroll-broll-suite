from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aroll_v21.operator import ArollV21OperatorConfig, run_operator

from tests.test_aroll_v21_fresh_draft_source_segment_rebind import (
    STALE_SOURCE_SEGMENT_ID_B,
    bind_video_identity,
)
from tests.test_aroll_v21_real_writeback_backend import run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import FakeAdapter, create_disposable_draft, fake_real_draft_result


class FakeEngineReturningReport:
    def __init__(self, *args, report, **kwargs) -> None:
        self.report = report

    def run(self, *_args, **_kwargs):
        return self.report


class ArollV21NoReadyTrueWhenSourceTemplateMissingTests(unittest.TestCase):
    def test_dry_run_blocks_ready_before_write_when_source_template_missing(self) -> None:
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
            ready_looking_report = run_report_from_result(old_result)
            self.assertEqual(ready_looking_report.status, "ok")

            with patch(
                "aroll_v21.operator.RealDraftIngestAdapter",
                lambda *a, **k: FakeAdapter(result=current_result),
            ), patch(
                "aroll_v21.operator.ArollEngine",
                lambda *a, **k: FakeEngineReturningReport(report=ready_looking_report),
            ):
                summary = run_operator(
                    ArollV21OperatorConfig(
                        mode="dry-run",
                        run_dir=root / "run",
                        draft_dir=draft_dir,
                    )
                )

            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["write_status"], "blocked_by_prewrite_source_template_availability")
            self.assertFalse(summary["READY_FOR_DISPOSABLE_WRITE_PRE_AUDIT"])
            self.assertFalse(summary["write_allowed"])
            self.assertEqual(summary["fatal_blocker"], "V21_DYNAMIC_BINDING_MISSING")
            self.assertEqual(summary["source_segment_template_missing_count"], 1)
            self.assertFalse(summary["commit_performed"])
            writeback_report = json.loads((root / "run" / "writeback_report.json").read_text("utf-8"))
            self.assertEqual(writeback_report["block_reason"], "V21_DYNAMIC_BINDING_MISSING")
            self.assertEqual(writeback_report["source_segment_template_missing_count"], 1)
            prewrite_report = json.loads((root / "run" / "prewrite_report.json").read_text("utf-8"))
            self.assertEqual(prewrite_report["block_reason"], "V21_DYNAMIC_BINDING_MISSING")
            self.assertEqual(prewrite_report["current_source_template_candidate_count"], 1)


if __name__ == "__main__":
    unittest.main()
