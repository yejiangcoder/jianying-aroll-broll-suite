from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21.ingest.real_draft_adapter import RealDraftIngestAdapter
from tests.test_aroll_v21_real_draft_ingest_adapter import _draft_payload, _make_real_draft_skeleton


def _round7_payload(word_end_ms: int = 1440) -> dict:
    payload = _draft_payload()
    payload.pop("word_timeline")
    payload["tracks"][0]["segments"][0]["source_timerange"] = {"start": 0, "duration": 172_279_999}
    payload["tracks"][0]["segments"][0]["target_timerange"] = {"start": 0, "duration": 143_566_666}
    payload["tracks"][1]["segments"] = [
        {
            "id": "subtitle_seg_005",
            "material_id": "text_5",
            "target_timerange": {"start": 14_100_000, "duration": 1_433_333},
        }
    ]
    payload["materials"]["texts"][0]["id"] = "text_5"
    payload["materials"]["texts"][0]["text"] = "就像螃蟹效应一样"
    payload["materials"]["texts"][0]["recognize_text"] = "就像螃蟹效应一样"
    payload["materials"]["texts"][0]["words"] = {
        "start_time": [0, 200, 520, 800, 1080],
        "end_time": [200, 520, 800, 1040, word_end_ms],
        "text": ["就", "像", "螃蟹", "效应", "一样"],
    }
    return payload


class ArollV21NativeSourceTimeRound7SampleTests(unittest.TestCase):
    def test_round7_relative_word_time_adds_text_segment_target_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir = _make_real_draft_skeleton(root)
            payload = _round7_payload()

            def fake_decrypt(_jy_draftc: Path, _encrypted: Path, output: Path) -> None:
                output.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")

            result = RealDraftIngestAdapter(decrypt_func=fake_decrypt).load(draft_dir, root / "run")

            self.assertNotIn("NATIVE_WORD_TIME_OUTSIDE_TEXT_SEGMENT", [blocker.code for blocker in result.blockers])
            final_word = result.word_timeline[-1]
            self.assertEqual(final_word["word_text"], "一样")
            self.assertEqual(final_word["source_start_us"], 15_180_000)
            self.assertEqual(final_word["source_end_us"], 15_533_333)
            self.assertNotEqual(final_word["source_start_us"], 1_080_000)
            self.assertTrue(final_word["time_clamped_within_tolerance"])
            self.assertTrue(result.metadata["native_word_mapping"]["source_time_monotonic_by_subtitle"])


if __name__ == "__main__":
    unittest.main()
