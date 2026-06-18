from __future__ import annotations

import unittest

from aroll_v21.ingest.draft_native_word_timeline_discovery import discover_draft_native_word_timeline
from aroll_v21.ingest.word_timeline_provider import DefaultWordTimelineProvider


class ArollV21NoSubtitleAsWordFallbackTests(unittest.TestCase):
    def test_subtitle_rows_with_text_and_time_are_not_words(self) -> None:
        words, metadata = discover_draft_native_word_timeline(
            {
                "subtitles": [
                    {"text": "这是一整句字幕", "start_us": 0, "duration_us": 1000000},
                    {"text": "第二句字幕", "start_us": 1000000, "duration_us": 900000},
                ]
            }
        )
        self.assertEqual(words, [])
        self.assertEqual(metadata["subtitle_as_word_rejected_count"], 2)

    def test_sentence_rows_with_text_and_time_are_not_words(self) -> None:
        words, metadata = discover_draft_native_word_timeline(
            {"sentences": [{"text": "这是一整句", "start_us": 0, "end_us": 1000000}]}
        )
        self.assertEqual(words, [])
        self.assertEqual(metadata["subtitle_as_word_rejected_count"], 1)

    def test_explicit_word_rows_are_accepted(self) -> None:
        words, metadata = discover_draft_native_word_timeline(
            {"words": [{"word_text": "你", "start_us": 0, "end_us": 100000, "source_material_id": "m1"}]}
        )
        self.assertEqual(len(words), 1)
        self.assertEqual(words[0]["word_text"], "你")
        self.assertEqual(metadata["selected_path"], "/words")

    def test_text_field_under_explicit_word_path_is_accepted(self) -> None:
        words, metadata = discover_draft_native_word_timeline({"words": [{"text": "词", "start_us": 0, "end_us": 100000}]})
        self.assertEqual(len(words), 1)
        self.assertEqual(words[0]["word_text"], "词")
        self.assertEqual(metadata["selected_path"], "/words")

    def test_missing_speech_timeline_blocks_provider(self) -> None:
        result = DefaultWordTimelineProvider().load(
            draft_data={"subtitles": [{"text": "整句", "start_us": 0, "duration_us": 1000000}]}
        )
        self.assertEqual(result.words, [])
        self.assertIn("REAL_DRAFT_SPEECH_TIMELINE_MISSING", [blocker.code for blocker in result.blockers])


if __name__ == "__main__":
    unittest.main()
