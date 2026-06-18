from __future__ import annotations

import unittest

from aroll_v21.ingest.draft_native_word_timeline_discovery import discover_draft_native_word_timeline


class ArollV21Round5NativeWordsSampleFixtureTests(unittest.TestCase):
    def test_round5_like_117_materials_751_dict_array_words(self) -> None:
        text_materials = []
        remaining = 751
        for index in range(1, 118):
            count = 7 if index <= 49 else 6
            remaining -= count
            starts = [word_index * 320 for word_index in range(count)]
            ends = [start + 240 for start in starts]
            text_materials.append(
                {
                    "id": f"round5_text_{index:03d}",
                    "current_words": {},
                    "words": {
                        "start_time": starts,
                        "end_time": ends,
                        "text": [f"词{word_index}" for word_index in range(count)],
                    },
                }
            )
        self.assertEqual(remaining, 0)

        words, metadata = discover_draft_native_word_timeline({}, text_materials=text_materials)

        self.assertEqual(len(words), 751)
        self.assertEqual(metadata["scanned_text_material_count"], 117)
        self.assertEqual(metadata["materials_with_words_key"], 117)
        self.assertEqual(metadata["materials_with_nonempty_words"], 117)
        self.assertEqual(metadata["candidate_count"], 751)
        self.assertEqual(metadata["accepted_count"], 751)
        self.assertEqual(metadata["rejected_count"], 0)


if __name__ == "__main__":
    unittest.main()
