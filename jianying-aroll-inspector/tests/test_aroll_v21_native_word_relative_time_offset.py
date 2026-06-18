from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21.ingest.real_draft_adapter import RealDraftIngestAdapter
from tests.test_aroll_v21_real_draft_ingest_adapter import _draft_payload, _make_real_draft_skeleton


class ArollV21NativeWordRelativeTimeOffsetTests(unittest.TestCase):
    def test_native_dict_array_start_time_is_never_used_as_global_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir = _make_real_draft_skeleton(root)
            payload = _draft_payload()
            payload.pop("word_timeline")
            payload["tracks"][0]["segments"][0]["source_timerange"] = {"start": 5_000_000, "duration": 20_000_000}
            payload["tracks"][0]["segments"][0]["target_timerange"] = {"start": 10_000_000, "duration": 20_000_000}
            payload["tracks"][1]["segments"][0]["target_timerange"] = {"start": 14_100_000, "duration": 2_000_000}
            payload["materials"]["texts"][0]["words"] = {
                "start_time": [1080],
                "end_time": [1440],
                "text": ["一样"],
            }

            def fake_decrypt(_jy_draftc: Path, _encrypted: Path, output: Path) -> None:
                output.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")

            result = RealDraftIngestAdapter(decrypt_func=fake_decrypt).load(draft_dir, root / "run")

            self.assertEqual([blocker.code for blocker in result.blockers], [])
            word = result.word_timeline[0]
            self.assertEqual(word["target_start_us"], 15_180_000)
            self.assertEqual(word["source_start_us"], 15_180_000)
            self.assertNotEqual(word["source_start_us"], 1_080_000)
            self.assertEqual(word["debug_hints"]["material_local_source_start_us"], 10_180_000)


if __name__ == "__main__":
    unittest.main()
