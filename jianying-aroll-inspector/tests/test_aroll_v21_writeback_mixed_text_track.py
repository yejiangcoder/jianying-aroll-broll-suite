from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_aroll_v21_real_writeback_backend import run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


def add_confirmed_callout_to_selected_text_track(result) -> tuple[dict, dict]:
    callout_material = {
        "id": "callout_material",
        "role": "callout",
        "type": "text",
        "text": "callout",
    }
    callout_segment = {
        "id": "callout_segment",
        "type": "callout",
        "material_id": "callout_material",
        "target_timerange": {"start": 500_000, "duration": 500_000},
    }
    result.draft_data["materials"]["texts"].append(callout_material)
    text_track = next(track for track in result.draft_data["tracks"] if track["id"] == "text_track")
    text_track["segments"].append(callout_segment)
    result.text_segments.append(callout_segment | {"track_id": "text_track", "track_type": "text"})
    result.text_materials.append(callout_material)
    return callout_material, callout_segment


class ArollV21WritebackMixedTextTrackTests(unittest.TestCase):
    def test_selected_text_track_with_old_subtitles_and_callout_preserves_callout_and_writes_captions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            _callout_material, callout_segment = add_confirmed_callout_to_selected_text_track(result)
            report = run_report_from_result(fake_real_draft_result(root=root))

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
            segment_ids = [segment["id"] for segment in text_track["segments"]]

            self.assertNotIn("caption_segment_001", segment_ids)
            self.assertIn(callout_segment["id"], segment_ids)
            self.assertEqual(sum(1 for segment_id in segment_ids if segment_id.startswith("v21_caption_segment_")), len(report.captions))

            rough = writeback_result.report["rough_cut_quality"]
            self.assertEqual(rough["canonical_caption_segment_count"], len(report.captions))
            self.assertEqual(rough["selected_canonical_caption_segment_count"], len(report.captions))
            self.assertGreater(rough["selected_text_track_total_segment_count"], len(report.captions))
            self.assertEqual(rough["visible_caption_track_count"], 1)
            self.assertEqual(rough["old_subtitle_residue_track_count"], 0)
            self.assertEqual(rough["overlapping_caption_segments_count"], 0)
            self.assertTrue(rough["non_subtitle_text_segments_preserved"])
            self.assertEqual(writeback_result.report["preserved_non_subtitle_text_segment_count"], 1)


if __name__ == "__main__":
    unittest.main()
