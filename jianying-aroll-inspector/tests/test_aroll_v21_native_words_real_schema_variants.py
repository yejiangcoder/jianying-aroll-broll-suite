from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput
from aroll_v21.ingest.draft_native_word_timeline_discovery import discover_draft_native_word_timeline
from aroll_v21.ingest.real_draft_adapter import RealDraftIngestAdapter
from tests.test_aroll_v21_real_draft_ingest_adapter import _draft_payload, _make_real_draft_skeleton


class ArollV21NativeWordsRealSchemaVariantsTests(unittest.TestCase):
    def test_native_words_accept_start_time_end_time_variant(self) -> None:
        words, metadata = discover_draft_native_word_timeline(
            {
                "materials": {
                    "texts": [
                        {
                            "id": "text_1",
                            "words": [{"word": "真词", "start_time": 100, "end_time": 200}],
                        }
                    ]
                }
            }
        )

        self.assertEqual(len(words), 1)
        self.assertEqual(words[0]["word_text"], "真词")
        self.assertEqual(words[0]["start_us"], 100)
        self.assertEqual(words[0]["end_us"], 200)
        self.assertEqual(metadata["selected_path"], "/materials/texts[]/words")

    def test_native_words_accept_nested_time_range_variant(self) -> None:
        words, _metadata = discover_draft_native_word_timeline(
            {
                "materials": {
                    "texts": [
                        {
                            "id": "text_1",
                            "words": [{"token": "嵌套", "time_range": {"start": 300, "duration": 120}}],
                        }
                    ]
                }
            }
        )

        self.assertEqual(len(words), 1)
        self.assertEqual(words[0]["start_us"], 300)
        self.assertEqual(words[0]["end_us"], 420)

    def test_relative_subtitle_timing_maps_to_source_time_and_edit_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir = _make_real_draft_skeleton(root)
            payload = _draft_payload()
            payload.pop("word_timeline")
            payload["tracks"][0]["segments"][0]["source_timerange"] = {"start": 5000000, "duration": 2000000}
            payload["tracks"][0]["segments"][0]["target_timerange"] = {"start": 1000000, "duration": 2000000}
            payload["tracks"][1]["segments"][0]["target_timerange"] = {"start": 1200000, "duration": 800000}
            payload["materials"]["texts"][0]["words"] = [
                {"content": "相对", "start": 0, "duration": 300000},
                {"content": "字幕", "start": 300000, "duration": 300000},
            ]

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
            self.assertEqual(result.word_timeline[0]["source_end_us"], 1500000)
            self.assertEqual(
                result.word_timeline[0]["debug_hints"]["material_local_source_start_us"],
                5200000,
            )
            self.assertEqual(
                result.word_timeline[0]["debug_hints"]["material_local_source_end_us"],
                5500000,
            )
            self.assertIsNone(result.word_timeline[0]["source_segment_id"])
            self.assertEqual(result.word_timeline[0]["source_material_id"], "")
            self.assertTrue(report.source_graph.invariant_report.all_edit_units_have_word_ids)
            self.assertEqual(report.source_graph.edit_units[0].word_ids, ["real_word_000001", "real_word_000002"])


if __name__ == "__main__":
    unittest.main()
