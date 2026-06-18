from __future__ import annotations

import unittest

from aroll_v21.ingest import DraftIngest


class ArollV21NoWordsDiagnosticBindingTests(unittest.TestCase):
    def test_no_words_still_blocks_but_reports_diagnostic_source_segment_candidates(self) -> None:
        graph = DraftIngest().build_source_graph(
            word_timeline=[],
            subtitles=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": "整句字幕", "start_us": 100, "end_us": 900}],
            source_segments=[{"id": "clip_1", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000}],
            text_materials=[],
            text_segments=[],
        )

        self.assertFalse(graph.invariant_report.single_source_graph_ok)
        self.assertEqual(graph.edit_units[0].word_ids, [])
        blockers = [blocker for blocker in graph.invariant_report.blockers if blocker.code == "EDIT_UNIT_WORD_BINDING_MISSING"]
        self.assertEqual(len(blockers), 1)
        context = blockers[0].context
        self.assertEqual(context["binding_status"], "diagnostic_only")
        self.assertEqual(context["candidate_source_segment_id"], "clip_1")
        self.assertEqual(context["candidate_source_material_id"], "main_video")
        self.assertTrue(context["diagnostic_source_segment_candidates"])
        self.assertIn("SOURCE_WORD_TIMELINE_EMPTY", [blocker.code for blocker in graph.invariant_report.blockers])


if __name__ == "__main__":
    unittest.main()
