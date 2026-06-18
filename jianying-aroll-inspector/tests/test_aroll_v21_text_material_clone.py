from __future__ import annotations

import json
import unittest

from aroll_v21.writer.text_material_clone import clone_caption_text_material


class ArollV21TextMaterialCloneTests(unittest.TestCase):
    def test_content_json_remains_json_and_styles_are_preserved(self) -> None:
        content = json.dumps(
            {"text": "旧字幕", "styles": [{"range": {"start": 0, "end": 3}, "font_size": 42}]},
            ensure_ascii=False,
        )
        material = {
            "id": "caption_template",
            "text": "旧字幕",
            "recognize_text": "旧字幕",
            "content": content,
            "base_content": content,
        }
        cloned = clone_caption_text_material(material, "caption_out", "新字幕文本")
        self.assertEqual(cloned["id"], "caption_out")
        self.assertEqual(cloned["text"], "新字幕文本")
        self.assertEqual(cloned["recognize_text"], "新字幕文本")
        content_payload = json.loads(cloned["content"])
        base_payload = json.loads(cloned["base_content"])
        self.assertEqual(content_payload["text"], "新字幕文本")
        self.assertEqual(base_payload["text"], "新字幕文本")
        self.assertEqual(content_payload["styles"][0]["font_size"], 42)
        self.assertEqual(content_payload["styles"][0]["range"]["end"], len("新字幕文本"))
        self.assertEqual(base_payload["styles"], content_payload["styles"])


if __name__ == "__main__":
    unittest.main()
