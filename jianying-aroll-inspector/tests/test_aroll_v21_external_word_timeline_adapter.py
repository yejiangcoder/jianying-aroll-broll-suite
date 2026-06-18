from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21.ingest import DraftIngest
from aroll_v21.ingest.external_word_timeline_adapter import ExternalWordTimelineAdapter


class ArollV21ExternalWordTimelineAdapterTests(unittest.TestCase):
    def test_complete_external_word_timeline_rows_are_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "word_timeline.json"
            path.write_text(json.dumps([{"text": "你", "source_start_us": 100, "source_end_us": 200}]), "utf-8")
            result = ExternalWordTimelineAdapter().load(path)
            self.assertEqual(result.blockers, [])
            self.assertEqual(result.words[0]["word_text"], "你")
            self.assertEqual(result.words[0]["start_us"], 100)

    def test_missing_source_time_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "word_timeline.json"
            path.write_text(json.dumps([{"text": "你", "source_start_us": 100}]), "utf-8")
            result = ExternalWordTimelineAdapter().load(path)
            self.assertEqual([blocker.code for blocker in result.blockers], ["EXTERNAL_WORD_TIMELINE_REQUIRED_FIELD_MISSING"])

    def test_external_words_do_not_promote_current_source_segment_to_canonical_word_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "word_timeline.json"
            path.write_text(
                json.dumps(
                    [
                        {
                            "text": "你",
                            "source_start_us": 100,
                            "source_end_us": 200,
                            "subtitle_uid": "s1",
                            "subtitle_index": 1,
                        }
                    ]
                ),
                "utf-8",
            )
            result = ExternalWordTimelineAdapter().load(path)
            graph = DraftIngest().build_source_graph(
                word_timeline=result.words,
                subtitles=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": "你"}],
                source_segments=[{"id": "clip1", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000}],
                text_materials=[],
                text_segments=[],
            )
            self.assertEqual(graph.words[0].source_material_id, "")
            self.assertIsNone(graph.words[0].source_segment_id)
            self.assertEqual(graph.source_segments[0]["id"], "clip1")


if __name__ == "__main__":
    unittest.main()
