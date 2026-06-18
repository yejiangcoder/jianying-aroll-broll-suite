from __future__ import annotations

import unittest

from aroll_v21.decision.final_target_repeat_resolver import FinalTargetRepeatResolver
from aroll_v21.ir import DecisionPlan, FinalTimelineSegment


def segment(index: int, text: str, *, start_us: int | None = None) -> FinalTimelineSegment:
    start = (index - 1) * 500_000 if start_us is None else start_us
    return FinalTimelineSegment(
        segment_id=f"v21_seg_{index:06d}",
        source_material_id="main",
        source_segment_id="clip",
        source_start_us=start,
        source_end_us=start + max(200_000, len(text) * 40_000),
        target_start_us=start,
        target_end_us=start + max(200_000, len(text) * 40_000),
        word_ids=[f"w_{index:06d}"],
        text=text,
        decision_ids=[],
    )


class ArollV21FinalTargetRepeatResolverTests(unittest.TestCase):
    def test_high_near_duplicate_take_drops_recommended_segment(self) -> None:
        plan = DecisionPlan(decisions=[])
        final_timeline, blockers = FinalTargetRepeatResolver().resolve(
            [segment(1, "恨不得给人家当牛做马"), segment(2, "中间句"), segment(3, "恨不得给人家当牛做马")],
            plan,
        )

        self.assertEqual(blockers, [])
        self.assertEqual([row.text for row in final_timeline], ["中间句", "恨不得给人家当牛做马"])
        self.assertEqual(final_timeline[0].target_start_us, 0)
        self.assertEqual(final_timeline[0].target_end_us, final_timeline[1].target_start_us)
        trace = [row for row in plan.decision_trace if row.get("route") == "final_target_repeat"]
        self.assertEqual(trace[0]["decision"], "auto_drop_high_confidence_exact_repeat")
        self.assertTrue(trace[0]["applied"])

    def test_medium_semantic_containment_emits_request_without_auto_drop(self) -> None:
        plan = DecisionPlan(decisions=[])
        final_timeline, blockers = FinalTargetRepeatResolver().resolve(
            [segment(1, "自信的人能拿到结果"), segment(2, "自信的人真的能拿到结果")],
            plan,
        )

        self.assertEqual(blockers, [])
        self.assertEqual([row.text for row in final_timeline], ["自信的人能拿到结果", "自信的人真的能拿到结果"])
        self.assertEqual(plan.semantic_unresolved_count, 1)
        self.assertFalse(plan.write_allowed)
        self.assertEqual(plan.semantic_request_payloads[0]["type"], "final_target_repeat")
        self.assertEqual(plan.semantic_request_payloads[0]["cluster_type"], "semantic_containment_take")
        forbidden = {
            "source_start_us",
            "source_end_us",
            "target_start_us",
            "target_end_us",
            "edl",
            "final_edl",
            "draft_content",
            "material_id",
            "segment_id",
        }
        self.assertFalse(forbidden & set(plan.semantic_request_payloads[0]))


if __name__ == "__main__":
    unittest.main()
