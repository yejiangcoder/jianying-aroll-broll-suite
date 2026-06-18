from __future__ import annotations

import json
import unittest

from aroll_v21.writer.caption_material_writer import caption_template_fingerprint
from tests.test_aroll_v21_caption_template_round7_fingerprint_sample import _round7_material, _round7_segment


class ArollV21CaptionTemplateIgnoresVolatileTextFieldsTests(unittest.TestCase):
    def test_content_base_content_words_current_words_keyword_ranges_and_ranges_are_volatile(self) -> None:
        material_a = _round7_material("material_a", "短字幕", keyword=True)
        material_b = _round7_material("material_b", "更长的一条字幕文本", keyword=True)
        segment_a = _round7_segment("material_a", 1)
        segment_b = _round7_segment("material_b", 2)

        content_b = json.loads(material_b["content"])
        content_b["styles"][0]["range"] = [0, 1]
        content_b["styles"].append({**content_b["styles"][0], "range": [1, len(content_b["text"])]})
        material_b["content"] = json.dumps(content_b, ensure_ascii=False)
        base_content_b = json.loads(material_b["base_content"])
        base_content_b["text"] = "完全不同的文本"
        base_content_b["styles"][0]["range"] = [0, len(base_content_b["text"])]
        material_b["base_content"] = json.dumps(base_content_b, ensure_ascii=False)
        material_b["words"] = {"start_time": [0, 80, 200], "end_time": [80, 200, 360], "text": ["更", "长", "文本"]}
        material_b["current_words"] = {}
        material_b["subtitle_keywords"] = {"range": [{"location": 1, "length": 7, "source_type": "server"}]}

        self.assertEqual(caption_template_fingerprint(material_a, segment_a), caption_template_fingerprint(material_b, segment_b))


if __name__ == "__main__":
    unittest.main()
