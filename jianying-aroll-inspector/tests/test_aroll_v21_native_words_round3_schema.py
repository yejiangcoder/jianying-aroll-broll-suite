from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput
from aroll_v21.ingest.real_draft_adapter import RealDraftIngestAdapter
from tests.test_aroll_v21_real_draft_ingest_adapter import _draft_payload, _make_real_draft_skeleton


class ArollV21NativeWordsRound3SchemaTests(unittest.TestCase):
    def test_round3_like_text_material_words_bind_to_edit_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir = _make_real_draft_skeleton(root)
            payload = _draft_payload()
            payload.pop("word_timeline")
            payload["tracks"][0]["segments"][0]["source_timerange"] = {"start": 7000000, "duration": 1000000}
            payload["tracks"][0]["segments"][0]["target_timerange"] = {"start": 3000000, "duration": 1000000}
            payload["tracks"][1]["segments"][0]["target_timerange"] = {"start": 3200000, "duration": 500000}
            payload["materials"]["texts"][0]["words"] = [
                {"word": "真实", "time_range": {"start": 0, "duration": 200000}},
                {"word": "字幕", "time_range": {"start": 200000, "duration": 300000}},
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
            self.assertEqual(result.word_timeline[0]["source_start_us"], 3200000)
            self.assertEqual(result.word_timeline[1]["source_end_us"], 3700000)
            self.assertEqual(
                result.word_timeline[0]["debug_hints"]["material_local_source_start_us"],
                7200000,
            )
            self.assertEqual(
                result.word_timeline[1]["debug_hints"]["material_local_source_end_us"],
                7700000,
            )
            self.assertIsNone(result.word_timeline[0]["source_segment_id"])
            self.assertEqual(result.word_timeline[0]["source_material_id"], "")
            self.assertTrue(report.source_graph.invariant_report.single_source_graph_ok)
            self.assertTrue(report.source_graph.invariant_report.all_edit_units_have_word_ids)


if __name__ == "__main__":
    unittest.main()
