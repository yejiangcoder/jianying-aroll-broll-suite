from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_aroll_v21_real_writeback_backend import run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_writeback
from tests.test_aroll_v21_writeback_selects_subtitle_track_by_binding import result_with_title_track


class ArollV21WritebackPreservesNonSubtitleTextTracksTests(unittest.TestCase):
    def test_title_and_callout_materials_are_not_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            result = result_with_title_track(root)
            callout_material = {"id": "callout_material", "type": "text", "text": "贴纸文字"}
            callout_segment = {
                "id": "callout_segment",
                "type": "text",
                "material_id": "callout_material",
                "target_timerange": {"start": 500000, "duration": 500000},
            }
            result.draft_data["materials"]["texts"].append(callout_material)
            result.draft_data["tracks"].append({"id": "callout_track", "type": "text", "segments": [callout_segment]})
            result.text_segments.append(callout_segment | {"track_id": "callout_track", "track_type": "text"})
            report = run_report_from_result(result)

            writeback_result = fake_real_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            self.assertTrue(writeback_result.report["non_subtitle_text_tracks_preserved"])
            written = json.loads(draft_content.read_text("utf-8"))
            material_ids = {row["id"] for row in written["materials"]["texts"]}
            self.assertIn("title_material", material_ids)
            self.assertIn("callout_material", material_ids)
            callout_track = next(track for track in written["tracks"] if track["id"] == "callout_track")
            self.assertEqual(callout_track["segments"][0]["id"], "callout_segment")


if __name__ == "__main__":
    unittest.main()
