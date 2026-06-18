from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput
from aroll_v21.ingest.draft_native_word_timeline_discovery import discover_draft_native_word_timeline
from aroll_v21.ingest.real_draft_adapter import RealDraftIngestAdapter
from tests.test_aroll_v21_real_draft_ingest_adapter import _draft_payload, _make_real_draft_skeleton


class ArollV21NativeWordsDictOfArraysTests(unittest.TestCase):
    def test_dict_of_arrays_words_converts_to_word_rows(self) -> None:
        words, metadata = discover_draft_native_word_timeline(
            {},
            text_materials=[
                {
                    "id": "text_001",
                    "current_words": {},
                    "words": {
                        "start_time": [0, 320, 760, 840],
                        "end_time": [240, 640, 840, 1040],
                        "text": ["就", "国南", "能", "不能"],
                    },
                }
            ],
        )

        self.assertEqual([row["word_text"] for row in words], ["就", "国南", "能", "不能"])
        self.assertEqual(words[0]["start_us"], 0)
        self.assertEqual(words[0]["end_us"], 240000)
        self.assertEqual(words[1]["start_us"], 320000)
        self.assertEqual(metadata["materials_with_words_key"], 1)
        self.assertEqual(metadata["materials_with_nonempty_words"], 1)
        self.assertEqual(metadata["candidate_count"], 4)
        self.assertEqual(metadata["accepted_count"], 4)
        self.assertEqual(metadata["rejected_count"], 0)

    def test_dict_of_arrays_length_mismatch_rejects_with_reason(self) -> None:
        words, metadata = discover_draft_native_word_timeline(
            {},
            text_materials=[
                {
                    "id": "text_001",
                    "words": {
                        "start_time": [0, 320],
                        "end_time": [240],
                        "text": ["就", "国南"],
                    },
                }
            ],
        )

        self.assertEqual(words, [])
        self.assertEqual(metadata["materials_with_words_key"], 1)
        self.assertEqual(metadata["materials_with_nonempty_words"], 1)
        self.assertEqual(metadata["candidate_count"], 1)
        self.assertEqual(metadata["accepted_count"], 0)
        self.assertEqual(metadata["rejected_count"], 1)
        self.assertEqual(metadata["sample_rejections"][0]["reason"], "dict_of_arrays_length_mismatch")

    def test_current_words_empty_dict_is_ignored(self) -> None:
        words, metadata = discover_draft_native_word_timeline(
            {},
            text_materials=[{"id": "text_001", "current_words": {}, "words": {}}],
        )

        self.assertEqual(words, [])
        self.assertEqual(metadata["materials_with_words_key"], 1)
        self.assertEqual(metadata["materials_with_nonempty_words"], 0)
        self.assertEqual(metadata["candidate_count"], 0)

    def test_real_adapter_maps_dict_of_arrays_ms_to_source_time_and_edit_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir = _make_real_draft_skeleton(root)
            payload = _draft_payload()
            payload.pop("word_timeline")
            payload["tracks"][0]["segments"][0]["source_timerange"] = {"start": 5000000, "duration": 2000000}
            payload["tracks"][0]["segments"][0]["target_timerange"] = {"start": 1000000, "duration": 2000000}
            payload["tracks"][1]["segments"][0]["target_timerange"] = {"start": 1200000, "duration": 1200000}
            payload["materials"]["texts"][0]["current_words"] = {}
            payload["materials"]["texts"][0]["words"] = {
                "start_time": [0, 320],
                "end_time": [240, 640],
                "text": ["就", "国南"],
            }

            def fake_decrypt(_jy_draftc: Path, _encrypted: Path, output: Path) -> None:
                output.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")

            result = RealDraftIngestAdapter(decrypt_func=fake_decrypt).load(draft_dir, root / "run")
            report = ArollEngine().run(
                ArollRunInput(
                    draft_data=result.draft_data,
                    word_timeline=result.word_timeline,
                    subtitles=result.subtitles,
                    source_segments=result.source_segments,
                    source_materials=result.source_materials,
                    text_materials=result.text_materials,
                    text_segments=result.text_segments,
                    ingest_blockers=result.blockers,
                    ingest_metadata=result.metadata,
                    postwrite_mode="simulated",
                )
            )

            self.assertEqual([blocker.code for blocker in result.blockers], [])
            self.assertEqual(len(result.word_timeline), 2)
            self.assertEqual(result.word_timeline[0]["source_start_us"], 1200000)
            self.assertEqual(result.word_timeline[0]["source_end_us"], 1440000)
            self.assertEqual(
                result.word_timeline[0]["debug_hints"]["material_local_source_start_us"],
                5200000,
            )
            self.assertEqual(
                result.word_timeline[0]["debug_hints"]["material_local_source_end_us"],
                5440000,
            )
            self.assertIsNone(result.word_timeline[0]["source_segment_id"])
            self.assertEqual(result.word_timeline[0]["source_material_id"], "")
            self.assertEqual(result.metadata["word_timeline_provider"]["draft_native"]["candidate_count"], 2)
            self.assertTrue(report.source_graph.words)
            self.assertTrue(report.source_graph.invariant_report.all_edit_units_have_word_ids)


if __name__ == "__main__":
    unittest.main()
