from __future__ import annotations

from copy import deepcopy
import unittest

from aroll_final_repeat_gate import build_final_repeat_gate_report
from aroll_v21.decision.deterministic_baseline_policy import DeterministicBaselinePolicy
from aroll_v21.decision.final_target_repeat_resolver import FINAL_TARGET_REPEAT_DECISIONS, FinalTargetRepeatResolver
from aroll_v21.ir import DecisionPlan, FinalTimelineSegment
from aroll_v21.validate.validators import ReadOnlyValidators


def _baseline_plan() -> DecisionPlan:
    return DecisionPlan(decisions=[], semantic_decision_rows=[{"_semantic_mode": "deterministic_baseline"}])


def _segment(index: int, text: str) -> FinalTimelineSegment:
    start = (index - 1) * 500_000
    return FinalTimelineSegment(
        segment_id=f"v21_seg_{index:06d}",
        source_material_id="main",
        source_segment_id=None,
        source_start_us=start,
        source_end_us=start + 500_000,
        target_start_us=start,
        target_end_us=start + 500_000,
        word_ids=[f"w_{index:06d}"],
        text=text,
        decision_ids=[],
    )


def _high_near_duplicate_candidate() -> dict:
    return {
        "cluster_id": "tc_0001",
        "cluster_type": "near_duplicate_take",
        "confidence": "high",
        "recommended_drop_index": 1,
        "requires_llm": False,
        "pairwise_evidence": [{"similarity": 0.9474}],
    }


def _caption_rows(texts: list[str]) -> list[dict]:
    rows = []
    cursor = 0
    for index, text in enumerate(texts, start=1):
        rows.append(
            {
                "fragment_id": f"cap_{index:06d}",
                "fragment_text": text,
                "text": text,
                "target_start_us": cursor,
                "target_duration_us": 500_000,
                "word_ids": [f"w_{index:06d}"],
            }
        )
        cursor += 500_000
    return rows


class ArollV21DeterministicBaselinePolicyTests(unittest.TestCase):
    def test_policy_enabled_from_decision_plan(self) -> None:
        self.assertTrue(DeterministicBaselinePolicy().is_enabled(_baseline_plan()))
        self.assertFalse(DeterministicBaselinePolicy().is_enabled(DecisionPlan(decisions=[])))

    def test_policy_keep_all_for_low_risk_missing_cluster(self) -> None:
        row = DeterministicBaselinePolicy().decision_for_missing_cluster("repeat_2000", "semantic_retry")

        self.assertIsNotNone(row)
        self.assertEqual(row["decision"], "keep_all")
        self.assertEqual(row["v21_resolution"], "accepted_by_deterministic_baseline")
        self.assertEqual(row["decision_source"], "deterministic_baseline")
        self.assertFalse(row["requires_human_review"])

    def test_deterministic_baseline_cannot_keep_all_fatal_modifier_redundancy(self) -> None:
        row = DeterministicBaselinePolicy().decision_for_missing_cluster("repeat_2000", "modifier_redundancy")

        self.assertIsNone(row)

    def test_policy_drops_high_near_duplicate_take_recommended_index(self) -> None:
        row = DeterministicBaselinePolicy().decision_for_final_repeat_candidate(_high_near_duplicate_candidate())

        self.assertIsNotNone(row)
        self.assertEqual(row["decision"], "drop_recommended")
        self.assertEqual(row["drop_index"], 1)
        self.assertEqual(row["v21_resolution"], "accepted_by_deterministic_baseline_drop_recommended")
        self.assertEqual(row["decision_source"], "deterministic_baseline")
        self.assertEqual(row["semantic_mode"], "deterministic_baseline")
        self.assertFalse(row["requires_human_review"])

    def test_policy_never_keep_all_high_near_duplicate_take(self) -> None:
        row = DeterministicBaselinePolicy().decision_for_final_repeat_candidate(_high_near_duplicate_candidate())

        self.assertNotEqual(row["decision"], "keep_all")
        self.assertNotEqual(row["v21_resolution"], "accepted_by_deterministic_baseline")

    def test_drop_recommended_is_valid_final_repeat_decision(self) -> None:
        self.assertIn("drop_recommended", FINAL_TARGET_REPEAT_DECISIONS)

        row = {"decision": "drop_recommended", "drop_index": 2}
        indices = FinalTargetRepeatResolver()._drop_indices_for_decision({"recommended_drop_index": 1}, "drop_recommended", row)

        self.assertEqual(indices, [2])

    def test_baseline_policy_resolver_contract_closed_for_keep_all_or_none(self) -> None:
        row = DeterministicBaselinePolicy().decision_for_final_repeat_candidate(
            {
                "cluster_id": "tc_0002",
                "cluster_type": "near_duplicate_take",
                "confidence": "medium",
                "recommended_drop_index": 1,
                "pairwise_evidence": [{"similarity": 0.9474}],
            }
        )

        self.assertIsNone(row)

    def test_final_target_repeat_resolver_uses_policy_for_high_near_duplicate(self) -> None:
        plan = _baseline_plan()
        final_timeline, blockers = FinalTargetRepeatResolver().resolve(
            [
                _segment(1, "恨不得给人家当牛做马"),
                _segment(2, "中间句"),
                _segment(3, "恨不得给人家当牛马"),
            ],
            plan,
        )

        self.assertEqual(blockers, [])
        self.assertEqual([segment.text for segment in final_timeline], ["中间句", "恨不得给人家当牛马"])
        trace = [row for row in plan.decision_trace if row.get("route") == "final_target_repeat"]
        self.assertEqual(trace[0]["decision"], "drop_recommended")
        self.assertEqual(trace[0]["decision_source"], "deterministic_baseline")
        self.assertEqual(trace[0]["v21_resolution"], "accepted_by_deterministic_baseline_drop_recommended")
        self.assertEqual(trace[0]["drop_index"], 1)

    def test_final_target_semantic_containment_baseline_does_not_keep_all(self) -> None:
        plan = _baseline_plan()
        final_timeline, blockers = FinalTargetRepeatResolver().resolve(
            [_segment(1, "自信的人能拿到结果"), _segment(2, "自信的人真的能拿到结果")],
            plan,
        )

        self.assertEqual(blockers, [])
        self.assertEqual([segment.text for segment in final_timeline], ["自信的人能拿到结果", "自信的人真的能拿到结果"])
        self.assertEqual(plan.semantic_unresolved_count, 1)
        self.assertFalse(plan.write_allowed)
        self.assertEqual(plan.final_target_repeat_accepted_cluster_ids, [])
        self.assertEqual(plan.semantic_request_payloads[0]["cluster_type"], "semantic_containment_take")
        self.assertFalse(any(row.get("decision") == "keep_all" for row in plan.decision_trace))

    def test_validator_does_not_mutate_final_repeat_candidates(self) -> None:
        report = build_final_repeat_gate_report(
            {"issues": []},
            _caption_rows(["恨不得给人家当牛做马", "中间句", "恨不得给人家当牛马"]),
        )
        before = deepcopy(report)

        ReadOnlyValidators()._final_repeat_semantic_status(report, _baseline_plan())

        self.assertEqual(report, before)

    def test_validator_does_not_create_deterministic_baseline_decisions(self) -> None:
        report = build_final_repeat_gate_report(
            {"issues": []},
            _caption_rows(["恨不得给人家当牛做马", "中间句", "恨不得给人家当牛马"]),
        )

        updated = ReadOnlyValidators()._final_repeat_semantic_status(report, _baseline_plan())

        candidate = updated["final_target_repeat_candidates"][0]
        self.assertNotIn("decision", candidate)
        self.assertNotIn("decision_source", candidate)
        self.assertNotIn("semantic_mode", candidate)
        self.assertNotEqual(candidate.get("v21_resolution"), "accepted_by_deterministic_baseline")


if __name__ == "__main__":
    unittest.main()
