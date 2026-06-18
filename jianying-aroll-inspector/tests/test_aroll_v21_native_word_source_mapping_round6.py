from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput
from aroll_v21.ingest.real_draft_adapter import RealDraftIngestAdapter
from tests.test_aroll_v21_real_draft_ingest_adapter import _draft_payload, _make_real_draft_skeleton


class ArollV21NativeWordSourceMappingRound6Tests(unittest.TestCase):
    def test_dict_array_times_map_through_nested_clip_target_timerange(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir = _make_real_draft_skeleton(root)
            payload = _draft_payload()
            payload.pop("word_timeline")
            payload["tracks"][0]["segments"][0]["source_timerange"] = {"start": 5_000_000, "duration": 5_000_000}
            payload["tracks"][0]["segments"][0]["target_timerange"] = {"start": 1_000_000, "duration": 5_000_000}
            payload["tracks"][1]["segments"] = [
                {
                    "id": "subtitle_seg_1",
                    "material_id": "text_1",
                    "clip": {"target_timerange": {"start": 1_200_000, "duration": 1_000_000}},
                },
                {
                    "id": "subtitle_seg_2",
                    "material_id": "text_2",
                    "clip": {"target_timerange": {"start": 2_600_000, "duration": 1_000_000}},
                },
            ]
            payload["materials"]["texts"].append(dict(payload["materials"]["texts"][0], id="text_2"))
            payload["materials"]["texts"][0]["words"] = {
                "start_time": [0, 320],
                "end_time": [240, 640],
                "text": ["就", "国南"],
            }
            payload["materials"]["texts"][1]["words"] = {
                "start_time": [0, 200],
                "end_time": [120, 420],
                "text": ["能", "不能"],
            }

            def fake_decrypt(_jy_draftc: Path, _encrypted: Path, output: Path) -> None:
                output.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")

            result = RealDraftIngestAdapter(decrypt_func=fake_decrypt).load(draft_dir, root / "run")
            metadata = result.metadata["native_word_mapping"]

            self.assertEqual([blocker.code for blocker in result.blockers], [])
            self.assertEqual([row["source_start_us"] for row in result.word_timeline], [1_200_000, 1_520_000, 2_600_000, 2_800_000])
            self.assertEqual(
                [row["debug_hints"]["material_local_source_start_us"] for row in result.word_timeline],
                [5_200_000, 5_520_000, 6_600_000, 6_800_000],
            )
            self.assertEqual(metadata["accepted_count"], 4)
            self.assertEqual(metadata["mapped_to_text_segment_count"], 4)
            self.assertEqual(metadata["mapped_to_source_segment_count"], 4)
            self.assertEqual(metadata["relative_time_count"], 4)
            self.assertTrue(metadata["source_time_monotonic_by_subtitle"])
            self.assertEqual(metadata["source_time_out_of_segment_count"], 0)

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
            self.assertTrue(report.source_graph.invariant_report.all_edit_units_have_word_ids)
            self.assertEqual([word.source_start_us for word in report.source_graph.words], [1_200_000, 1_520_000, 2_600_000, 2_800_000])

    def test_unmapped_relative_word_blocks_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir = _make_real_draft_skeleton(root)
            payload = _draft_payload()
            payload.pop("word_timeline")
            payload["tracks"][1]["segments"][0].pop("target_timerange")
            payload["materials"]["texts"][0]["words"] = {"start_time": [0], "end_time": [240], "text": ["就"]}

            def fake_decrypt(_jy_draftc: Path, _encrypted: Path, output: Path) -> None:
                output.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")

            result = RealDraftIngestAdapter(decrypt_func=fake_decrypt).load(draft_dir, root / "run")

            self.assertIn("NATIVE_WORD_TEXT_SEGMENT_BINDING_MISSING", [blocker.code for blocker in result.blockers])


if __name__ == "__main__":
    unittest.main()
