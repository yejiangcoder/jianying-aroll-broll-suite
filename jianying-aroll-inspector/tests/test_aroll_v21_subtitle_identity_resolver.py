from __future__ import annotations

import unittest

from aroll_v21.ingest import DraftIngest
from aroll_v21.ir import CaptionRenderUnit
from aroll_v21.writer import SubtitleIdentityResolver
from tests.test_aroll_v21_caption_template_round5_position_y_minus_073 import (
    _round5_caption_material,
    _round5_caption_segment,
)


class ArollV21SubtitleIdentityResolverTests(unittest.TestCase):
    def test_normalized_sub_uid_maps_to_real_subtitle_index_material(self) -> None:
        material = _round5_caption_material("real_text_uuid")
        graph = DraftIngest().build_source_graph(
            word_timeline=[
                {"word_id": "w1", "word_text": "字", "start_us": 0, "end_us": 100000, "subtitle_uid": "sub_000001", "subtitle_index": 1}
            ],
            subtitles=[{"subtitle_uid": "real_subtitle_uuid", "subtitle_index": 1, "text": "字", "word_ids": ["w1"], "text_material_id": "real_text_uuid"}],
            source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 1000000}],
            text_materials=[material],
            text_segments=[_round5_caption_segment("real_text_uuid")],
        )
        captions = [
            CaptionRenderUnit(
                caption_id="cap",
                timeline_segment_ids=["timeline"],
                word_ids=["w1"],
                text="字",
                target_start_us=0,
                target_end_us=100000,
                source_subtitle_uids=["sub_000001"],
                style_template_id="canonical_caption_template",
            )
        ]

        ids = SubtitleIdentityResolver().material_ids_for_captions(graph, captions)

        self.assertEqual(ids, {"real_text_uuid"})


if __name__ == "__main__":
    unittest.main()
