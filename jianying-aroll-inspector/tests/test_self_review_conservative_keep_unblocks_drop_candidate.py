from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aroll_codex_self_review import build_self_review_report, collect_self_review_candidates
from aroll_decision_plan_builder import build_aroll_decision_plan


class SelfReviewConservativeKeepTest(unittest.TestCase):
    def test_self_review_unblocks_drop_candidate(self) -> None:
        candidates = [
            {
                "candidate_id": "cand_0001",
                "candidate_type": "drop_span",
                "source_subtitle_indices": [7],
                "source_subtitle_ranges": [{"subtitle_index": 7, "subtitle_uid": "sub_000007", "text": "半句", "start_us": 1000, "end_us": 2000}],
                "source_text": "半句",
                "source_start_us": 1000,
                "source_end_us": 2000,
                "proposed_action": "drop",
                "python_guess": "drop",
                "requires_llm": True,
            }
        ]
        arbiter_results = [
            {
                "candidate_id": "cand_0001",
                "classification": "codex_self_review_required",
                "approved_action": "self_review",
                "confidence": "low",
                "reason": "semantic ambiguity",
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = build_aroll_decision_plan(candidates, arbiter_results, Path(temp_dir))
        self.assertFalse(plan["blocked"])
        self.assertIn(7, plan["force_keep_subtitle_indices"])
        self.assertNotIn(7, plan["approved_drop_subtitle_indices"])
        self.assertEqual(plan["summary"]["decision_plan_conservative_keep_count"], 1)
        self.assertEqual(plan["summary"]["decision_plan_self_review_block_count"], 0)

        review = build_self_review_report(collect_self_review_candidates(decision_plan=plan))
        self.assertEqual(review["codex_self_review_unresolved_count"], 0)
        self.assertEqual(review["resolved_by_conservative_keep"], 1)

    def test_non_drop_self_review_still_blocks(self) -> None:
        candidates = [
            {
                "candidate_id": "cand_0002",
                "candidate_type": "semantic_required_unit",
                "source_subtitle_indices": [8],
                "source_text": "关键语义",
                "proposed_action": "manual_review",
                "python_guess": "keep",
                "requires_llm": True,
            }
        ]
        arbiter_results = [
            {
                "candidate_id": "cand_0002",
                "classification": "codex_self_review_required",
                "approved_action": "self_review",
                "confidence": "low",
                "reason": "not a deletion candidate",
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = build_aroll_decision_plan(candidates, arbiter_results, Path(temp_dir))
        self.assertTrue(plan["blocked"])
        self.assertEqual(plan["summary"]["decision_plan_conservative_keep_count"], 0)
        self.assertEqual(plan["summary"]["decision_plan_self_review_block_count"], 1)
        review = build_self_review_report(collect_self_review_candidates(decision_plan=plan))
        self.assertEqual(review["codex_self_review_unresolved_count"], 1)

    def test_lexical_reduplication_guard_keeps_phrase(self) -> None:
        candidates = [
            {
                "candidate_id": "cand_redup",
                "candidate_type": "micro_cleanup",
                "source_subtitle_indices": [49],
                "source_subtitle_ranges": [
                    {"subtitle_index": 49, "subtitle_uid": "sub_000049", "text": "姐妹底子好好", "start_us": 1000, "end_us": 2000}
                ],
                "source_text": "姐妹底子好好",
                "source_start_us": 1000,
                "source_end_us": 2000,
                "proposed_action": "micro_cleanup",
                "python_guess": "micro_cleanup",
                "proposed_final_text": "姐妹底子好",
                "requires_llm": True,
            }
        ]
        arbiter_results = [
            {
                "candidate_id": "cand_redup",
                "classification": "codex_self_review_required",
                "approved_action": "self_review",
                "confidence": "low",
                "reason": "口语强调不确定",
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = build_aroll_decision_plan(candidates, arbiter_results, Path(temp_dir))
        self.assertFalse(plan["blocked"])
        self.assertIn(49, plan["force_keep_subtitle_indices"])
        self.assertEqual(plan["summary"]["decision_plan_conservative_keep_count"], 1)
        self.assertEqual(plan["summary"]["decision_plan_self_review_block_count"], 0)
        self.assertEqual(plan["conservative_keep_items"][0]["guard"]["guard_type"], "lexical_reduplication_guard")

    def test_semantic_quantity_guard_keeps_quantity(self) -> None:
        candidates = [
            {
                "candidate_id": "cand_quantity",
                "candidate_type": "dirty_stutter",
                "source_subtitle_indices": [46],
                "source_subtitle_ranges": [
                    {"subtitle_index": 46, "subtitle_uid": "sub_000046", "text": "哪怕是一个200多斤的人", "start_us": 1000, "end_us": 2000}
                ],
                "source_text": "哪怕是一个200多斤的人",
                "source_start_us": 1000,
                "source_end_us": 2000,
                "proposed_action": "micro_cleanup",
                "python_guess": "same_subtitle_repeated_phrase",
                "repeat_cluster": {"micro_cleanup_text": "哪怕是一个20多斤的人"},
                "requires_llm": True,
            }
        ]
        arbiter_results = [
            {
                "candidate_id": "cand_quantity",
                "classification": "codex_self_review_required",
                "approved_action": "self_review",
                "confidence": "low",
                "reason": "数量短语不确定",
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = build_aroll_decision_plan(candidates, arbiter_results, Path(temp_dir))
        self.assertFalse(plan["blocked"])
        self.assertIn(46, plan["force_keep_subtitle_indices"])
        self.assertEqual(plan["summary"]["decision_plan_conservative_keep_count"], 1)
        self.assertEqual(plan["conservative_keep_items"][0]["guard"]["guard_type"], "semantic_quantity_guard")

    def test_suffix_prefix_overlap_merge_merges_without_losing_unique_prefix_suffix(self) -> None:
        candidates = [
            {
                "candidate_id": "cand_overlap",
                "candidate_type": "duplicate_take",
                "source_subtitle_indices": [12, 14],
                "source_subtitle_ranges": [
                    {"subtitle_index": 12, "subtitle_uid": "sub_000012", "text": "就我发现有这么一群精分", "start_us": 1000, "end_us": 2000},
                    {"subtitle_index": 14, "subtitle_uid": "sub_000014", "text": "一群精分的数字游民呐", "start_us": 2500, "end_us": 3500},
                ],
                "source_text": "就我发现有这么一群精分 一群精分的数字游民呐",
                "source_start_us": 1000,
                "source_end_us": 3500,
                "proposed_action": "self_review",
                "python_guess": "boundary_overlap_cleanup",
                "requires_llm": True,
            }
        ]
        arbiter_results = [
            {
                "candidate_id": "cand_overlap",
                "classification": "codex_self_review_required",
                "approved_action": "self_review",
                "confidence": "low",
                "reason": "边界重叠但不能删整句",
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = build_aroll_decision_plan(candidates, arbiter_results, Path(temp_dir))
        self.assertFalse(plan["blocked"])
        self.assertIn(12, plan["force_keep_subtitle_indices"])
        self.assertIn(14, plan["force_keep_subtitle_indices"])
        self.assertEqual(plan["summary"]["decision_plan_overlap_merge_count"], 1)
        self.assertEqual(plan["summary"]["decision_plan_self_review_block_count"], 0)
        merge = plan["overlap_merge_items"][0]["overlap_merge"]
        self.assertEqual(merge["overlap_text"], "一群精分")
        self.assertEqual(merge["merged_text"], "就我发现有这么一群精分的数字游民呐")

        review = build_self_review_report(collect_self_review_candidates(decision_plan=plan))
        self.assertEqual(review["codex_self_review_unresolved_count"], 0)
        self.assertEqual(review["resolved_by_overlap_merge"], 1)

    def test_semantic_overlap_self_review_conservative_keep_when_no_safe_merge(self) -> None:
        candidates = [
            {
                "candidate_id": "cand_semantic_overlap",
                "candidate_type": "semantic_overlap",
                "source_subtitle_indices": [30, 31],
                "source_subtitle_ranges": [
                    {"subtitle_index": 30, "subtitle_uid": "sub_000030", "text": "左边独立语义", "start_us": 1000, "end_us": 2000},
                    {"subtitle_index": 31, "subtitle_uid": "sub_000031", "text": "右边独立语义", "start_us": 2500, "end_us": 3500},
                ],
                "source_text": "左边独立语义 右边独立语义",
                "source_start_us": 1000,
                "source_end_us": 3500,
                "proposed_action": "remove_overlap",
                "python_guess": "semantic_overlap",
                "requires_llm": True,
            }
        ]
        arbiter_results = [
            {
                "candidate_id": "cand_semantic_overlap",
                "classification": "codex_self_review_required",
                "approved_action": "self_review",
                "confidence": "low",
                "reason": "语义重叠但无安全重叠字符",
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            plan = build_aroll_decision_plan(candidates, arbiter_results, Path(temp_dir))
        self.assertFalse(plan["blocked"])
        self.assertEqual(plan["summary"]["decision_plan_conservative_keep_count"], 1)
        self.assertEqual(plan["summary"]["decision_plan_overlap_merge_count"], 0)
        self.assertEqual(plan["summary"]["decision_plan_self_review_block_count"], 0)


if __name__ == "__main__":
    unittest.main()
