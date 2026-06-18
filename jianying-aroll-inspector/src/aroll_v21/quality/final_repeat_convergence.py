from __future__ import annotations

from typing import Any

from aroll_v21.contracts import FinalRepeatConvergenceReport, contract_to_dict
from aroll_v21.quality.repeat_span_repair import dropped_span_report


def build_final_repeat_convergence_report(
    *,
    decision_trace: list[dict[str, Any]],
    final_repeat_report: dict[str, Any],
) -> dict[str, Any]:
    detector_report = final_repeat_report if isinstance(final_repeat_report, dict) else {}
    detector_report_present = (
        "final_target_repeat_high_count" in detector_report
        and "final_target_repeat_candidates" in detector_report
    )
    dropped = dropped_span_report(decision_trace)
    iterations: set[int] = set()
    for row in decision_trace:
        if not isinstance(row, dict) or row.get("route") != "final_target_repeat":
            continue
        if not row.get("applied"):
            continue
        decision = str(row.get("decision") or "")
        if decision not in {"drop_recommended", "auto_drop_high_confidence_exact_repeat", "drop_left", "drop_right", "keep_longest_drop_others"}:
            continue
        iteration = int(row.get("convergence_iteration") or 0)
        if iteration > 0:
            iterations.add(iteration)
    high_after = int(detector_report.get("final_target_repeat_high_count") or 0)
    unresolved = [
        str(row.get("cluster_id") or "")
        for row in detector_report.get("final_target_repeat_candidates") or []
        if isinstance(row, dict)
        and str(row.get("confidence") or "") == "high"
        and str(row.get("v21_resolution") or "").startswith("fatal")
    ]
    blocker_codes = []
    if not detector_report_present:
        blocker_codes.append("V21_FINAL_REPEAT_DETECTOR_REPORT_MISSING")
    if high_after or unresolved:
        blocker_codes.append("V21_FINAL_REPEAT_UNRESOLVED_AFTER_CONVERGENCE")
    report = contract_to_dict(
        FinalRepeatConvergenceReport(
            enabled=True,
            iterations=max(iterations, default=0),
            dropped_cluster_ids=list(dropped["dropped_cluster_ids"]),
            dropped_segment_indices=list(dropped["dropped_segment_indices"]),
            final_repeat_high_count_before=int(dropped["dropped_cluster_count"]) + high_after,
            final_repeat_high_count_after=high_after,
            unresolved_high_cluster_ids=sorted(set(unresolved)),
            gate_passed=not blocker_codes,
            blocker_codes=blocker_codes,
        )
    )
    report.update(
        {
            "detector_report_present": detector_report_present,
            "dropped_cluster_count": int(dropped["dropped_cluster_count"]),
            "dropped_segment_count": int(dropped["dropped_segment_count"]),
            "final_repeat_dropped_segment_count": int(dropped["dropped_segment_count"]),
            "clusters_per_dropped_segment": dict(dropped["clusters_per_dropped_segment"]),
        }
    )
    return report
