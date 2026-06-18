from __future__ import annotations

import json
import unittest

from aroll_v21.ingest import DraftIngest
from aroll_v21.ir import CaptionRenderUnit
from aroll_v21.writer import CaptionMaterialWriter


def _round5_caption_material(material_id: str = "round5_text_001") -> dict:
    content = {
        "text": "底部字幕",
        "styles": [
            {
                "range": {"start": 0, "end": 4},
                "font_size": 5.0,
                "fill": {"color": "#FFFFFF"},
                "stroke": {"color": "#000000", "width": 0.3},
            }
        ],
    }
    return {
        "id": material_id,
        "role": "title",
        "type": "text",
        "font_size": 5.0,
        "initial_scale": 1.0,
        "scale": 1.0,
        "content": json.dumps(content, ensure_ascii=False),
        "base_content": json.dumps(content, ensure_ascii=False),
    }


def _round5_caption_segment(material_id: str = "round5_text_001") -> dict:
    return {
        "id": f"{material_id}_seg",
        "type": "title",
        "material_id": material_id,
        "clip": {"transform": {"x": 0.0, "y": -0.73}, "scale": 1.0},
        "target_timerange": {"start": 0, "duration": 1000000},
    }


def _caption(uid: str = "s001") -> CaptionRenderUnit:
    return CaptionRenderUnit(
        caption_id="cap_001",
        timeline_segment_ids=["timeline_001"],
        word_ids=["w001"],
        text="底部字幕",
        target_start_us=0,
        target_end_us=1000000,
        source_subtitle_uids=[uid],
        style_template_id="canonical_caption_template",
    )


class ArollV21CaptionTemplateRound5PositionTests(unittest.TestCase):
    def test_round5_y_minus_073_subtitle_bound_material_is_candidate(self) -> None:
        material = _round5_caption_material()
        segment = _round5_caption_segment()
        graph = DraftIngest().build_source_graph(
            word_timeline=[
                {"word_id": "w001", "word_text": "底部", "start_us": 0, "end_us": 100000, "subtitle_uid": "s001", "subtitle_index": 1}
            ],
            subtitles=[{"subtitle_uid": "s001", "subtitle_index": 1, "text": "底部字幕", "word_ids": ["w001"], "text_material_id": material["id"]}],
            source_segments=[{"id": "clip", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1000000}],
            text_materials=[material],
            text_segments=[segment],
        )

        plan, blockers = CaptionMaterialWriter().build_write_plan(graph, [_caption()])

        self.assertEqual(blockers, [])
        report = plan["template_report"]
        self.assertEqual(report["candidate_count"], 1)
        self.assertEqual(report["fingerprint_group_count"], 1)
        self.assertEqual(report["rejection_summary"]["title_like"], 0)
        self.assertEqual(report["title_like_reasons"]["position_center_title_like"], 0)
        self.assertEqual(report["title_like_reasons"]["bottom_subtitle_position"], 1)
        self.assertEqual(report["title_like_reasons"]["subtitle_bound_position_risk_downgraded"], 1)
        self.assertEqual(plan["writer_fallback_count"], 0)


if __name__ == "__main__":
    unittest.main()
