from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21.ingest.real_draft_adapter import RealDraftIngestAdapter
from tests.test_aroll_v21_real_draft_ingest_adapter import _draft_payload, _make_real_draft_skeleton


class ArollV21ProviderDebugMetadataOnSuccessTests(unittest.TestCase):
    def test_successful_native_ingest_outputs_provider_and_mapping_debug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir = _make_real_draft_skeleton(root)
            payload = _draft_payload()
            payload.pop("word_timeline")
            payload["materials"]["texts"][0]["words"] = {"start_time": [0], "end_time": [240], "text": ["就"]}

            def fake_decrypt(_jy_draftc: Path, _encrypted: Path, output: Path) -> None:
                output.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")

            result = RealDraftIngestAdapter(decrypt_func=fake_decrypt).load(draft_dir, root / "run")
            provider = result.metadata["word_timeline_provider"]["draft_native"]
            mapping = result.metadata["word_timeline_provider"]["native_word_mapping"]

            self.assertEqual(provider["candidate_count"], 1)
            self.assertEqual(provider["accepted_count"], 1)
            self.assertEqual(provider["materials_with_nonempty_words"], 1)
            self.assertEqual(mapping["accepted_count"], 1)
            self.assertEqual(mapping["mapped_to_text_segment_count"], 1)
            self.assertEqual(mapping["mapped_to_source_segment_count"], 1)
            self.assertTrue(mapping["sample_mapped_words"])


if __name__ == "__main__":
    unittest.main()
