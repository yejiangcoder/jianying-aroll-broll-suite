from __future__ import annotations

import unittest

from aroll_v21.ingest.word_timeline_provider import DefaultWordTimelineProvider


class ArollV21NativeWordsFromNormalizedTextMaterialsTests(unittest.TestCase):
    def test_normalized_text_material_words_are_prioritized(self) -> None:
        result = DefaultWordTimelineProvider().load(
            draft_data={
                "materials": {
                    "texts": [
                        {
                            "id": "raw_text_001",
                            "words": [{"text": "原始", "start": 0, "duration": 100000}],
                        }
                    ]
                }
            },
            text_materials=[
                {
                    "id": "normalized_text_001",
                    "words": [
                        {"word": "规整", "start": 0, "duration": 100000},
                        {"word": "字幕", "start": 100000, "duration": 100000},
                    ],
                }
            ],
            text_segments=[{"id": "text_seg_001", "material_id": "normalized_text_001"}],
            source_segments=[{"id": "clip_001", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000000}],
        )

        metadata = result.metadata["draft_native"]
        self.assertEqual(result.blockers, [])
        self.assertEqual([row["text_material_id"] for row in result.words], ["normalized_text_001", "normalized_text_001"])
        self.assertEqual(metadata["selected_path"], "/normalized_text_materials[]/words")
        self.assertEqual(metadata["scanned_text_material_count"], 1)
        self.assertEqual(metadata["materials_with_words_key"], 1)
        self.assertEqual(metadata["materials_with_nonempty_words"], 1)
        self.assertEqual(metadata["candidate_count"], 2)
        self.assertEqual(metadata["accepted_count"], 2)
        self.assertEqual(metadata["rejected_count"], 0)

    def test_normalized_words_debug_counts_rejections(self) -> None:
        result = DefaultWordTimelineProvider().load(
            draft_data={},
            text_materials=[
                {
                    "id": "normalized_text_001",
                    "words": [
                        {"text": "缺时间"},
                        {"text": "错时间", "start": 100000, "end": 100000},
                    ],
                }
            ],
        )

        metadata = result.metadata["draft_native"]
        self.assertEqual(result.words, [])
        self.assertIn("DRAFT_NATIVE_WORD_ROWS_REJECTED", [blocker.code for blocker in result.blockers])
        self.assertEqual(metadata["candidate_count"], 2)
        self.assertEqual(metadata["accepted_count"], 0)
        self.assertEqual(metadata["rejected_count"], 2)
        self.assertEqual(metadata["sample_rejections"][0]["reason"], "missing_word_timing")
        self.assertEqual(metadata["sample_rejections"][1]["reason"], "invalid_word_timing")


if __name__ == "__main__":
    unittest.main()
