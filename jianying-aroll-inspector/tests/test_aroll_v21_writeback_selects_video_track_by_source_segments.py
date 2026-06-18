from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_aroll_v21_real_writeback_backend import run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


class ArollV21WritebackVideoTrackSelectionTests(unittest.TestCase):
    def test_first_video_track_broll_second_aroll_source_only_second_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            broll_segment = {
                "id": "broll_segment",
                "type": "video",
                "material_id": "broll_material",
                "source_timerange": {"start": 0, "duration": 1000000},
                "target_timerange": {"start": 0, "duration": 1000000},
            }
            result.draft_data["tracks"].insert(0, {"id": "broll_track", "type": "video", "segments": [broll_segment]})
            report = run_report_from_result(result)

            writeback_result = fake_real_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            self.assertEqual(writeback_result.report["selected_video_track_id"], "video_track")
            written = json.loads(draft_content.read_text("utf-8"))
            broll_track = next(track for track in written["tracks"] if track["id"] == "broll_track")
            video_track = next(track for track in written["tracks"] if track["id"] == "video_track")
            self.assertEqual(broll_track["segments"][0]["id"], "broll_segment")
            self.assertTrue(all(segment["id"].startswith("v21_video_segment_") for segment in video_track["segments"]))


if __name__ == "__main__":
    unittest.main()
