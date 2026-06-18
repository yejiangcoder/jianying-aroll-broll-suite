from __future__ import annotations

import unittest

from aroll_v21.compiler import RoughCutQualityNormalizer
from aroll_v21.ir.models import DecisionPlan
from tests.test_aroll_v21_rough_cut_quality_normalizer import make_segment, make_source_graph, make_word


class ArollV21RoughCutHandlesTests(unittest.TestCase):
    def test_adjacent_segments_do_not_overlap_after_handle_expansion(self) -> None:
        words = [
            make_word("w1", "前句完整长一些", 300_000, 1_050_000, "s1", 1),
            make_word("w2", "后句完整长一些", 1_050_000, 1_800_000, "s2", 2),
        ]
        segments = [
            make_segment("seg1", "前句完整长一些", 300_000, 1_050_000, ["w1"]),
            make_segment("seg2", "后句完整长一些", 1_050_000, 1_800_000, ["w2"]),
        ]

        normalized, blockers = RoughCutQualityNormalizer().normalize(segments, make_source_graph(words), DecisionPlan(decisions=[]))

        self.assertEqual(blockers, [])
        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[0].clip_source_end_us, normalized[0].spoken_source_end_us)
        self.assertEqual(normalized[1].clip_source_start_us, normalized[1].spoken_source_start_us)
        self.assertGreater(normalized[0].lead_handle_us, 0)
        self.assertGreater(normalized[1].tail_handle_us, 0)


if __name__ == "__main__":
    unittest.main()
