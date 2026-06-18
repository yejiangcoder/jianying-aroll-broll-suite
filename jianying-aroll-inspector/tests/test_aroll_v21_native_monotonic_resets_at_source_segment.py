from __future__ import annotations

import unittest

from aroll_v21.ingest.real_draft_adapter import RealDraftIngestAdapter


class ArollV21NativeMonotonicResetsAtSourceSegmentTests(unittest.TestCase):
    def test_source_time_monotonic_check_does_not_reset_at_logical_source_segment_boundary(self) -> None:
        report = RealDraftIngestAdapter()._source_time_monotonic_report(
            [
                {"word_id": "w1", "subtitle_index": 1, "word_index_in_subtitle": 1, "source_start_us": 10_000_000, "source_segment_id": "clip_a"},
                {"word_id": "w2", "subtitle_index": 2, "word_index_in_subtitle": 1, "source_start_us": 10_500_000, "source_segment_id": "clip_a"},
                {"word_id": "w3", "subtitle_index": 3, "word_index_in_subtitle": 1, "source_start_us": 500_000, "source_segment_id": "clip_b"},
            ]
        )

        self.assertFalse(report["source_time_monotonic_by_subtitle"])
        self.assertEqual(report["source_time_non_monotonic_sample"]["word_id"], "w3")
        self.assertEqual(report["source_time_non_monotonic_sample"]["prev_source_start_us"], 10_500_000)


if __name__ == "__main__":
    unittest.main()
