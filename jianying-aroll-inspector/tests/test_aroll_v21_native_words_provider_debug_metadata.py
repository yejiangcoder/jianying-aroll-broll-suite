from __future__ import annotations

import unittest

from aroll_v21.ingest.draft_native_word_timeline_discovery import discover_draft_native_word_timeline


class ArollV21NativeWordsProviderDebugMetadataTests(unittest.TestCase):
    def test_debug_metadata_reports_round4_like_scan_counts(self) -> None:
        text_materials = [
            {"id": f"text_{index:03d}", "words": [{"content": "词", "time_range": {"start": index * 1000, "duration": 500}}]}
            for index in range(1, 118)
        ]

        words, metadata = discover_draft_native_word_timeline({}, text_materials=text_materials)

        self.assertEqual(len(words), 117)
        self.assertEqual(metadata["scanned_text_material_count"], 117)
        self.assertEqual(metadata["materials_with_words_key"], 117)
        self.assertEqual(metadata["materials_with_nonempty_words"], 117)
        self.assertEqual(metadata["candidate_count"], 117)
        self.assertEqual(metadata["accepted_count"], 117)
        self.assertEqual(metadata["rejected_count"], 0)
        self.assertEqual(metadata["sample_rejections"], [])

    def test_missing_timing_reports_specific_rejection_reason(self) -> None:
        words, metadata = discover_draft_native_word_timeline(
            {},
            text_materials=[{"id": "text_001", "words": [{"word": "词"}]}],
        )

        self.assertEqual(words, [])
        self.assertEqual(metadata["candidate_count"], 1)
        self.assertEqual(metadata["accepted_count"], 0)
        self.assertEqual(metadata["rejected_count"], 1)
        self.assertEqual(metadata["sample_rejections"][0]["reason"], "missing_word_timing")


if __name__ == "__main__":
    unittest.main()
