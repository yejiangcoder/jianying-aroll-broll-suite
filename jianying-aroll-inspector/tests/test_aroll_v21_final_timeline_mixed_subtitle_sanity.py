from __future__ import annotations

import unittest

from aroll_v21.compiler import FinalTimelineCompiler
from aroll_v21.decision import SemanticDecisionPlanner
from aroll_v21.ingest import DraftIngest


class ArollV21FinalTimelineMixedSubtitleSanityTests(unittest.TestCase):
    def test_mixed_non_monotonic_subtitle_source_order_blocks(self) -> None:
        words = [
            {"word_id": "w006", "word_text": "就", "source_start_us": 1000, "source_end_us": 1100, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s006", "subtitle_index": 6},
            {"word_id": "w109", "word_text": "度", "source_start_us": 900, "source_end_us": 950, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s109", "subtitle_index": 109},
        ]
        graph = DraftIngest().build_source_graph(
            word_timeline=words,
            subtitles=[
                {"subtitle_uid": "s006", "subtitle_index": 6, "text": "就", "word_ids": ["w006"]},
                {"subtitle_uid": "s109", "subtitle_index": 109, "text": "度", "word_ids": ["w109"]},
            ],
            source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 2000}],
        )

        _timeline, blockers = FinalTimelineCompiler().compile(graph, SemanticDecisionPlanner().plan([]))

        self.assertIn("FINAL_TIMELINE_SEGMENT_UNSAFE_WORD_ORDER", [blocker.code for blocker in blockers])

    def test_oversized_multi_subtitle_group_blocks(self) -> None:
        words = []
        subtitles = []
        for index in range(1, 54):
            word_id = f"w{index:03d}"
            words.append(
                {
                    "word_id": word_id,
                    "word_text": "字",
                    "source_start_us": index * 1000,
                    "source_end_us": index * 1000 + 500,
                    "source_material_id": "main",
                    "source_segment_id": "clip",
                    "subtitle_uid": "s001",
                    "subtitle_index": 1,
                }
            )
        subtitles.append({"subtitle_uid": "s001", "subtitle_index": 1, "text": "字" * 53, "word_ids": [row["word_id"] for row in words]})
        graph = DraftIngest().build_source_graph(
            word_timeline=words,
            subtitles=subtitles,
            source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 100000}],
        )

        _timeline, blockers = FinalTimelineCompiler().compile(graph, SemanticDecisionPlanner().plan([]))

        self.assertIn("FINAL_TIMELINE_SEGMENT_OVERSIZED_WORD_COUNT", [blocker.code for blocker in blockers])


if __name__ == "__main__":
    unittest.main()
