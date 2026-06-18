from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.debug_aroll_v21_current_draft_source_templates import inspect_draft_source_templates


class ArollV21RealDraftSourceTemplateIndexFromDraftContentTests(unittest.TestCase):
    def test_debug_helper_extracts_video_track_segments_and_material_candidates_from_draft_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            timeline_dir = root / "draft" / "Timelines" / "timeline_001"
            timeline_dir.mkdir(parents=True)
            draft_data = {
                "materials": {
                    "videos": [
                        {
                            "id": "current_video_material",
                            "path": "C:/redacted/source.mp4",
                            "duration": 1_000_000,
                        }
                    ]
                },
                "tracks": [
                    {
                        "id": "video_track",
                        "type": "video",
                        "segments": [
                            {
                                "id": "current_video_segment",
                                "material_id": "current_video_material",
                                "source_timerange": {"start": 0, "duration": 1_000_000},
                                "target_timerange": {"start": 0, "duration": 1_000_000},
                            }
                        ],
                    }
                ],
            }
            (timeline_dir / "draft_content.json").write_text(json.dumps(draft_data), "utf-8")
            (timeline_dir / "template-2.tmp").write_text(json.dumps(draft_data), "utf-8")

            report = inspect_draft_source_templates(root / "draft")

            self.assertTrue(report["draft_content_parse_ok"])
            self.assertEqual(report["active_timeline_id"], "timeline_001")
            self.assertEqual(report["current_draft_video_track_count"], 1)
            self.assertEqual(report["current_draft_video_segment_count"], 1)
            self.assertEqual(report["current_draft_video_material_count"], 1)
            self.assertEqual(report["current_source_template_candidate_count"], 1)
            sample = report["current_source_template_candidate_samples"][0]
            self.assertEqual(sample["source_segment_id"], "current_video_segment")
            self.assertEqual(sample["source_material_id"], "current_video_material")
            self.assertEqual(sample["source_range"], [0, 1_000_000])


if __name__ == "__main__":
    unittest.main()
