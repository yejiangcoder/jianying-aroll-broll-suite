from __future__ import annotations

import unittest

from aroll_v21.compiler import FinalTimelineCompiler
from aroll_v21.decision.final_target_repeat_resolver import FinalTargetRepeatResolver
from aroll_v21.ingest import DraftIngest
from aroll_v21.ir import DecisionPlan
from aroll_v21.render import SubtitleRenderer
from aroll_v21.writer import CaptionMaterialWriter
from tests.test_aroll_v21_captions_after_prefix_drop import _template_rows
from tests.test_aroll_v21_final_target_repeat_resolver import segment


class ArollV21FinalTargetRepeatNearDuplicateAutoDropTests(unittest.TestCase):
    def test_six_high_exact_duplicate_fixtures_drop_recommended_segments(self) -> None:
        duplicate_texts = [
            "恨不得给人家当牛做马",
            "人家年少的时候",
            "你说是死肌肉",
            "把那个敢于",
            "跟着老子",
            "把输掉的",
        ]
        segments = []
        index = 1
        for text in duplicate_texts:
            segments.append(segment(index, text))
            index += 1
            segments.append(segment(index, text))
            index += 1
        plan = DecisionPlan(decisions=[])

        final_timeline, blockers = FinalTargetRepeatResolver().resolve(segments, plan)

        self.assertEqual(blockers, [])
        self.assertEqual([row.text for row in final_timeline], duplicate_texts)
        self.assertEqual(len([row for row in plan.decision_trace if row.get("decision") == "auto_drop_high_confidence_exact_repeat"]), 6)
        for left, right in zip(final_timeline, final_timeline[1:]):
            self.assertEqual(left.target_end_us, right.target_start_us)

    def test_captions_and_material_plan_align_after_final_target_drop(self) -> None:
        materials, text_segments = _template_rows()
        graph = DraftIngest().build_source_graph(
            word_timeline=[
                {
                    "word_id": "w_001",
                    "word_text": "把输掉的",
                    "source_start_us": 0,
                    "source_end_us": 300_000,
                    "source_material_id": "main",
                    "source_segment_id": "clip",
                    "subtitle_uid": "s_001",
                    "subtitle_index": 1,
                },
                {
                    "word_id": "w_002",
                    "word_text": "把输掉的",
                    "source_start_us": 400_000,
                    "source_end_us": 700_000,
                    "source_material_id": "main",
                    "source_segment_id": "clip",
                    "subtitle_uid": "s_002",
                    "subtitle_index": 2,
                },
            ],
            subtitles=[
                {"subtitle_uid": "s_001", "subtitle_index": 1, "text": "把输掉的", "word_ids": ["w_001"], "text_material_id": "template_text"},
                {"subtitle_uid": "s_002", "subtitle_index": 2, "text": "把输掉的", "word_ids": ["w_002"], "text_material_id": "template_text"},
            ],
            source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 1_000_000}],
            text_materials=materials,
            text_segments=text_segments,
        )

        final_timeline, blockers = FinalTimelineCompiler().compile(graph, DecisionPlan(decisions=[]))
        captions = SubtitleRenderer().render(final_timeline, graph)
        material_write_plan, writer_blockers = CaptionMaterialWriter().build_write_plan(graph, captions)

        self.assertEqual(blockers, [])
        self.assertEqual(writer_blockers, [])
        self.assertEqual([segment.text for segment in final_timeline], ["把输掉的"])
        self.assertEqual([caption.text for caption in captions], ["把输掉的"])
        self.assertEqual(len(material_write_plan["materials"]), len(captions))
        self.assertEqual(len(material_write_plan["segments"]), len(captions))


if __name__ == "__main__":
    unittest.main()
