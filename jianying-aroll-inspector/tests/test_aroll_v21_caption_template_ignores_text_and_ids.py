from __future__ import annotations

import json
import unittest

from aroll_v21.writer.caption_material_writer import caption_template_fingerprint
from tests.test_aroll_v21_caption_template_round5_position_y_minus_073 import (
    _round5_caption_material,
    _round5_caption_segment,
)


class ArollV21CaptionTemplateIgnoresTextAndIdsTests(unittest.TestCase):
    def test_fingerprint_ignores_ids_text_and_content_ranges(self) -> None:
        material_a = _round5_caption_material("caption_a")
        material_b = _round5_caption_material("caption_b")
        segment_a = _round5_caption_segment("caption_a")
        segment_b = _round5_caption_segment("caption_b")
        payload = json.loads(material_b["content"])
        payload["text"] = "完全不同的字幕文本"
        payload["styles"][0]["range"]["end"] = len(payload["text"])
        material_b["content"] = json.dumps(payload, ensure_ascii=False)
        material_b["base_content"] = json.dumps(payload, ensure_ascii=False)
        material_b["recognize_text"] = payload["text"]
        segment_b["id"] = "different_segment_id"
        segment_b["material_id"] = material_b["id"]

        fingerprint_a, material_fp_a, segment_fp_a = caption_template_fingerprint(material_a, segment_a)
        fingerprint_b, material_fp_b, segment_fp_b = caption_template_fingerprint(material_b, segment_b)

        self.assertEqual(fingerprint_a, fingerprint_b)
        self.assertEqual(material_fp_a, material_fp_b)
        self.assertEqual(segment_fp_a, segment_fp_b)


if __name__ == "__main__":
    unittest.main()
