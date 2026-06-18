from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aroll_v21 import ArollEngine
from aroll_v21.decision import SemanticAdjudicationDecisionType, SemanticDecisionPlanner
from aroll_v21.decision.final_target_repeat_resolver import FinalTargetRepeatResolver
from aroll_v21.engine import AUTO_PROVIDER_ROUTING_SKIPPED_CODE, FINAL_TARGET_PROVIDER_FAILURE_CODE
from aroll_v21.ir import DecisionPlan
from aroll_v21.operator import ArollV21OperatorConfig, run_operator
from tests.test_aroll_v21_semantic_adjudication_layer import (
    FailingSemanticProvider,
    FakeSemanticProvider,
    _two_caption_input,
    _write_input,
)
from tests.test_aroll_v21_semantic_planner_contract import _semantic_cluster


def _final_target_input():
    return _two_caption_input("红花开满山", "蓝月升过桥")


def _final_target_clusters(_resolver, segments):  # type: ignore[no-untyped-def]
    if len(segments) < 2:
        return []
    return [
        {
            "cluster_id": "tc_0001",
            "cluster_type": "semantic_containment_take",
            "confidence": "medium",
            "severity": "medium",
            "requires_llm": True,
            "recommended_drop_index": None,
            "items": [
                {
                    "subtitle_index": 1,
                    "subtitle_uid": segments[0].segment_id,
                    "text": segments[0].text,
                },
                {
                    "subtitle_index": 2,
                    "subtitle_uid": segments[1].segment_id,
                    "text": segments[1].text,
                },
            ],
        }
    ]


def _final_target_payload() -> dict:
    return {
        "cluster_id": "final_target_repeat_tc_0001",
        "issue_id": "final_target_repeat_tc_0001",
        "type": "final_target_repeat",
        "issue_type": "semantic_containment",
        "cluster_type": "semantic_containment_take",
        "severity": "medium",
        "provider_required": True,
        "requires_llm": True,
        "left_text": "红花开满山",
        "right_text": "蓝月升过桥",
        "candidates": [
            {"role": "left", "text": "红花开满山", "subtitle_index": 1, "candidate_id": "v21_seg_000001"},
            {"role": "right", "text": "蓝月升过桥", "subtitle_index": 2, "candidate_id": "v21_seg_000002"},
        ],
        "allowed_decisions": ["keep_all", "drop_left", "drop_right", "requires_human_review"],
    }


class RaisingSemanticProvider:
    provider_name = "raising_deepseek"

    def __init__(self) -> None:
        self.requests = []

    def decide(self, requests):  # type: ignore[no-untyped-def]
        self.requests.extend(requests)
        raise ValueError("provider json malformed")


class ArollV21FinalTargetRepeatAutoProviderTests(unittest.TestCase):
    def test_auto_mode_routes_final_target_repeat_requests_to_provider(self) -> None:
        provider = FakeSemanticProvider(SemanticAdjudicationDecisionType.DROP_RIGHT)

        with patch.object(FinalTargetRepeatResolver, "_clusters", _final_target_clusters):
            report = ArollEngine(semantic_mode="auto", semantic_provider=provider).run(_final_target_input())

        semantic_report = report.decision_plan.semantic_adjudication_report
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(provider.requests[0].issue_id, "final_target_repeat_tc_0001")
        self.assertEqual(provider.requests[0].issue_type.value, "semantic_containment")
        self.assertEqual(semantic_report["semantic_provider_required_count"], 1)
        self.assertEqual(semantic_report["deepseek_provider_called_count"], 1)

    def test_provider_configured_but_required_request_not_called_is_blocker(self) -> None:
        plan = DecisionPlan(
            decisions=[],
            semantic_request_payloads=[_final_target_payload()],
            semantic_adjudication_report={
                "semantic_mode": "auto",
                "deepseek_provider_configured": True,
                "deepseek_provider_called_count": 0,
                "semantic_provider_required_count": 1,
                "routing_decisions": [
                    {
                        "issue_id": "final_target_repeat_tc_0001",
                        "requires_provider": True,
                    }
                ],
            },
        )

        ArollEngine()._refresh_semantic_adjudication_report(plan)

        self.assertIn(AUTO_PROVIDER_ROUTING_SKIPPED_CODE, [blocker.code for blocker in plan.blockers])
        self.assertIn(AUTO_PROVIDER_ROUTING_SKIPPED_CODE, plan.semantic_adjudication_report["blocker_codes"])
        self.assertFalse(plan.semantic_adjudication_report["semantic_adjudication_gate_passed"])

    def test_final_target_repeat_provider_decision_resolves_unresolved_request(self) -> None:
        provider = FakeSemanticProvider(SemanticAdjudicationDecisionType.DROP_RIGHT)

        with patch.object(FinalTargetRepeatResolver, "_clusters", _final_target_clusters):
            report = ArollEngine(semantic_mode="auto", semantic_provider=provider).run(_final_target_input())

        self.assertEqual([segment.text for segment in report.final_timeline], ["红花开满山"])
        self.assertEqual(report.decision_plan.semantic_request_payloads, [])
        self.assertEqual(report.decision_plan.final_target_repeat_unresolved_cluster_ids, [])
        self.assertEqual(report.decision_plan.semantic_adjudication_report["semantic_request_unresolved_count"], 0)
        self.assertTrue(
            any(
                row.get("route") == "final_target_repeat"
                and row.get("cluster_id") == "final_target_repeat_tc_0001"
                and row.get("decision") == "drop_right"
                and row.get("applied")
                for row in report.decision_trace
            )
        )

    def test_final_target_repeat_provider_can_return_keep_longest_drop_others(self) -> None:
        provider = FakeSemanticProvider(SemanticAdjudicationDecisionType.KEEP_LONGEST_DROP_OTHERS)

        with patch.object(FinalTargetRepeatResolver, "_clusters", _final_target_clusters):
            report = ArollEngine(semantic_mode="auto", semantic_provider=provider).run(_final_target_input())

        self.assertEqual([segment.text for segment in report.final_timeline], ["红花开满山"])
        self.assertEqual(report.decision_plan.semantic_request_payloads, [])
        self.assertEqual(report.decision_plan.semantic_adjudication_report["semantic_request_unresolved_count"], 0)
        self.assertTrue(
            any(
                row.get("route") == "final_target_repeat"
                and row.get("cluster_id") == "final_target_repeat_tc_0001"
                and row.get("decision") == "keep_longest_drop_others"
                and row.get("applied")
                for row in report.decision_trace
            )
        )

    def test_final_target_repeat_provider_error_reports_called_count(self) -> None:
        provider = RaisingSemanticProvider()

        with patch.object(FinalTargetRepeatResolver, "_clusters", _final_target_clusters):
            report = ArollEngine(semantic_mode="auto", semantic_provider=provider).run(_final_target_input())

        semantic_report = report.decision_plan.semantic_adjudication_report
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(semantic_report["deepseek_provider_called_count"], 1)
        self.assertIn("provider json malformed", semantic_report["deepseek_provider_error"])
        self.assertEqual(semantic_report["semantic_request_unresolved_count"], 1)
        self.assertIn(FINAL_TARGET_PROVIDER_FAILURE_CODE, [blocker.code for blocker in report.blocker_report.blockers])
        self.assertNotIn(AUTO_PROVIDER_ROUTING_SKIPPED_CODE, [blocker.code for blocker in report.blocker_report.blockers])

    def test_source_semantic_provider_error_reports_called_count(self) -> None:
        provider = RaisingSemanticProvider()

        plan = SemanticDecisionPlanner(semantic_mode="auto", semantic_provider=provider).plan([_semantic_cluster()])

        semantic_report = plan.semantic_adjudication_report
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(semantic_report["deepseek_provider_called_count"], 1)
        self.assertIn("provider json malformed", semantic_report["deepseek_provider_error"])
        self.assertEqual(plan.semantic_unresolved_count, 1)
        self.assertEqual(semantic_report["semantic_request_unresolved_count"], 1)
        self.assertIn(FINAL_TARGET_PROVIDER_FAILURE_CODE, [blocker.code for blocker in plan.blockers])

    def test_commit_reuses_final_target_repeat_semantic_cache(self) -> None:
        provider = FakeSemanticProvider(SemanticAdjudicationDecisionType.DROP_RIGHT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_json = root / "input.json"
            run_dir = root / "run"
            _write_input(input_json, _final_target_input())

            with patch.object(FinalTargetRepeatResolver, "_clusters", _final_target_clusters):
                with patch("aroll_v21.operator.deepseek_provider_from_env", return_value=provider):
                    dry_summary = run_operator(
                        ArollV21OperatorConfig(
                            mode="dry-run",
                            run_dir=run_dir,
                            input_json=input_json,
                            semantic_mode="auto",
                        )
                    )
                with patch("aroll_v21.operator.deepseek_provider_from_env", return_value=FailingSemanticProvider()):
                    write_summary = run_operator(
                        ArollV21OperatorConfig(
                            mode="write",
                            run_dir=run_dir,
                            input_json=input_json,
                            semantic_mode="auto",
                        )
                    )

            payloads = json.loads((run_dir / "semantic_request_payloads.json").read_text("utf-8"))
            report = json.loads((run_dir / "semantic_adjudication_report.json").read_text("utf-8"))
            resolved = json.loads((run_dir / "semantic_decisions.resolved.json").read_text("utf-8"))
            cache = json.loads((run_dir / "semantic_decision_cache.json").read_text("utf-8"))

        self.assertEqual(dry_summary["deepseek_provider_called_count"], 1)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(payloads, [])
        self.assertEqual(report["semantic_request_unresolved_count"], 0)
        self.assertEqual(cache, resolved)
        self.assertEqual(cache[0]["cluster_id"], "final_target_repeat_tc_0001")
        self.assertEqual(write_summary["deepseek_provider_called_count"], 0)
        self.assertTrue(write_summary["semantic_decision_cache_used"])


if __name__ == "__main__":
    unittest.main()
