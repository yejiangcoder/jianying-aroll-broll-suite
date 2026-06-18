from __future__ import annotations

import unittest

from aroll_v21.compiler import FinalTimelineCompiler
from aroll_v21.ir import DecisionPlan, FinalTimelineSegment


def _segment(
    segment_id: str,
    text: str,
    start_us: int,
    end_us: int,
    word_ids: list[str],
) -> FinalTimelineSegment:
    return FinalTimelineSegment(
        segment_id=segment_id,
        source_material_id="main",
        source_segment_id="clip",
        source_start_us=start_us,
        source_end_us=end_us,
        target_start_us=start_us,
        target_end_us=end_us,
        word_ids=word_ids,
        text=text,
        decision_ids=[],
    )


class ArollV21PreEmitSafeDropsWithOtherBlockersTests(unittest.TestCase):
    def test_safe_drops_still_apply_when_another_prefix_pair_is_unmappable(self) -> None:
        segments = [
            _segment("unsafe_left", "坏", 0, 100_000, []),
            _segment("unsafe_right", "坏掉", 100_000, 300_000, ["w_bad_right"]),
            _segment("safe_left", "重新上", 300_000, 500_000, ["w_safe_left"]),
            _segment("safe_right", "重新上桌", 500_000, 800_000, ["w_safe_right"]),
        ]
        plan = DecisionPlan(decisions=[])

        final_timeline, blockers = FinalTimelineCompiler()._pre_emit_boundary_prefix_normalization(segments, plan)

        self.assertEqual([segment.text for segment in final_timeline], ["坏", "坏掉", "重新上桌"])
        self.assertEqual([blocker.code for blocker in blockers], ["BOUNDARY_PREFIX_CONTAINMENT_REQUIRES_HUMAN_REVIEW"])
        self.assertEqual(final_timeline[0].target_start_us, 0)
        self.assertEqual(final_timeline[0].target_end_us, final_timeline[1].target_start_us)
        self.assertEqual(final_timeline[1].target_end_us, final_timeline[2].target_start_us)
        self.assertGreater(final_timeline[2].target_end_us, final_timeline[2].target_start_us)
        applied = [row for row in plan.decision_trace if row.get("stage") == "final_timeline_pre_emit"]
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["left_text"], "重新上")
        self.assertEqual(applied[0]["right_text"], "重新上桌")


if __name__ == "__main__":
    unittest.main()
