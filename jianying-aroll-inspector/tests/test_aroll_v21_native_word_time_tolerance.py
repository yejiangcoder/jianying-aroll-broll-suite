from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21.ingest.real_draft_adapter import RealDraftIngestAdapter, TEXT_WORD_TIME_TOLERANCE_US
from tests.test_aroll_v21_real_draft_ingest_adapter import _draft_payload, _make_real_draft_skeleton


def _payload_with_end(end_ms: int) -> dict:
    payload = _draft_payload()
    payload.pop("word_timeline")
    payload["tracks"][0]["segments"][0]["source_timerange"] = {"start": 0, "duration": 10_000_000}
    payload["tracks"][0]["segments"][0]["target_timerange"] = {"start": 0, "duration": 10_000_000}
    payload["tracks"][1]["segments"][0]["target_timerange"] = {"start": 2_000_000, "duration": 1_000_000}
    payload["materials"]["texts"][0]["words"] = {"start_time": [880], "end_time": [end_ms], "text": ["词"]}
    return payload


def _load_payload(payload: dict) -> tuple[list[str], dict, dict]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        draft_dir = _make_real_draft_skeleton(root)

        def fake_decrypt(_jy_draftc: Path, _encrypted: Path, output: Path) -> None:
            output.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")

        result = RealDraftIngestAdapter(decrypt_func=fake_decrypt).load(draft_dir, root / "run")
        word = result.word_timeline[0] if result.word_timeline else {}
        return [blocker.code for blocker in result.blockers], word, result.metadata["native_word_mapping"]


class ArollV21NativeWordTimeToleranceTests(unittest.TestCase):
    def test_end_time_within_80ms_tolerance_is_clamped(self) -> None:
        blockers, word, metadata = _load_payload(_payload_with_end(1000 + TEXT_WORD_TIME_TOLERANCE_US // 1000))

        self.assertNotIn("NATIVE_WORD_TIME_OUTSIDE_TEXT_SEGMENT", blockers)
        self.assertEqual(word["target_end_us"], 3_000_000)
        self.assertTrue(word["time_clamped_within_tolerance"])
        self.assertEqual(metadata["time_clamped_within_tolerance_count"], 1)

    def test_end_time_over_80ms_tolerance_blocks(self) -> None:
        blockers, _word, metadata = _load_payload(_payload_with_end(1000 + TEXT_WORD_TIME_TOLERANCE_US // 1000 + 1))

        self.assertIn("NATIVE_WORD_TIME_OUTSIDE_TEXT_SEGMENT", blockers)
        self.assertEqual(metadata["time_clamped_within_tolerance_count"], 0)


if __name__ == "__main__":
    unittest.main()
