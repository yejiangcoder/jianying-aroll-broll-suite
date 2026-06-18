from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21.ingest.real_draft_adapter import RealDraftIngestAdapter
from aroll_v21.ingest.word_timeline_provider import DefaultWordTimelineProvider
from tests.test_aroll_v21_real_draft_ingest_adapter import _draft_payload, _make_real_draft_skeleton


class ArollV21V32SpeechTimelineContractTests(unittest.TestCase):
    def test_draft_native_word_level_preferred_over_subtitle_phrase(self) -> None:
        payload = _draft_payload()
        result = DefaultWordTimelineProvider().load(
            draft_data=payload,
            text_materials=payload["materials"]["texts"],
            text_segments=[payload["tracks"][1]["segments"][0]],
            source_segments=[],
        )

        self.assertEqual(result.metadata["selected_provider"], "draft_native_word")
        self.assertEqual(result.metadata["speech_timeline_granularity"], "word")

    def test_subtitle_phrase_fallback_enabled_when_no_word_level(self) -> None:
        payload = _draft_payload()
        payload.pop("word_timeline")
        result = DefaultWordTimelineProvider().load(
            draft_data=payload,
            text_materials=payload["materials"]["texts"],
            text_segments=[payload["tracks"][1]["segments"][0]],
            source_segments=[
                {
                    **payload["tracks"][0]["segments"][0],
                    "track_type": "video",
                    "target_start_us": 0,
                    "target_end_us": 1_000_000,
                    "source_start_us": 0,
                    "source_end_us": 1_000_000,
                }
            ],
        )

        self.assertEqual(len(result.words), 1)
        self.assertEqual(result.metadata["selected_provider"], "draft_native_subtitle_phrase")
        self.assertEqual(result.metadata["speech_timeline_granularity"], "subtitle_phrase")

    def test_subtitle_phrase_fallback_reports_coarse_granularity(self) -> None:
        payload = _draft_payload()
        payload.pop("word_timeline")
        result = self._ingest_payload(payload)

        self.assertEqual(result.metadata["speech_timeline_granularity"], "subtitle_phrase")
        self.assertEqual(result.metadata["speech_timeline_precision"], "coarse")
        self.assertFalse(result.metadata["speech_timeline_can_cut_inside_caption"])

    def test_subtitle_phrase_fallback_does_not_fabricate_word_level(self) -> None:
        payload = _draft_payload()
        payload.pop("word_timeline")
        result = self._ingest_payload(payload)

        self.assertEqual(result.word_timeline[0]["speech_timeline_granularity"], "subtitle_phrase")
        self.assertFalse(result.word_timeline[0]["can_cut_inside_caption"])
        self.assertTrue(result.word_timeline[0]["word_id"].startswith("subtitle_phrase_"))

    def test_no_speech_timeline_fail_closed_with_clear_report(self) -> None:
        result = DefaultWordTimelineProvider().load(draft_data={}, text_materials=[], text_segments=[], source_segments=[])

        self.assertEqual(result.words, [])
        self.assertIn("REAL_DRAFT_SPEECH_TIMELINE_MISSING", [blocker.code for blocker in result.blockers])
        self.assertEqual(result.metadata["speech_timeline_provider"], "")

    def test_native_speech_mapping_ignores_audio_segments(self) -> None:
        payload = _draft_payload()
        audio_segment = dict(payload["tracks"][0]["segments"][0], id="audio_seg", track_type="audio")
        payload["tracks"][0]["segments"] = []
        payload["tracks"].insert(0, {"id": "audio_track", "type": "audio", "segments": [audio_segment]})

        result = self._ingest_payload(payload)

        self.assertIn("V21_SPEECH_TIMELINE_VIDEO_SOURCE_MISSING", [blocker.code for blocker in result.blockers])

    def test_native_speech_mapping_requires_primary_video_coverage(self) -> None:
        payload = _draft_payload()
        payload["tracks"][0]["segments"][0]["target_timerange"] = {"start": 2_000_000, "duration": 1_000_000}

        result = self._ingest_payload(payload)

        self.assertIn("V21_SPEECH_TIMELINE_VIDEO_SOURCE_MISSING", [blocker.code for blocker in result.blockers])

    def _ingest_payload(self, payload: dict):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir = _make_real_draft_skeleton(root)

            def fake_decrypt(_jy_draftc: Path, _encrypted: Path, output: Path) -> None:
                output.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")

            return RealDraftIngestAdapter(decrypt_func=fake_decrypt).load(draft_dir, root / "run")


if __name__ == "__main__":
    unittest.main()
