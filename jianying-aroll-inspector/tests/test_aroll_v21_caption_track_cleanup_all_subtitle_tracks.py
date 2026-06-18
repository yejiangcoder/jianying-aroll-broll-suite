from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_aroll_v21_real_writeback_backend import run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback
from tests.test_aroll_v21_writeback_selects_subtitle_track_by_binding import result_with_title_track


class ArollV21CaptionTrackCleanupAllSubtitleTracksTests(unittest.TestCase):
    def test_all_old_subtitle_tracks_are_cleared_and_non_subtitle_tracks_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            result = result_with_title_track(root)
            base_report = run_report_from_result(fake_real_draft_result(root=root))
            selected_extra = dict(result.text_segments[0])
            selected_extra["id"] = "selected_extra_segment"
            result.draft_data["tracks"][2]["segments"].append(selected_extra)
            result.text_segments.append(selected_extra | {"track_id": "text_track", "track_type": "text"})

            residue_segment = dict(result.text_segments[0])
            residue_segment["id"] = "residue_subtitle_segment"
            residue_track = {"id": "subtitle_residue_track", "type": "text", "segments": [residue_segment]}
            result.draft_data["tracks"].append(residue_track)
            result.text_segments.append(residue_segment | {"track_id": "subtitle_residue_track", "track_type": "text"})

            writeback_result = fake_real_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=base_report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            written = json.loads(draft_content.read_text("utf-8"))
            text_track = next(track for track in written["tracks"] if track["id"] == "text_track")
            residue_track = next(track for track in written["tracks"] if track["id"] == "subtitle_residue_track")
            title_track = next(track for track in written["tracks"] if track["id"] == "title_track")

            self.assertEqual(len(text_track["segments"]), len(base_report.captions))
            self.assertEqual(residue_track["segments"], [])
            self.assertEqual(title_track["segments"][0]["id"], "title_segment")
            rough = writeback_result.report["rough_cut_quality"]
            self.assertEqual(rough["visible_caption_track_count"], 1)
            self.assertEqual(rough["old_subtitle_residue_track_count"], 0)
            self.assertEqual(rough["selected_canonical_subtitle_track_segment_count"], len(base_report.captions))
            self.assertTrue(rough["selected_canonical_subtitle_track_matches_captions"])

    def test_selected_subtitle_track_with_explicit_callout_segment_preserves_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            callout_segment = {
                "id": "safe_callout_segment",
                "type": "text",
                "material_id": "callout_material",
                "track_id": "text_track",
                "track_type": "text",
                "target_timerange": {"start": 500_000, "duration": 500_000},
            }
            result.draft_data["materials"]["texts"].append({"id": "callout_material", "type": "text", "text": "贴纸"})
            result.draft_data["tracks"][1]["segments"].append(callout_segment)
            result.text_segments.append(callout_segment)
            report = run_report_from_result(result)

            writeback_result = fake_real_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            written = json.loads(draft_content.read_text("utf-8"))
            text_track = next(track for track in written["tracks"] if track["id"] == "text_track")
            self.assertIn("safe_callout_segment", {segment["id"] for segment in text_track["segments"]})
            self.assertEqual(writeback_result.report["post_write_old_subtitle_residue_count"], 0)

    def test_post_mutation_rough_cut_qc_failure_blocks_before_target_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)
            before = draft_content.read_text("utf-8")
            bad_metrics = {
                "final_timeline_count": len(report.final_timeline),
                "caption_count": len(report.captions),
                "material_count": len(report.material_write_plan["materials"]),
                "segment_count": len(report.material_write_plan["segments"]),
                "visible_caption_track_count": 2,
                "old_subtitle_residue_track_count": 1,
                "overlapping_caption_segments_count": 1,
                "target_gap_count": 0,
                "target_overlap_count": 0,
                "selected_canonical_subtitle_track_segment_count": 0,
                "selected_canonical_subtitle_track_matches_captions": False,
            }
            writeback = fake_real_writeback()

            with patch.object(writeback, "_writeback_rough_cut_quality", return_value=bad_metrics):
                writeback_result = writeback.commit(
                    draft_dir=draft_dir,
                    run_dir=root / "run",
                    real_draft_result=result,
                    run_report=report,
                    sacrificial_write_override_used=True,
                )

            self.assertFalse(writeback_result.success)
            self.assertEqual(writeback_result.blockers[0].code, "V21_WRITEBACK_ROUGH_CUT_QC_FAILED")
            self.assertEqual(draft_content.read_text("utf-8"), before)


if __name__ == "__main__":
    unittest.main()
