from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aroll_candidate_discovery import discover_aroll_candidates
from aroll_decision_plan_builder import apply_decision_plan_to_merged, build_aroll_decision_plan
from aroll_final_repeat_gate import build_final_repeat_gate_report
from aroll_repeat_fix_planner import build_final_repeat_fix_plan
from aroll_take_clusterer import build_take_clusters, take_clusters_to_repeat_detector_rows


class TakeClusterApplySmokeTest(unittest.TestCase):
    def test_take_cluster_approved_drop_is_added_to_merged_drops(self) -> None:
        subtitles = [
            {
                "subtitle_uid": "sub_000001",
                "subtitle_index": 1,
                "subtitle_text": "今天我们开始做第一步",
                "start_us": 1_000_000,
                "duration_us": 1_200_000,
                "end_us": 2_200_000,
            },
            {
                "subtitle_uid": "sub_000002",
                "subtitle_index": 2,
                "subtitle_text": "今天我们开始做第一步",
                "start_us": 2_400_000,
                "duration_us": 1_200_000,
                "end_us": 3_600_000,
            },
        ]

        clusters, cluster_report = build_take_clusters(subtitles, [])
        self.assertGreater(cluster_report["take_cluster_count"], 0)

        repeat_rows = take_clusters_to_repeat_detector_rows(clusters)
        candidates = discover_aroll_candidates(
            source_subtitles=subtitles,
            final_plan=[],
            repeat_clusters=repeat_rows,
            merged={"drop_decisions": [], "micro_cleanups": []},
        )
        take_candidate = next(row for row in candidates if (row.get("repeat_cluster") or {}).get("source") == "take_clusterer")

        arbiter_results = [
            {
                "candidate_id": take_candidate["candidate_id"],
                "classification": "duplicate_take_covered",
                "approved_action": "drop_left",
                "confidence": "high",
                "reason": "synthetic duplicate take keeps the later complete take",
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = build_aroll_decision_plan(candidates, arbiter_results, Path(temp_dir))

        self.assertEqual(plan["approved_drop_subtitle_indices"], [1])
        merged, report = apply_decision_plan_to_merged({"drop_decisions": [], "micro_cleanups": []}, plan)

        self.assertEqual(report["final_drop_count"], 1)
        self.assertEqual(report["added_decision_plan_drop_count"], 1)
        self.assertEqual(report["added_decision_plan_drop_indices"], [1])
        self.assertEqual(report["approved_drop_without_merged_effect_count"], 0)
        self.assertEqual(report["take_cluster_applied_drop_count"], 1)
        self.assertEqual(merged["drop_decisions"][0]["subtitle_index"], 1)
        self.assertEqual(merged["drop_decisions"][0]["source"], "decision_plan_take_cluster")

    def test_final_target_take_cluster_blocks_repeat_gate(self) -> None:
        report = build_final_repeat_gate_report(
            {"issues": []},
            [
                {"fragment_id": "f1", "fragment_text": "人家年少的时候", "target_start_us": 0, "target_duration_us": 1_000_000},
                {"fragment_id": "f2", "fragment_text": "人家年少的时候", "target_start_us": 1_100_000, "target_duration_us": 1_000_000},
            ],
        )
        self.assertFalse(report["final_repeat_gate_passed"])
        self.assertGreater(report["final_target_take_cluster_count"], 0)

    def test_final_audit_selected_side_mapping(self) -> None:
        audit = {
            "issues": [
                {
                    "issue_id": "rep_001",
                    "recommended_action": "drop_right",
                    "confidence": "high",
                    "deterministic_safe": False,
                    "requires_llm": True,
                    "involved_subtitle_ids": ["left_sub", "right_sub"],
                    "left_subtitle_ids": ["left_sub"],
                    "right_subtitle_ids": ["right_sub"],
                    "left_source_start_us": 10_000_000,
                    "left_source_end_us": 11_000_000,
                    "right_source_start_us": 12_000_000,
                    "right_source_end_us": 13_000_000,
                    "reason": "synthetic final audit side selection",
                }
            ]
        }
        llm_results = [
            {
                "candidate_id": "final_rep_001",
                "classification": "duplicate_take_covered",
                "approved_action": "drop_left",
                "confidence": "high",
            }
        ]

        plan = build_final_repeat_fix_plan(audit, {"tiny_artifact_issues": []}, llm_results)

        self.assertEqual(plan["summary"]["final_audit_llm_action_applied_count"], 1)
        self.assertEqual(plan["summary"]["final_audit_python_recommended_overridden_count"], 1)
        self.assertEqual(plan["summary"]["codex_self_review_count"], 0)
        self.assertEqual(len(plan["drop_segments"]), 1)
        drop = plan["drop_segments"][0]
        self.assertEqual(drop["drop_side"], "left")
        self.assertEqual(drop["selected_subtitle_ids"], ["left_sub"])
        self.assertEqual(drop["selected_source_start_us"], 10_000_000)
        self.assertEqual(drop["selected_source_end_us"], 11_000_000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
