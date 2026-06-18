from __future__ import annotations

import unittest

from aroll_v21.ingest import DraftIngest


class ArollV21SourceMaterialInventoryTests(unittest.TestCase):
    def test_source_materials_are_derived_from_source_segments_when_needed(self) -> None:
        graph = DraftIngest().build_source_graph(
            word_timeline=[
                {"word_id": "w1", "word_text": "甲", "start_us": 0, "end_us": 100, "subtitle_uid": "s1"}
            ],
            subtitles=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": "甲"}],
            source_segments=[{"id": "clip1", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000}],
            text_materials=[],
            text_segments=[],
        )
        self.assertTrue(graph.source_materials)
        self.assertEqual(graph.source_materials[0]["source_material_id"], "main_video")
        self.assertTrue(graph.invariant_report.single_source_graph_ok)

    def test_missing_source_material_id_is_explicit_blocker(self) -> None:
        graph = DraftIngest().build_source_graph(
            word_timeline=[{"word_id": "w1", "word_text": "甲", "start_us": 0, "end_us": 100, "subtitle_uid": "s1"}],
            subtitles=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": "甲"}],
            source_segments=[{"id": "clip1", "source_start_us": 0, "source_end_us": 1000}],
            text_materials=[],
            text_segments=[],
        )
        self.assertIn("SOURCE_SEGMENT_MATERIAL_UNBOUND", [blocker.code for blocker in graph.invariant_report.blockers])

    def test_explicit_empty_source_material_inventory_blocks(self) -> None:
        graph = DraftIngest().build_source_graph(
            word_timeline=[
                {"word_id": "w1", "word_text": "甲", "start_us": 0, "end_us": 100, "source_material_id": "main", "subtitle_uid": "s1"}
            ],
            subtitles=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": "甲"}],
            source_segments=[{"id": "clip1", "material_id": "main", "source_start_us": 0, "source_end_us": 1000}],
            source_materials=[],
            text_materials=[],
            text_segments=[],
        )
        self.assertIn("SOURCE_MATERIAL_INVENTORY_EMPTY", [blocker.code for blocker in graph.invariant_report.blockers])

    def test_segment_material_absent_from_explicit_inventory_blocks(self) -> None:
        graph = DraftIngest().build_source_graph(
            word_timeline=[
                {"word_id": "w1", "word_text": "甲", "start_us": 0, "end_us": 100, "source_material_id": "main", "subtitle_uid": "s1"}
            ],
            subtitles=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": "甲"}],
            source_segments=[{"id": "clip1", "material_id": "main", "source_start_us": 0, "source_end_us": 1000}],
            source_materials=[{"source_material_id": "other", "path": "", "duration_us": 1000, "type": "video", "metadata": {}}],
            text_materials=[],
            text_segments=[],
        )
        self.assertIn("SOURCE_SEGMENT_MATERIAL_NOT_IN_INVENTORY", [blocker.code for blocker in graph.invariant_report.blockers])


if __name__ == "__main__":
    unittest.main()
