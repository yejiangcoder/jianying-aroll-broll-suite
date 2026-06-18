from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21.ingest.draft_native_word_timeline_discovery import discover_draft_native_word_timeline
from aroll_v21.ingest.real_draft_adapter import RealDraftIngestAdapter

from tests.test_aroll_v21_real_draft_ingest_adapter import _draft_payload, _make_real_draft_skeleton


class ArollV21NativeTextMaterialWordsProviderTests(unittest.TestCase):
    def test_text_material_words_generate_bound_word_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir = _make_real_draft_skeleton(root)
            payload = _draft_payload()
            payload.pop("word_timeline")
            payload["materials"]["texts"][0]["words"] = [
                {"text": "示例", "start": 0, "duration": 500000},
                {"text": "字幕", "start": 500000, "duration": 500000},
            ]

            def fake_decrypt(_jy_draftc: Path, _encrypted: Path, output: Path) -> None:
                output.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")

            result = RealDraftIngestAdapter(decrypt_func=fake_decrypt).load(draft_dir, root / "run")

            self.assertEqual([blocker.code for blocker in result.blockers], [])
            self.assertEqual(len(result.word_timeline), 2)
            self.assertEqual(result.word_timeline[0]["start_us"], 0)
            self.assertEqual(result.word_timeline[0]["end_us"], 500000)
            self.assertEqual(result.word_timeline[0]["subtitle_uid"], "subtitle_seg_1")
            self.assertEqual(result.word_timeline[0]["source_material_id"], "")
            self.assertIsNone(result.word_timeline[0]["source_segment_id"])
            self.assertEqual(result.word_timeline[0]["debug_hints"]["current_video_material_id"], "main_video")
            self.assertEqual(result.word_timeline[0]["debug_hints"]["current_video_segment_id"], "video_seg_1")
            self.assertEqual(result.metadata["word_timeline_provider"]["selected_provider"], "draft_native_word")
            self.assertEqual(result.metadata["speech_timeline_granularity"], "word")

    def test_native_text_material_words_missing_timing_blocks(self) -> None:
        payload = _draft_payload()
        payload.pop("word_timeline")
        payload["materials"]["texts"][0]["words"] = [{"text": "示例"}]
        result, metadata = discover_draft_native_word_timeline(payload)

        self.assertEqual(result, [])
        self.assertEqual(metadata["invalid_word_row_count"], 1)

    def test_subtitle_and_sentence_timed_rows_remain_forbidden(self) -> None:
        words, metadata = discover_draft_native_word_timeline(
            {
                "subtitles": [{"text": "整句字幕", "start_us": 0, "duration_us": 1000000}],
                "sentences": [{"text": "整句话", "start": 0, "end": 1000000}],
            }
        )

        self.assertEqual(words, [])
        self.assertEqual(metadata["subtitle_as_word_rejected_count"], 2)


if __name__ == "__main__":
    unittest.main()
