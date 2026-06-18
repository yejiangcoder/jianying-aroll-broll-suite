from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput
from aroll_v21.ingest.external_word_timeline_adapter import ExternalWordTimelineAdapter


class ArollV21DraftAgnosticInputContractTests(unittest.TestCase):
    def test_external_word_timeline_strips_physical_ids_into_debug_hints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "words.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "word_id": "w1",
                            "text": "Alpha",
                            "source_start_us": 0,
                            "source_end_us": 500_000,
                            "source_segment_id": "old_source_segment",
                            "source_material_id": "old_source_material",
                            "track_id": "old_track",
                        }
                    ]
                ),
                "utf-8",
            )

            result = ExternalWordTimelineAdapter().load(path)

            self.assertFalse(result.blockers)
            self.assertNotIn("source_segment_id", result.words[0])
            self.assertNotIn("source_material_id", result.words[0])
            self.assertEqual(result.words[0]["debug_hints"]["legacy_source_segment_id"], "old_source_segment")
            self.assertEqual(result.words[0]["debug_hints"]["legacy_source_material_id"], "old_source_material")
            self.assertEqual(result.metadata["stripped_physical_id_count"], 3)

    def test_source_graph_and_final_timeline_do_not_promote_old_physical_ids_to_canonical_truth(self) -> None:
        engine = ArollEngine()
        report = engine.run(
            ArollRunInput(
                mode="dry-run",
                draft_data={},
                word_timeline=[
                    {
                        "word_id": "w1",
                        "word_text": "Alpha",
                        "start_us": 0,
                        "end_us": 500_000,
                        "subtitle_index": 1,
                        "source_segment_id": "old_source_segment",
                        "source_material_id": "old_source_material",
                    }
                ],
                subtitles=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": "Alpha", "word_ids": ["w1"]}],
                source_segments=[],
                source_materials=[],
                text_materials=[{"id": "caption_template", "text": "Alpha", "content": {"text": "Alpha"}, "type": "subtitle"}],
                text_segments=[
                    {
                        "id": "caption_segment",
                        "material_id": "caption_template",
                        "target_timerange": {"start": 0, "duration": 500_000},
                        "track_id": "text_track",
                        "track_type": "text",
                    }
                ],
            )
        )

        self.assertTrue(report.final_timeline)
        self.assertEqual(report.source_graph.words[0].source_material_id, "")
        self.assertIsNone(report.source_graph.words[0].source_segment_id)
        self.assertEqual(report.source_graph.words[0].debug_hints["legacy_source_segment_id"], "old_source_segment")
        self.assertEqual(report.final_timeline[0].source_material_id, "")
        self.assertIsNone(report.final_timeline[0].source_segment_id)


if __name__ == "__main__":
    unittest.main()
