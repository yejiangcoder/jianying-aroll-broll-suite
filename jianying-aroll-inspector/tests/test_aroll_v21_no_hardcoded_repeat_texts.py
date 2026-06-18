from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ArollV21NoHardcodedRepeatTextsTests(unittest.TestCase):
    def test_src_aroll_v21_does_not_contain_manual_repeat_fixture_texts(self) -> None:
        forbidden = [
            "评论区也全是哇",
            "重新上",
            "恨不得给人家当牛做马",
            "人家年少的时候",
            "你说是死肌肉",
            "把那个敢于",
            "跟着老子",
            "把输掉的",
        ]
        hits = []
        for path in (ROOT / "src" / "aroll_v21").rglob("*.py"):
            text = path.read_text("utf-8")
            for item in forbidden:
                if item in text:
                    hits.append(f"{path.relative_to(ROOT)}:{item}")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
