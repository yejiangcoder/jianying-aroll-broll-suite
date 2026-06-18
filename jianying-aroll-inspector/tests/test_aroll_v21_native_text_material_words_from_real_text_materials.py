from __future__ import annotations

import unittest

from aroll_v21.ingest.word_timeline_provider import DefaultWordTimelineProvider


class ArollV21NativeTextMaterialWordsFromRealTextMaterialsTests(unittest.TestCase):
    def test_provider_reads_normalized_text_materials_words(self) -> None:
        result = DefaultWordTimelineProvider().load(
            draft_data={},
            text_materials=[
                {
                    "id": "sub_001",
                    "words": [
                        {"text": "你", "start_time": 0, "end_time": 100000},
                        {"text": "好", "start_time": 100000, "end_time": 200000},
                    ],
                }
            ],
        )

        self.assertEqual(result.blockers, [])
        self.assertEqual(len(result.words), 2)
        self.assertEqual(result.words[0]["text_material_id"], "sub_001")
        self.assertEqual(result.words[0]["source_start_us"], None)
        self.assertEqual(result.metadata["selected_provider"], "draft_native_word")
        self.assertEqual(result.metadata["speech_timeline_granularity"], "word")
        self.assertEqual(result.metadata["draft_native"]["candidate_count"], 2)
        self.assertEqual(result.metadata["draft_native"]["accepted_count"], 2)
        self.assertEqual(result.metadata["draft_native"]["rejected_count"], 0)
        self.assertEqual(result.metadata["draft_native"]["candidate_path_count"], 1)
        self.assertEqual(result.metadata["draft_native"]["selected_path"], "/normalized_text_materials[]/words")

    def test_sentence_rows_are_not_accepted_via_normalized_materials(self) -> None:
        result = DefaultWordTimelineProvider().load(
            draft_data={"sentences": [{"text": "整句", "start": 0, "end": 1000000}]},
            text_materials=[],
        )

        self.assertEqual(result.words, [])
        self.assertIn("REAL_DRAFT_SPEECH_TIMELINE_MISSING", [blocker.code for blocker in result.blockers])


if __name__ == "__main__":
    unittest.main()
