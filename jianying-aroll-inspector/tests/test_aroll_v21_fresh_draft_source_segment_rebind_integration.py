from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from aroll_v21.operator import ArollV21OperatorConfig, run_operator
from tests.test_aroll_v21_fresh_draft_source_segment_rebind import (
    STALE_SOURCE_SEGMENT_ID_A,
    bind_video_identity,
    two_old_source_segment_report,
)
from tests.test_aroll_v21_prewrite_report_emitted_on_source_template_failure import FakeEngineReturningReport
from tests.test_aroll_v21_sacrificial_write_override import FakeAdapter, create_disposable_draft, fake_real_draft_result


class ArollV21FreshDraftSourceSegmentRebindIntegrationTests(unittest.TestCase):
    def test_dry_run_rejects_stale_source_segment_id_in_logical_final_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            current_result = bind_video_identity(
                fake_real_draft_result(root=root),
                source_segment_id="current_primary_seg",
                source_material_id="current_primary_mat",
                duration_us=1_000_000,
            )
            current_result = replace(current_result, source_segments=[], source_materials=[])
            report = two_old_source_segment_report()
            polluted_first = replace(report.final_timeline[0], source_segment_id=STALE_SOURCE_SEGMENT_ID_A)
            report = replace(
                report,
                final_timeline=[polluted_first, *report.final_timeline[1:]],
                resolved_template_map={},
                source_binding_report={},
            )

            with patch("aroll_v21.operator.RealDraftIngestAdapter", lambda *a, **k: FakeAdapter(result=current_result)), patch(
                "aroll_v21.operator.ArollEngine",
                lambda *a, **k: FakeEngineReturningReport(report=report),
            ):
                summary = run_operator(ArollV21OperatorConfig(mode="dry-run", run_dir=root / "run", draft_dir=draft_dir))

            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["write_status"], "blocked_by_prewrite_source_template_availability")
            self.assertFalse(summary["READY_FOR_DISPOSABLE_WRITE_PRE_AUDIT"])
            self.assertFalse(summary["commit_performed"])
            self.assertFalse(summary["writeback_success"])
            self.assertEqual(summary["fatal_blocker"], "V21_DYNAMIC_BINDING_FORBIDS_LOGICAL_SOURCE_SEGMENT_ID")
            prewrite = json.loads((root / "run" / "prewrite_report.json").read_text("utf-8"))
            writeback = json.loads((root / "run" / "writeback_report.json").read_text("utf-8"))
            self.assertEqual(prewrite["current_draft_video_track_count"], 1)
            self.assertEqual(prewrite["current_draft_video_segment_count"], 1)
            self.assertEqual(prewrite["current_draft_video_material_count"], 1)
            self.assertEqual(prewrite["current_source_template_candidate_count"], 1)
            self.assertEqual(prewrite["block_reason"], "V21_DYNAMIC_BINDING_FORBIDS_LOGICAL_SOURCE_SEGMENT_ID")
            self.assertEqual(writeback["block_reason"], "V21_DYNAMIC_BINDING_FORBIDS_LOGICAL_SOURCE_SEGMENT_ID")
            self.assertFalse(writeback["writeback_success"])
            self.assertEqual(prewrite["source_segment_template_rebind_count"], 1)
            self.assertEqual(prewrite["source_segment_template_missing_count"], 0)
            self.assertEqual(prewrite["source_segment_template_exact_match_count"], 0)
            self.assertNotEqual(len(prewrite["resolved_template_map"]), len(report.final_timeline))


if __name__ == "__main__":
    unittest.main()
