from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _item_id(row: dict[str, Any], fallback: int) -> str:
    return str(row.get("candidate_id") or row.get("unit_id") or row.get("issue_id") or f"self_review_{fallback:04d}")


def collect_self_review_candidates(
    *,
    decision_plan: dict[str, Any] | None = None,
    repeat_plan: dict[str, Any] | None = None,
    post_semantic_repeat_plan: dict[str, Any] | None = None,
    final_audit_candidates: list[dict[str, Any]] | None = None,
    final_audit_results: list[dict[str, Any]] | None = None,
    after_audit: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    result_by_id = {
        str(row.get("candidate_id") or row.get("unit_id") or ""): row
        for row in (final_audit_results or [])
    }

    for row in (decision_plan or {}).get("codex_self_review_items") or []:
        rows.append(
            {
                "source": "decision_plan",
                "item_id": _item_id(row, len(rows) + 1),
                "reason": row.get("self_review_reason") or "decision plan requires Codex self-review",
                "candidate": row,
            }
        )
    for row in (decision_plan or {}).get("conservative_keep_items") or []:
        rows.append(
            {
                "source": "decision_plan_conservative_keep",
                "item_id": _item_id(row, len(rows) + 1),
                "reason": row.get("self_review_reason") or "deletion self-review resolved by conservative keep",
                "candidate": row,
                "resolved_by_conservative_keep": True,
            }
        )
    for row in (decision_plan or {}).get("overlap_merge_items") or []:
        rows.append(
            {
                "source": "decision_plan_overlap_merge",
                "item_id": _item_id(row, len(rows) + 1),
                "reason": row.get("self_review_reason") or "self-review resolved by suffix-prefix overlap merge",
                "candidate": row,
                "resolved_by_overlap_merge": True,
            }
        )

    for plan_name, plan in [
        ("repeat_plan", repeat_plan or {}),
        ("post_semantic_repeat_plan", post_semantic_repeat_plan or {}),
    ]:
        for row in plan.get("codex_self_review") or []:
            rows.append(
                {
                    "source": plan_name,
                    "item_id": _item_id(row, len(rows) + 1),
                    "reason": row.get("self_review_reason") or "repeat fix requires Codex self-review",
                    "candidate": row,
                }
            )

    for candidate in final_audit_candidates or []:
        cid = str(candidate.get("candidate_id") or "")
        result = result_by_id.get(cid)
        if not result:
            rows.append(
                {
                    "source": "final_audit_llm_missing",
                    "item_id": cid or _item_id(candidate, len(rows) + 1),
                    "reason": "final audit candidate has no LLM result",
                    "candidate": candidate,
                }
            )
            continue
        if str(result.get("classification") or "") == "codex_self_review_required" or str(result.get("approved_action") or "") == "self_review":
            rows.append(
                {
                    "source": "final_audit_llm_result",
                    "item_id": cid or _item_id(candidate, len(rows) + 1),
                    "reason": result.get("reason") or "final audit LLM requested Codex self-review",
                    "candidate": candidate,
                    "llm_result": result,
                }
            )

    for issue in (after_audit or {}).get("issues") or []:
        if issue.get("requires_llm"):
            rows.append(
                {
                    "source": "post_semantic_after_audit",
                    "item_id": _item_id(issue, len(rows) + 1),
                    "reason": "post-semantic residual repeat requires semantic decision",
                    "candidate": issue,
                }
            )
    return rows


def build_self_review_report(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    conservative_keep = [
        row
        for row in candidates
        if row.get("resolved_by_conservative_keep")
        or (row.get("candidate") or {}).get("resolved_by_conservative_keep")
    ]
    overlap_merge = [
        row
        for row in candidates
        if row.get("resolved_by_overlap_merge")
        or (row.get("candidate") or {}).get("resolved_by_overlap_merge")
    ]
    unresolved = [
        row
        for row in candidates
        if row not in conservative_keep and row not in overlap_merge
    ]
    return {
        "self_review_candidate_count": len(candidates),
        "resolved_by_context_expansion": 0,
        "resolved_by_second_llm_pass": 0,
        "resolved_by_conservative_keep": len(conservative_keep),
        "resolved_by_overlap_merge": len(overlap_merge),
        "resolved_by_alternative_cut_plan": 0,
        "accepted_low_confidence_false_positive_count": 0,
        "blocked_unresolved_count": len(unresolved),
        "codex_self_review_unresolved_count": len(unresolved),
        "unresolved_items": unresolved,
        "conservative_keep_items": conservative_keep,
        "overlap_merge_items": overlap_merge,
        "write_blocked_by_self_review": bool(unresolved),
    }


def write_self_review_outputs(run_dir: Path, report: dict[str, Any]) -> None:
    write_json(run_dir / "codex_self_review_report.json", report)
    lines = [
        "# Codex Self Review Report",
        "",
        f"- self_review_candidate_count: {report.get('self_review_candidate_count')}",
        f"- resolved_by_conservative_keep: {report.get('resolved_by_conservative_keep')}",
        f"- resolved_by_overlap_merge: {report.get('resolved_by_overlap_merge')}",
        f"- blocked_unresolved_count: {report.get('blocked_unresolved_count')}",
        f"- write_blocked_by_self_review: {report.get('write_blocked_by_self_review')}",
        "",
        "## Unresolved Items",
    ]
    if not report.get("unresolved_items"):
        lines.append("- none")
    for row in report.get("unresolved_items") or []:
        lines.append(f"- {row.get('source')} | {row.get('item_id')} | {row.get('reason')}")
    (run_dir / "codex_self_review_report.md").write_text("\n".join(lines) + "\n", "utf-8")
    (run_dir / "uat_self_review_summary.md").write_text(
        "\n".join(
            [
                "# UAT Self Review Summary",
                "",
                f"- unresolved: {report.get('codex_self_review_unresolved_count')}",
                f"- blocked: {report.get('write_blocked_by_self_review')}",
            ]
        )
        + "\n",
        "utf-8",
    )
