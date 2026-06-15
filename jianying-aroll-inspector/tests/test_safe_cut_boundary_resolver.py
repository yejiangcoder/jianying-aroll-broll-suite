from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aroll_safe_cut_boundary_gate import audit_safe_cut_boundaries
from aroll_safe_cut_boundary_resolver import resolve_safe_cut_boundaries


class SafeCutBoundaryResolverTest(unittest.TestCase):
    def test_resolver_snaps_inside_word_boundary(self) -> None:
        words = [{"word_id": "w1", "word_text": "A", "start_us": 100_000, "end_us": 300_000}]
        edl = [{"clip_id": "c1", "source_start_us": 180_000, "source_end_us": 500_000, "target_start_us": 0, "target_duration_us": 320_000}]
        before = audit_safe_cut_boundaries(words, final_edl=edl)
        self.assertGreater(before["cut_inside_word_count"], 0)
        with tempfile.TemporaryDirectory() as td:
            repaired, report = resolve_safe_cut_boundaries(final_edl=edl, word_timeline=words, output_path=Path(td) / "safe.json")
        after = audit_safe_cut_boundaries(words, final_edl=repaired)
        self.assertTrue(report["safe_cut_boundary_resolver_passed"])
        self.assertEqual(after["cut_inside_word_count"], 0)


if __name__ == "__main__":
    unittest.main()

