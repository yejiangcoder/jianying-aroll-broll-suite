from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from aroll_v21.decision.semantic_adjudication import normalize_semantic_mode
from aroll_v21.decision.semantic_contracts import SemanticAdjudicationMode
from aroll_v21.ir.models import BlockerReport, RunReport
from aroll_v21.operator_config import ArollV21OperatorConfig
from aroll_v21.writeback import WritebackResult


def _postwrite_environment(config: ArollV21OperatorConfig) -> dict[str, Any]:
    draft_content_path = ""
    if config.draft_dir is not None:
        draft_content_path = str(Path(config.draft_dir) / "draft_content.json")
    return {
        "draft_dir": str(config.draft_dir or ""),
        "jy_draftc_path": str(config.jy_draftc or ""),
        "jy_install_dir": str(os.environ.get("JY_INSTALL_DIR") or ""),
        "postwrite_decrypt_cwd": str(Path.cwd()),
        "draft_content_path": draft_content_path,
        "only_specified_draft_written": bool(config.draft_dir is not None),
    }


def _annotate_postwrite_environment(
    report: RunReport,
    config: ArollV21OperatorConfig,
    *,
    sacrificial_override_used: bool = False,
    writeback_report: dict[str, Any] | None = None,
) -> None:
    evidence = _postwrite_environment(config)
    postwrite = report.postwrite_report
    postwrite.update(evidence)
    if writeback_report:
        postwrite.update(writeback_report)
        postwrite.update(
            {
                "writeback_success": bool(writeback_report.get("writeback_success")),
                "WRITE_SUCCESS": bool(writeback_report.get("WRITE_SUCCESS")),
                "ENCRYPT_SUCCESS": bool(writeback_report.get("ENCRYPT_SUCCESS")),
            }
        )
        if writeback_report.get("writeback_success"):
            postwrite["ready_for_user_manual_qc"] = True
        _merge_prewrite_quality_gate(report, writeback_report)
    semantic_mode = normalize_semantic_mode(config.semantic_mode).value
    postwrite["semantic_mode"] = semantic_mode
    postwrite["semantic_decisions_generated_from_current_draft"] = semantic_mode == SemanticAdjudicationMode.DETERMINISTIC_BASELINE.value
    postwrite["semantic_decisions_reused_from_old_draft"] = False
    if sacrificial_override_used:
        ready_for_user_manual_qc = bool(writeback_report and writeback_report.get("writeback_success"))
        postwrite.update(
            {
                "sacrificial_write_override_used": True,
                "postwrite_decrypt_skipped_for_sacrificial_draft": True,
                "postwrite_decrypt_skip_reason": "ACTUAL_POSTWRITE_DECRYPT_UNAVAILABLE",
                "ready_for_user_manual_qc": ready_for_user_manual_qc,
            }
        )
    validator_postwrite = (report.validator_report or {}).get("postwrite_material_validator")
    if isinstance(validator_postwrite, dict):
        validator_postwrite.update(postwrite)
    if report.blocker_report and isinstance(report.blocker_report.summary, dict):
        report.blocker_report.summary.update(
            {
                "sacrificial_write_override_used": bool(sacrificial_override_used),
                "postwrite_decrypt_skipped_for_sacrificial_draft": bool(
                    postwrite.get("postwrite_decrypt_skipped_for_sacrificial_draft")
                ),
                "postwrite_decrypt_skip_reason": str(postwrite.get("postwrite_decrypt_skip_reason") or ""),
                "writeback_success": bool(postwrite.get("writeback_success")),
                "WRITE_SUCCESS": bool(postwrite.get("WRITE_SUCCESS")),
                "ENCRYPT_SUCCESS": bool(postwrite.get("ENCRYPT_SUCCESS")),
                **{key: postwrite.get(key, value) for key, value in evidence.items()},
            }
        )


def _merge_prewrite_quality_gate(report: RunReport, writeback_report: dict[str, Any]) -> None:
    quality = (report.validator_report or {}).get("quality_gate_report")
    if not isinstance(quality, dict):
        return
    speed_gate = writeback_report.get("effective_speed_gate")
    if not isinstance(speed_gate, dict):
        return
    quality["effective_speed_gate"] = dict(speed_gate)
    quality["effective_speed_gate_present"] = True
    missing = [item for item in quality.get("missing_required_gates") or [] if item != "effective_speed_gate"]
    quality["missing_required_gates"] = missing
    existing_codes = {str(code) for code in quality.get("blocker_codes") or []}
    existing_codes.update(str(code) for code in speed_gate.get("blocker_codes") or [])
    if not missing:
        existing_codes.discard("V21_QUALITY_GATE_MISSING_REQUIRED_GATE")
    quality["blocker_codes"] = sorted(code for code in existing_codes if code)
    quality["gate_passed"] = bool(quality.get("gate_passed")) and bool(speed_gate.get("gate_passed")) and not quality["blocker_codes"]
    quality["ready_for_user_manual_qc_preconditions_passed"] = (
        bool(quality.get("ready_for_user_manual_qc_preconditions_passed"))
        and bool(speed_gate.get("gate_passed"))
        and not quality["blocker_codes"]
    )


def _writeback_blocked_report(report: RunReport, writeback_result: WritebackResult) -> RunReport:
    blockers = list(report.blocker_report.blockers if report.blocker_report else []) + list(writeback_result.blockers)
    summary = dict(report.blocker_report.summary if report.blocker_report else {})
    summary.update(
        {
            "stage": "writeback",
            "writeback_success": False,
            "WRITE_SUCCESS": False,
            "ENCRYPT_SUCCESS": bool(writeback_result.report.get("ENCRYPT_SUCCESS")),
            "write_allowed": False,
            "ready_for_write": False,
            "READY_FOR_DISPOSABLE_WRITE_PRE_AUDIT": False,
        }
    )
    postwrite = dict(report.postwrite_report or {})
    postwrite.update(writeback_result.report)
    return replace(
        report,
        status="blocked",
        postwrite_report=postwrite,
        blocker_report=BlockerReport(blocked=True, blockers=blockers, summary=summary),
    )


def _summary_blocker_codes(summary: dict[str, Any]) -> list[str]:
    raw = summary.get("blocker_codes") or summary.get("BLOCKER_CODES") or []
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [str(item) for item in raw if str(item)]
