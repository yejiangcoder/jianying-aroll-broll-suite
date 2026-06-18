from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_aroll_v21_real_writeback_backend import run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


class ArollV21WritebackPreserveNonSubtitleSegmentsTests(unittest.TestCase):
    def test_confirmed_title_segment_and_material_on_selected_track_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            title_material = {
                "id": "title_material",
                "role": "title",
                "type": "text",
                "text": "title",
            }
            title_segment = {
                "id": "title_segment",
                "type": "title",
                "material_id": "title_material",
                "target_timerange": {"start": 100_000, "duration": 800_000},
            }
            result.draft_data["materials"]["texts"].append(title_material)
            text_track = next(track for track in result.draft_data["tracks"] if track["id"] == "text_track")
            text_track["segments"].append(title_segment)
            result.text_segments.append(title_segment | {"track_id": "text_track", "track_type": "text"})
            result.text_materials.append(title_material)
            report = run_report_from_result(fake_real_draft_result(root=root))

            writeback_result = fake_real_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            self.assertTrue(writeback_result.report["non_subtitle_text_tracks_preserved"])
            self.assertTrue(writeback_result.report["non_subtitle_text_segments_preserved"])
            written = json.loads(draft_content.read_text("utf-8"))
            material_ids = {row["id"] for row in written["materials"]["texts"]}
            text_track = next(track for track in written["tracks"] if track["id"] == "text_track")
            segment_ids = {segment["id"] for segment in text_track["segments"]}

            self.assertIn("title_material", material_ids)
            self.assertIn("title_segment", segment_ids)
            self.assertEqual(writeback_result.report["rough_cut_quality"]["preserved_non_subtitle_text_segment_count"], 1)


if __name__ == "__main__":
    unittest.main()
