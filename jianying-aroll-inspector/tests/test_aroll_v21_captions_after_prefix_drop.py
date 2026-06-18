from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from aroll_v21.compiler import FinalTimelineCompiler
from aroll_v21.ingest import DraftIngest
from aroll_v21.render import SubtitleRenderer
from aroll_v21.writer import CaptionMaterialWriter
from tests.test_aroll_v21_final_timeline_pre_emit_prefix_drop import _drop_middle_plan, _graph_with_middle_unit


ROOT = Path(__file__).resolve().parents[1]


def _template_rows() -> tuple[list[dict], list[dict]]:
    fixture = json.loads((ROOT / "fixtures" / "real_materials" / "normal_caption_template.json").read_text("utf-8"))
    material = copy.deepcopy(fixture["material"])
    segment = copy.deepcopy(fixture["segment"])
    material["id"] = "template_text"
    segment["id"] = "template_segment"
    segment["material_id"] = "template_text"
    return [material], [segment]


class ArollV21CaptionsAfterPrefixDropTests(unittest.TestCase):
    def test_captions_and_material_plan_follow_pre_emit_prefix_drop(self) -> None:
        graph = _graph_with_middle_unit("评论区也全是哇", "中间", "评论区也全是哇塞")
        materials, segments = _template_rows()
        graph = DraftIngest().build_source_graph(
            word_timeline=[
                {
                    "word_id": word.word_id,
                    "word_text": word.text,
                    "source_start_us": word.source_start_us,
                    "source_end_us": word.source_end_us,
                    "source_material_id": word.source_material_id,
                    "source_segment_id": word.source_segment_id,
                    "subtitle_uid": word.subtitle_uid,
                    "subtitle_index": word.subtitle_index,
                }
                for word in graph.words
            ],
            subtitles=[
                {"subtitle_uid": "s_left", "subtitle_index": 1, "text": "评论区也全是哇", "word_ids": ["w_left"], "text_material_id": "template_text"},
                {"subtitle_uid": "s_middle", "subtitle_index": 2, "text": "中间", "word_ids": ["w_middle"], "text_material_id": "template_text"},
                {"subtitle_uid": "s_right", "subtitle_index": 3, "text": "评论区也全是哇塞", "word_ids": ["w_right"], "text_material_id": "template_text"},
            ],
            source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 2_000_000}],
            text_materials=materials,
            text_segments=segments,
        )
        final_timeline, blockers = FinalTimelineCompiler().compile(graph, _drop_middle_plan())
        captions = SubtitleRenderer().render(final_timeline, graph)
        material_write_plan, writer_blockers = CaptionMaterialWriter().build_write_plan(graph, captions)

        self.assertEqual(blockers, [])
        self.assertEqual(writer_blockers, [])
        self.assertEqual([caption.text for caption in captions], ["评论区也全是哇塞"])
        self.assertEqual(len(material_write_plan["materials"]), len(captions))
        self.assertEqual(len(material_write_plan["segments"]), len(captions))


if __name__ == "__main__":
    unittest.main()
