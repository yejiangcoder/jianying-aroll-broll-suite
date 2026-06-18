from __future__ import annotations

import unittest

from aroll_v21.engine import build_run_summary
from aroll_v21.ir import Blocker, BlockerReport, DecisionPlan, RunReport


def _run_report_with_blockers(
    blockers: list[Blocker],
    *,
    semantic_unresolved_count: int = 0,
    validator_ok: bool = True,
    semantic_report: dict | None = None,
) -> RunReport:
    return RunReport(
        status="blocked" if blockers or not validator_ok else "ok",
        source_graph=None,
        repeat_clusters=[],
        decision_plan=DecisionPlan(
            decisions=[],
            semantic_adjudication_report=dict(semantic_report or {}),
            semantic_unresolved_count=semantic_unresolved_count,
            write_allowed=semantic_unresolved_count == 0,
            requires_human_review=semantic_unresolved_count > 0,
        ),
        final_timeline=[],
        captions=[],
        material_write_plan={"writer_fallback_count": 0, "no_writer_fallback": True},
        validator_report={"validator_report_ok": validator_ok, "validators_read_only": True},
        postwrite_report={},
        blocker_report=BlockerReport(blocked=bool(blockers), blockers=blockers, summary={"mode": "dry-run"}),
    )


class ArollV21RunSummarySemanticUnresolvedCountTests(unittest.TestCase):
    def test_non_semantic_write_blocker_does_not_increment_semantic_unresolved_count(self) -> None:
        report = _run_report_with_blockers(
            [
                Blocker(
                    code="BOUNDARY_PREFIX_CONTAINMENT_REQUIRES_HUMAN_REVIEW",
                    message="non semantic compiler write blocker",
                    layer="compiler",
                    severity="write_blocker",
                )
            ],
            semantic_unresolved_count=0,
        )

        summary = build_run_summary(report)

        self.assertEqual(summary["semantic_unresolved_count"], 0)
        self.assertEqual(summary["semantic_review_blocker_count"], 0)
        self.assertEqual(summary["write_blocker_count"], 1)
        self.assertFalse(summary["write_allowed"])
        self.assertFalse(summary["READY_FOR_DISPOSABLE_WRITE_PRE_AUDIT"])

    def test_validator_fatal_keeps_write_allowed_false_even_when_semantic_clear(self) -> None:
        report = _run_report_with_blockers([], semantic_unresolved_count=0, validator_ok=False)

        summary = build_run_summary(report)

        self.assertEqual(summary["semantic_unresolved_count"], 0)
        self.assertTrue(summary["semantic_write_allowed"])
        self.assertFalse(summary["validator_write_allowed"])
        self.assertFalse(summary["write_allowed"])

    def test_auto_summary_explains_deepseek_not_called_when_no_provider_required(self) -> None:
        report = _run_report_with_blockers(
            [],
            semantic_report={
                "semantic_mode": "auto",
                "semantic_request_count": 0,
                "semantic_request_unresolved_count": 0,
                "semantic_provider_required_count": 0,
                "deepseek_provider_configured": False,
                "deepseek_provider_called_count": 0,
            },
        )

        summary = build_run_summary(report)

        self.assertEqual(summary["semantic_mode"], "auto")
        self.assertEqual(summary["deepseek_provider_called_count"], 0)
        self.assertEqual(summary["deepseek_provider_not_called_reason"], "no_provider_required")

    def test_semantic_requests_only_summary_explains_deepseek_not_called(self) -> None:
        report = _run_report_with_blockers(
            [],
            semantic_report={
                "semantic_mode": "semantic-requests-only",
                "semantic_request_count": 0,
                "semantic_request_unresolved_count": 0,
                "deepseek_provider_configured": False,
                "deepseek_provider_called_count": 0,
            },
        )

        summary = build_run_summary(report)

        self.assertEqual(summary["semantic_mode"], "semantic-requests-only")
        self.assertEqual(summary["deepseek_provider_called_count"], 0)
        self.assertEqual(summary["deepseek_provider_not_called_reason"], "semantic_mode=semantic-requests-only")

    def test_deepseek_summary_explains_missing_provider(self) -> None:
        report = _run_report_with_blockers(
            [],
            semantic_report={
                "semantic_mode": "deepseek",
                "semantic_request_count": 1,
                "semantic_request_unresolved_count": 1,
                "deepseek_provider_configured": False,
                "deepseek_provider_called_count": 0,
            },
            semantic_unresolved_count=1,
        )

        summary = build_run_summary(report)

        self.assertEqual(summary["semantic_mode"], "deepseek")
        self.assertEqual(summary["deepseek_provider_not_called_reason"], "deepseek_provider_not_configured")


if __name__ == "__main__":
    unittest.main()
