from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21.ingest.real_draft_adapter import RealDraftIngestResult

from dataclasses import replace

from aroll_v21.ir.models import FinalTimelineSegment
from tests.test_aroll_v21_real_writeback_backend import preflight_source_templates, run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


STALE_SOURCE_SEGMENT_ID_A = "old_seg_A"
STALE_SOURCE_SEGMENT_ID_B = "old_seg_B"


def bind_video_identity(
    result: RealDraftIngestResult,
    *,
    source_segment_id: str,
    source_material_id: str,
    media_path: str = "C:/media/video_1.mp4",
    duration_us: int = 1_000_000,
) -> RealDraftIngestResult:
    source_segment = result.source_segments[0]
    source_segment.update(
        {
            "id": source_segment_id,
            "material_id": source_material_id,
            "source_timerange": {"start": 0, "duration": duration_us},
            "target_timerange": {"start": 0, "duration": duration_us},
            "source_start_us": 0,
            "source_end_us": duration_us,
            "target_start_us": 0,
            "target_end_us": duration_us,
            "file_path": media_path,
            "name": Path(media_path).name,
        }
    )
    result.source_materials[:] = [
        {
            "source_material_id": source_material_id,
            "duration_us": duration_us,
            "file_path": media_path,
            "name": Path(media_path).name,
        }
    ]
    result.draft_data["tracks"][0]["segments"][0] = source_segment
    result.draft_data["materials"]["videos"] = [
        {
            "id": source_material_id,
            "duration": duration_us,
            "file_path": media_path,
            "name": Path(media_path).name,
        }
    ]
    return result


def strip_video_identity(result: RealDraftIngestResult) -> RealDraftIngestResult:
    for row in [*result.source_segments, *result.source_materials, *(result.draft_data.get("materials", {}).get("videos") or [])]:
        for key in ("path", "file_path", "local_path", "source_path", "video_path", "uri", "url", "name", "file_name", "filename", "material_name"):
            row.pop(key, None)
    return result


def two_old_source_segment_report() :
    old_result = bind_video_identity(
        fake_real_draft_result(),
        source_segment_id=STALE_SOURCE_SEGMENT_ID_A,
        source_material_id="old_mat_A",
    )
    report = run_report_from_result(old_result)
    first = report.final_timeline[0]
    second = FinalTimelineSegment(
        segment_id="v21_seg_second_source",
        source_material_id="",
        source_segment_id=None,
        source_start_us=500_000,
        source_end_us=800_000,
        target_start_us=first.target_end_us,
        target_end_us=first.target_end_us + 300_000,
        word_ids=["w002"],
        text="测试二",
        decision_ids=[],
        clip_source_start_us=500_000,
        clip_source_end_us=800_000,
    )
    return replace(report, final_timeline=[first, second])


class ArollV21FreshDraftSourceSegmentRebindTests(unittest.TestCase):
    def test_stale_source_segment_id_rebinds_to_unique_current_draft_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            old_result = bind_video_identity(
                fake_real_draft_result(),
                source_segment_id=STALE_SOURCE_SEGMENT_ID_A,
                source_material_id="old_mat_A",
            )
            current_result = bind_video_identity(
                fake_real_draft_result(root=root),
                source_segment_id="new_seg_B",
                source_material_id="new_mat_B",
            )
            report = run_report_from_result(old_result)

            writeback = fake_real_writeback()
            preflight = preflight_source_templates(
                draft_dir=draft_dir,
                real_draft_result=current_result,
                run_report=report,
            )
            self.assertTrue(preflight.success)
            self.assertEqual(preflight.report["source_segment_template_rebind_count"], 1)
            self.assertEqual(preflight.report["source_segment_template_exact_match_count"], 0)
            self.assertEqual(preflight.report["source_segment_template_rebind_samples"][0]["old_source_segment_id"], "")
            self.assertEqual(preflight.report["source_segment_template_rebind_samples"][0]["new_source_segment_id"], "new_seg_B")
            self.assertIn(preflight.report["source_segment_template_rebind_samples"][0]["match_strength"], {"strong", "weak_unique_primary_video"})
            bound_report = replace(
                report,
                resolved_template_map=dict(preflight.report["resolved_template_map"]),
                source_binding_report=dict(preflight.report),
            )

            writeback_result = writeback.commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=current_result,
                run_report=bound_report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            self.assertEqual(writeback_result.report["source_segment_template_rebind_count"], 1)
            written = json.loads(draft_content.read_text("utf-8"))
            video_track = next(track for track in written["tracks"] if track["id"] == "video_track")
            self.assertEqual(video_track["segments"][0]["material_id"], "new_mat_B")

    def test_two_stale_source_segment_ids_can_rebind_to_same_current_primary_video(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            report = two_old_source_segment_report()
            current_result = strip_video_identity(
                bind_video_identity(
                    fake_real_draft_result(root=root),
                    source_segment_id="new_primary_seg",
                    source_material_id="new_primary_mat",
                    duration_us=1_000_000,
                )
            )

            preflight = preflight_source_templates(
                draft_dir=draft_dir,
                real_draft_result=current_result,
                run_report=report,
            )

            self.assertTrue(preflight.success)
            self.assertEqual(preflight.report["source_segment_template_rebind_count"], 2)
            self.assertEqual(preflight.report["source_segment_template_missing_count"], 0)
            self.assertEqual(
                {row["new_source_segment_id"] for row in preflight.report["source_segment_template_rebind_samples"]},
                {"new_primary_seg"},
            )
            self.assertEqual(
                {row["match_strength"] for row in preflight.report["source_segment_template_rebind_samples"]},
                {"weak_unique_primary_video"},
            )


if __name__ == "__main__":
    unittest.main()
