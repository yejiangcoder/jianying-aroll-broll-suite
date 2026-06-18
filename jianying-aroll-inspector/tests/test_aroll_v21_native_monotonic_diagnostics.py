from __future__ import annotations

import unittest

from aroll_v21.ingest.real_draft_adapter import RealDraftIngestAdapter


class ArollV21NativeMonotonicDiagnosticsTests(unittest.TestCase):
    def test_same_source_segment_non_monotonic_reports_specific_words(self) -> None:
        report = RealDraftIngestAdapter()._source_time_monotonic_report(
            [
                {"word_id": "prev", "subtitle_uid": "s1", "subtitle_index": 1, "word_index_in_subtitle": 1, "source_start_us": 2_000_000, "source_segment_id": "clip"},
                {"word_id": "cur", "subtitle_uid": "s2", "subtitle_index": 2, "word_index_in_subtitle": 1, "source_start_us": 1_000_000, "source_segment_id": "clip"},
            ]
        )

        self.assertFalse(report["source_time_monotonic_by_subtitle"])
        sample = report["source_time_non_monotonic_sample"]
        self.assertEqual(sample["word_id"], "cur")
        self.assertEqual(sample["prev_word_id"], "prev")
        self.assertEqual(sample["prev_source_start_us"], 2_000_000)
        self.assertEqual(sample["current_source_start_us"], 1_000_000)
        self.assertEqual(sample["source_segment_id"], "clip")
        self.assertEqual(sample["subtitle_index"], 2)


if __name__ == "__main__":
    unittest.main()
