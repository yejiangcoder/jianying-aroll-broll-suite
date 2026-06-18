from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_aroll_v21_real_writeback_backend import run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


def result_with_title_track(root: Path):
    result = fake_real_draft_result(root=root)
    title_material = {"id": "title_material", "type": "text", "text": "标题"}
    title_segment = {
        "id": "title_segment",
        "type": "text",
        "material_id": "title_material",
        "target_timerange": {"start": 0, "duration": 1000000},
    }
    result.draft_data["materials"]["texts"].insert(0, title_material)
    result.draft_data["tracks"].insert(0, {"id": "title_track", "type": "text", "segments": [title_segment]})
    result.text_segments.append(title_segment | {"track_id": "title_track", "track_type": "text"})
    for index in range(3):
        extra_segment = dict(title_segment)
        extra_segment["id"] = f"title_segment_extra_{index}"
        result.draft_data["tracks"][0]["segments"].append(extra_segment)
        result.text_segments.append(extra_segment | {"track_id": "title_track", "track_type": "text"})
    return result


class ArollV21WritebackSubtitleTrackSelectionTests(unittest.TestCase):
    def test_first_text_track_title_second_subtitle_only_second_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            result = result_with_title_track(root)
            report = run_report_from_result(result)

            writeback_result = fake_real_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            self.assertEqual(writeback_result.report["selected_text_track_id"], "text_track")
            written = json.loads(draft_content.read_text("utf-8"))
            title_track = next(track for track in written["tracks"] if track["id"] == "title_track")
            text_track = next(track for track in written["tracks"] if track["id"] == "text_track")
            self.assertEqual(title_track["segments"][0]["id"], "title_segment")
            self.assertTrue(all(segment["id"].startswith("v21_caption_segment_") for segment in text_track["segments"]))


if __name__ == "__main__":
    unittest.main()
