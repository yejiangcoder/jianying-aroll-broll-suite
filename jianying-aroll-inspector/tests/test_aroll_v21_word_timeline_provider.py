from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21.ingest.real_draft_adapter import RealDraftIngestAdapter
from aroll_v21.ingest.word_timeline_provider import DefaultWordTimelineProvider

from tests.test_aroll_v21_real_draft_ingest_adapter import _draft_payload, _make_real_draft_skeleton


class ArollV21WordTimelineProviderTests(unittest.TestCase):
    def test_no_speech_timeline_continues_to_block(self) -> None:
        result = DefaultWordTimelineProvider().load(draft_data={})
        self.assertEqual(result.words, [])
        self.assertIn("REAL_DRAFT_SPEECH_TIMELINE_MISSING", [blocker.code for blocker in result.blockers])

    def test_external_provider_has_priority_when_explicitly_passed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            external = root / "word_timeline.json"
            external.write_text(
                json.dumps([{"text": "外部", "source_start_us": 0, "source_end_us": 1000}], ensure_ascii=False),
                "utf-8",
            )
            result = DefaultWordTimelineProvider().load(
                draft_data={"words": [{"word_text": "草稿", "start_us": 0, "end_us": 1000}]},
                external_path=external,
            )
            self.assertEqual(result.words[0]["word_text"], "外部")
            self.assertEqual(result.metadata["selected_provider"], "external")

    def test_real_draft_adapter_accepts_external_word_timeline_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir = _make_real_draft_skeleton(root)
            payload = _draft_payload()
            payload.pop("word_timeline")
            external = root / "word_timeline.json"
            external.write_text(
                json.dumps(
                    [
                        {
                            "text": "示例字幕",
                            "source_start_us": 0,
                            "source_end_us": 1000000,
                            "source_material_id": "main_video",
                            "source_segment_id": "video_seg_1",
                            "subtitle_uid": "subtitle_seg_1",
                            "subtitle_index": 1,
                        }
                    ],
                    ensure_ascii=False,
                ),
                "utf-8",
            )

            def fake_decrypt(_jy_draftc: Path, _encrypted: Path, output: Path) -> None:
                output.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")

            result = RealDraftIngestAdapter(decrypt_func=fake_decrypt).load(
                draft_dir,
                root / "run",
                word_timeline_json=external,
            )
            self.assertEqual(result.blockers, [])
            self.assertEqual(len(result.word_timeline), 1)
            self.assertEqual(result.metadata["word_timeline_provider"]["selected_provider"], "external")


if __name__ == "__main__":
    unittest.main()
