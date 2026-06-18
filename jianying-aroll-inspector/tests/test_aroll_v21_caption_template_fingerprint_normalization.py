from __future__ import annotations

import copy
import json
import unittest

from aroll_v21.ingest import DraftIngest
from aroll_v21.ir import CaptionRenderUnit
from aroll_v21.writer import CaptionMaterialWriter
from tests.test_aroll_v21_caption_template_round5_position_y_minus_073 import (
    _round5_caption_material,
    _round5_caption_segment,
)


def _with_text(material: dict, text: str) -> dict:
    row = copy.deepcopy(material)
    payload = json.loads(row["content"])
    payload["text"] = text
    payload["styles"][0]["range"]["end"] = len(text)
    row["content"] = json.dumps(payload, ensure_ascii=False)
    row["base_content"] = json.dumps(payload, ensure_ascii=False)
    row["recognize_text"] = text
    return row


class ArollV21CaptionTemplateFingerprintNormalizationTests(unittest.TestCase):
    def test_110_same_style_different_text_ids_and_ranges_collapse_to_one_group(self) -> None:
        materials = []
        segments = []
        subtitles = []
        captions = []
        words = []
        for index in range(1, 111):
            material_id = f"caption_{index:03d}"
            subtitle_uid = f"s{index:03d}"
            word_id = f"w{index:03d}"
            material = _with_text(_round5_caption_material(material_id), "字幕" * (index % 5 + 1))
            segment = _round5_caption_segment(material_id)
            segment["id"] = f"caption_segment_{index:03d}"
            material["created_at"] = index
            materials.append(material)
            segments.append(segment)
            subtitles.append({"subtitle_uid": subtitle_uid, "subtitle_index": index, "text": material["recognize_text"], "word_ids": [word_id], "text_material_id": material_id})
            words.append({"word_id": word_id, "word_text": "字", "start_us": index * 100000, "end_us": index * 100000 + 50000, "subtitle_uid": subtitle_uid, "subtitle_index": index})
            captions.append(
                CaptionRenderUnit(
                    caption_id=f"cap_{index:03d}",
                    timeline_segment_ids=[f"timeline_{index:03d}"],
                    word_ids=[word_id],
                    text="输出字幕",
                    target_start_us=index * 100000,
                    target_end_us=index * 100000 + 50000,
                    source_subtitle_uids=[subtitle_uid],
                    style_template_id="canonical_caption_template",
                )
            )
        graph = DraftIngest().build_source_graph(
            word_timeline=words,
            subtitles=subtitles,
            source_segments=[{"id": "clip", "material_id": "main_video", "source_start_us": 0, "source_end_us": 20000000}],
            text_materials=materials,
            text_segments=segments,
        )

        _material, _segment, report = CaptionMaterialWriter().template_detector.detect(graph, captions)

        self.assertEqual(report["candidate_count"], 110)
        self.assertEqual(report["fingerprint_group_count"], 1)
        self.assertEqual(report["selection_reason"], "single_safe_fingerprint_group")

    def test_real_style_difference_still_creates_ambiguous_groups(self) -> None:
        material_a = _round5_caption_material("caption_a")
        material_b = _round5_caption_material("caption_b")
        payload = json.loads(material_b["content"])
        payload["styles"][0]["font_size"] = 6.0
        material_b["font_size"] = 6.0
        material_b["content"] = json.dumps(payload, ensure_ascii=False)
        material_b["base_content"] = json.dumps(payload, ensure_ascii=False)
        graph = DraftIngest().build_source_graph(
            word_timeline=[
                {"word_id": "w1", "word_text": "甲", "start_us": 0, "end_us": 100000, "subtitle_uid": "s1", "subtitle_index": 1},
                {"word_id": "w2", "word_text": "乙", "start_us": 200000, "end_us": 300000, "subtitle_uid": "s2", "subtitle_index": 2},
            ],
            subtitles=[
                {"subtitle_uid": "s1", "subtitle_index": 1, "text": "甲", "word_ids": ["w1"], "text_material_id": "caption_a"},
                {"subtitle_uid": "s2", "subtitle_index": 2, "text": "乙", "word_ids": ["w2"], "text_material_id": "caption_b"},
            ],
            source_segments=[{"id": "clip", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000000}],
            text_materials=[material_a, material_b],
            text_segments=[_round5_caption_segment("caption_a"), _round5_caption_segment("caption_b")],
        )

        _material, _segment, report = CaptionMaterialWriter().template_detector.detect(graph, captions=[])

        self.assertEqual(report["fingerprint_group_count"], 2)
        self.assertEqual(report["blockers"][0]["code"], "CAPTION_TEMPLATE_AMBIGUOUS")


if __name__ == "__main__":
    unittest.main()
