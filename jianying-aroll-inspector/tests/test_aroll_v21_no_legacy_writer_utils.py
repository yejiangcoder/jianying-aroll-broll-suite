from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRITER_SRC = ROOT / "src" / "aroll_v21" / "writer"


class ArollV21NoLegacyWriterUtilsTests(unittest.TestCase):
    def test_v21_writer_does_not_import_shared_edit_utils_or_material_text_rows(self) -> None:
        text = "\n".join(path.read_text("utf-8") for path in WRITER_SRC.rglob("*.py"))
        self.assertNotIn("aroll_shared_edit_utils", text)
        self.assertNotIn("clone_text_material", text)
        self.assertNotIn("material_text_rows", text)


if __name__ == "__main__":
    unittest.main()
