from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aroll_source_draft_integrity_gate import audit_source_draft_integrity


class SourceDraftIntegrityGateTest(unittest.TestCase):
    def test_processed_aroll_output_detection(self) -> None:
        report = audit_source_draft_integrity(
            {
                "timeline_id": "tl_1",
                "selected_main_video_track": {"total_target_duration_us": 100_000_000, "materials": [{"material_id": "raw"}]},
                "text_tracks": [{"selected_as_subtitle_track": True, "track_id": "text_1", "segment_count": 10}],
            },
            {
                "materials": {"texts": [{"id": "aroll_text_000001"}]},
                "tracks": [{"id": "text_1", "segments": [{"id": "aroll_text_segment_000001", "material_id": "aroll_text_000001"}]}],
            },
        )
        self.assertFalse(report["source_draft_integrity_gate_passed"])
        self.assertTrue(report["detected_as_processed_aroll_output"])

    def test_duration_ratio_block(self) -> None:
        report = audit_source_draft_integrity(
            {
                "timeline_id": "tl_1",
                "selected_main_video_track": {"total_target_duration_us": 80_000_000, "materials": [{"material_id": "raw"}]},
                "text_tracks": [{"selected_as_subtitle_track": True, "track_id": "text_1", "segment_count": 100}],
            },
            {"materials": {"texts": []}, "tracks": []},
            clean_source_duration_us=100_000_000,
        )
        self.assertIn("SOURCE_DURATION_BELOW_CLEAN_BASELINE", report["fatal_reasons"])

    def test_subtitle_count_ratio_block(self) -> None:
        report = audit_source_draft_integrity(
            {
                "timeline_id": "tl_1",
                "selected_main_video_track": {"total_target_duration_us": 100_000_000, "materials": [{"material_id": "raw"}]},
                "text_tracks": [{"selected_as_subtitle_track": True, "track_id": "text_1", "segment_count": 80}],
            },
            {"materials": {"texts": []}, "tracks": []},
            clean_source_subtitle_count=100,
        )
        self.assertIn("SUBTITLE_COUNT_BELOW_CLEAN_BASELINE", report["fatal_reasons"])


if __name__ == "__main__":
    unittest.main()
