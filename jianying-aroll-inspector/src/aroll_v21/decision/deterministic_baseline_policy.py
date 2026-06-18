from __future__ import annotations

from typing import Any

from aroll_v21.contracts import BaselineDecisionKind, DecisionSource, SemanticMode


NEAR_DUPLICATE_DROP_THRESHOLD = 0.90
BASELINE_REFUSED_CLUSTER_TYPES = {
    "modifier_redundancy",
    "self_repair_aborted_phrase",
    "semantic_containment",
    "semantic_containment_take",
    "visible_caption_repeat",
}
BASELINE_REFUSED_RISK_LEVELS = {"medium", "high", "fatal"}


class DeterministicBaselinePolicy:
    """Explicit sacrificial-UAT semantic decision policy.

    The policy only creates decision rows. It does not mutate validators,
    candidates, or timelines.
    """

    def is_enabled(self, decision_plan: Any) -> bool:
        rows = list(getattr(decision_plan, "semantic_decision_rows", []) or [])
        return any(self._row_enables_policy(row) for row in rows if isinstance(row, dict))

    def decision_for_missing_cluster(
        self,
        cluster_id: str,
        cluster_type: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        context = dict(context or {})
        effective_cluster_type = str(cluster_type or context.get("cluster_type") or "")
        if self._must_refuse_missing_cluster(effective_cluster_type, context):
            no_baseline_decision = None
            return no_baseline_decision
        return self._baseline_row(
            cluster_id=cluster_id,
            decision=BaselineDecisionKind.KEEP_ALL.value,
            reason=str(context.get("reason") or "deterministic baseline keeps low-risk missing semantic cluster"),
            confidence=float(context.get("confidence") or 0.65),
            keep_unit_id=str(context.get("keep_unit_id") or ""),
            drop_unit_ids=[str(item) for item in context.get("drop_unit_ids") or [] if str(item)],
            cluster_type=effective_cluster_type,
        )

    def decision_for_final_repeat_candidate(self, candidate: dict[str, Any]) -> dict[str, Any] | None:
        cluster_id = self._cluster_id(candidate)
        if self._is_high_near_duplicate_take(candidate):
            drop_index = int(candidate.get("recommended_drop_index") or 0)
            return self._baseline_row(
                cluster_id=cluster_id,
                decision=BaselineDecisionKind.DROP_RECOMMENDED.value,
                reason="deterministic baseline drops the recommended high-confidence duplicate take",
                confidence=float(candidate.get("score") or 0.95),
                cluster_type="near_duplicate_take",
                drop_index=drop_index,
                v21_resolution="accepted_by_deterministic_baseline_drop_recommended",
            )
        no_policy_decision = None
        return no_policy_decision

    def _baseline_row(
        self,
        *,
        cluster_id: str,
        decision: str,
        reason: str,
        confidence: float,
        cluster_type: str = "",
        keep_unit_id: str = "",
        drop_unit_ids: list[str] | None = None,
        drop_index: int | None = None,
        v21_resolution: str = "accepted_by_deterministic_baseline",
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "decision_id": f"deterministic_baseline_{cluster_id}",
            "cluster_id": cluster_id,
            "cluster_type": cluster_type,
            "decision": decision,
            "reason": reason,
            "confidence": confidence,
            "requires_human_review": False,
            "decision_source": DecisionSource.DETERMINISTIC_BASELINE.value,
            "semantic_mode": SemanticMode.DETERMINISTIC_BASELINE.value,
            "v21_resolution": v21_resolution,
            "_decision_source": DecisionSource.DETERMINISTIC_BASELINE.value,
            "_semantic_mode": SemanticMode.DETERMINISTIC_BASELINE.value,
            "_synthetic_for_current_draft": True,
        }
        if keep_unit_id:
            row["keep_unit_id"] = keep_unit_id
        if drop_unit_ids is not None:
            row["drop_unit_ids"] = list(drop_unit_ids)
        if drop_index is not None:
            row["drop_index"] = int(drop_index)
            row["recommended_drop_index"] = int(drop_index)
        return row

    def _is_high_near_duplicate_take(self, candidate: dict[str, Any]) -> bool:
        if str(candidate.get("cluster_type") or "") != "near_duplicate_take":
            return False
        if str(candidate.get("confidence") or "") != "high":
            return False
        if bool(candidate.get("requires_llm")):
            return False
        if int(candidate.get("recommended_drop_index") or 0) <= 0:
            return False
        return self._candidate_similarity(candidate) >= NEAR_DUPLICATE_DROP_THRESHOLD

    def _candidate_similarity(self, candidate: dict[str, Any]) -> float:
        similarity = candidate.get("similarity")
        if isinstance(similarity, (int, float)):
            return float(similarity)
        pairwise = [float(row.get("similarity") or 0.0) for row in candidate.get("pairwise_evidence") or [] if isinstance(row, dict)]
        return min(pairwise) if pairwise else 0.0

    def _cluster_id(self, candidate: dict[str, Any]) -> str:
        raw = str(candidate.get("cluster_id") or "")
        return raw if raw.startswith("final_target_repeat_") else f"final_target_repeat_{raw}"

    def _must_refuse_missing_cluster(self, cluster_type: str, context: dict[str, Any]) -> bool:
        if cluster_type in BASELINE_REFUSED_CLUSTER_TYPES:
            return True
        risk = str(context.get("severity") or context.get("risk") or "").strip().lower()
        if risk in BASELINE_REFUSED_RISK_LEVELS:
            return True
        confidence_label = str(context.get("confidence_label") or "").strip().lower()
        if confidence_label in BASELINE_REFUSED_RISK_LEVELS:
            return True
        if bool(context.get("requires_llm")):
            return True
        if bool(context.get("requires_semantic_decision")):
            confidence = context.get("confidence")
            if isinstance(confidence, (int, float)) and float(confidence) >= 0.65:
                return True
            if str(confidence).strip().lower() in BASELINE_REFUSED_RISK_LEVELS:
                return True
        return False

    def _row_enables_policy(self, row: dict[str, Any]) -> bool:
        values = {
            str(row.get("_semantic_mode") or ""),
            str(row.get("semantic_mode") or ""),
            str(row.get("_decision_source") or ""),
            str(row.get("decision_source") or ""),
        }
        return bool({"deterministic_baseline", "deterministic-baseline"} & values)
