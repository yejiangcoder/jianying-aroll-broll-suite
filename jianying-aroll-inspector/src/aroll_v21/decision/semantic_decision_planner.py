from __future__ import annotations

from typing import Any, Protocol

from aroll_v21.decision.decision_trace import decision_trace_row
from aroll_v21.decision.deepseek_request_builder import FORBIDDEN_DEEPSEEK_FIELDS, unit_split_semantic_request_payload
from aroll_v21.decision.deepseek_semantic_planner import (
    BATCH_METADATA_FIELDS,
    DeepSeekSemanticPlannerAdapter,
    SEMANTIC_BATCH_PARTIAL_RESPONSE_CODE,
    SEMANTIC_BATCH_PROVIDER_FAILED_CODE,
    SEMANTIC_BATCH_PROVIDER_MISSING_CODE,
    SEMANTIC_BATCH_REQUIRES_HUMAN_REVIEW_CODE,
)
from aroll_v21.decision.deterministic_baseline_policy import DeterministicBaselinePolicy
from aroll_v21.decision.local_policy import LocalPolicy
from aroll_v21.decision.semantic_adjudication import (
    SemanticAdjudicationReportBuilder,
    SemanticIssueRouter,
    blocker_for_request,
    issue_type_for_cluster,
    normalize_semantic_mode,
    payload_from_request,
    request_from_cluster,
    semantic_blocker_code,
    severity_for_cluster,
)
from aroll_v21.decision.semantic_contracts import (
    SemanticAdjudicationDecision,
    SemanticAdjudicationDecisionType,
    SemanticAdjudicationMode,
    SemanticAdjudicationProvider,
    SemanticAdjudicationResult,
)
from aroll_v21.decision.semantic_json_planner import SEMANTIC_JSON_DECISIONS, SemanticDecisionsJsonPlanner
from aroll_v21.decision.unit_split_binding import (
    _reuse_existing_unit_split,
    _safe_unit_split_ids,
    _unit_split_binding,
    _unit_split_drop_texts,
)
from aroll_v21.ir.models import Blocker, DecisionPlan, RepeatCluster, TakeDecision, UnitSplitPlan


SEMANTIC_PROVIDER_FAILURE_BLOCKER_CODES = {
    "SEMANTIC_DECISION_NOT_PROVIDED",
    "V21_FATAL_MODIFIER_REDUNDANCY_UNRESOLVED",
    "V21_SELF_REPAIR_ABORTED_PHRASE_UNRESOLVED",
    "V21_SEMANTIC_ADJUDICATION_PROVIDER_MISSING",
    "V21_SEMANTIC_ADJUDICATION_PROVIDER_FAILED",
    SEMANTIC_BATCH_PROVIDER_MISSING_CODE,
    SEMANTIC_BATCH_PROVIDER_FAILED_CODE,
    SEMANTIC_BATCH_PARTIAL_RESPONSE_CODE,
    SEMANTIC_BATCH_REQUIRES_HUMAN_REVIEW_CODE,
}

__all__ = [
    "DeepSeekSemanticPlanner",
    "FORBIDDEN_DEEPSEEK_FIELDS",
    "LocalPolicy",
    "SEMANTIC_PROVIDER_FAILURE_BLOCKER_CODES",
    "SemanticDecisionPlanner",
]



class DeepSeekSemanticPlanner(Protocol):
    def decide(self, clusters: list[RepeatCluster]) -> list[dict[str, Any]]:
        """Return semantic decisions only: keep/drop unit ids, reason, confidence."""




class SemanticDecisionPlanner:
    def __init__(
        self,
        local_policy: LocalPolicy | None = None,
        deepseek_planner: DeepSeekSemanticPlanner | None = None,
        *,
        semantic_mode: str = "auto",
        semantic_provider: SemanticAdjudicationProvider | None = None,
        issue_router: SemanticIssueRouter | None = None,
    ) -> None:
        self.local_policy = local_policy or LocalPolicy()
        self.issue_router = issue_router or SemanticIssueRouter()
        self.semantic_mode = normalize_semantic_mode(semantic_mode)
        if semantic_provider is not None and deepseek_planner is None:
            deepseek_planner = DeepSeekSemanticPlannerAdapter(semantic_provider)
        self.deepseek_planner = deepseek_planner
        self.semantic_provider_configured = semantic_provider is not None or bool(getattr(deepseek_planner, "deepseek_provider_configured", False))
        self.semantic_provider_config_source = str(
            getattr(semantic_provider, "config_source", "")
            or getattr(deepseek_planner, "deepseek_provider_config_source", "")
            or ""
        )
        self.semantic_decision_cache_used = bool(getattr(deepseek_planner, "semantic_decision_cache_used", False))

    def plan(self, clusters: list[RepeatCluster]) -> DecisionPlan:
        blockers: list[Blocker] = []
        decisions: list[TakeDecision] = []
        split_decisions: list[UnitSplitPlan] = []
        semantic_request_payloads: list[dict[str, Any]] = []
        decision_trace: list[dict[str, Any]] = []
        semantic_unresolved_cluster_ids: set[str] = set()
        adjudication_report = SemanticAdjudicationReportBuilder(
            mode=self.semantic_mode,
            provider_configured=self.semantic_provider_configured,
            semantic_decision_cache_used=self.semantic_decision_cache_used,
        )
        deterministic_available_by_cluster = {
            cluster.cluster_id: self.local_policy.can_resolve_without_semantic(cluster)
            for cluster in clusters
        }
        routing_by_cluster = {
            cluster.cluster_id: self.issue_router.route_cluster(
                cluster,
                deterministic_action_available=deterministic_available_by_cluster[cluster.cluster_id],
            )
            for cluster in clusters
        }
        if self.semantic_mode == SemanticAdjudicationMode.AUTO:
            for route in routing_by_cluster.values():
                adjudication_report.add_route(route)
        if self.semantic_mode == SemanticAdjudicationMode.AUTO:
            semantic_clusters = [cluster for cluster in clusters if routing_by_cluster[cluster.cluster_id].requires_provider]
        else:
            semantic_clusters = [
                cluster
                for cluster in clusters
                if any(item.requires_semantic_decision for item in cluster.evidence)
                and not deterministic_available_by_cluster[cluster.cluster_id]
            ]
        semantic_decisions = self._deepseek_decisions(
            semantic_clusters,
            blockers,
            semantic_request_payloads,
            decision_trace,
            semantic_unresolved_cluster_ids,
            adjudication_report,
        ) if semantic_clusters else {}

        for cluster in clusters:
            semantic_decision = semantic_decisions.get(cluster.cluster_id)
            if semantic_decision:
                if isinstance(semantic_decision, UnitSplitPlan):
                    split_decisions.append(semantic_decision)
                    decision_trace.append(
                        self._trace(
                            cluster,
                            route="deepseek_required",
                            output_decision=semantic_decision.split_id,
                            reason=semantic_decision.reason,
                        )
                    )
                else:
                    decisions.append(semantic_decision)
                    decision_trace.append(
                        self._trace(
                            cluster,
                            route="deepseek_required",
                            output_decision=semantic_decision.decision_id,
                            reason=semantic_decision.reason,
                        )
                    )
                continue
            if cluster.cluster_id in semantic_unresolved_cluster_ids:
                decision_trace.append(
                    self._trace(
                        cluster,
                        route="self_review",
                        blocker="UNRESOLVED_SEMANTIC_REVIEW_REQUIRED",
                        reason="semantic planner is not configured; unit is conservatively kept for dry-run discovery",
                    )
                )
                continue
            if cluster.local_recommendation == "requires_unit_split":
                recovered_split = self._unit_split_from_existing_reuse(cluster, split_decisions)
                if recovered_split is not None:
                    self._record_locally_resolved_semantic_issue(adjudication_report, cluster, recovered_split.split_id, recovered_split.reason)
                    adjudication_report.add_local_decision()
                    split_decisions.append(recovered_split)
                    decision_trace.append(
                        self._trace(
                            cluster,
                            route="split_generated",
                            output_decision=recovered_split.split_id,
                            reason=recovered_split.reason,
                        )
                    )
                    continue
            local = self.local_policy.decide(cluster)
            if isinstance(local, Blocker):
                if local.code == "UNIT_SPLIT_REQUIRES_HUMAN_REVIEW":
                    recovered_split = self._unit_split_from_existing_reuse(cluster, split_decisions)
                    if recovered_split is not None:
                        self._record_locally_resolved_semantic_issue(adjudication_report, cluster, recovered_split.split_id, recovered_split.reason)
                        adjudication_report.add_local_decision()
                        split_decisions.append(recovered_split)
                        decision_trace.append(
                            self._trace(
                                cluster,
                                route="split_generated",
                                output_decision=recovered_split.split_id,
                                reason=recovered_split.reason,
                            )
                        )
                        continue
                    semantic_decision = self._semantic_decision_for_unit_split_review(cluster, blockers, decision_trace)
                    if semantic_decision is not None:
                        if isinstance(semantic_decision, UnitSplitPlan):
                            split_decisions.append(semantic_decision)
                            decision_trace.append(
                                self._trace(
                                    cluster,
                                    route="deepseek_required",
                                    output_decision=semantic_decision.split_id,
                                    reason=semantic_decision.reason,
                                )
                            )
                        else:
                            decisions.append(semantic_decision)
                        continue
                    self._append_unit_split_semantic_request(semantic_request_payloads, cluster, local)
                blockers.append(local)
                route = "split_required" if local.code.startswith("UNIT_SPLIT") else "blocked"
                decision_trace.append(self._trace(cluster, route=route, blocker=local.code, reason=local.message))
            elif isinstance(local, UnitSplitPlan):
                self._record_locally_resolved_semantic_issue(adjudication_report, cluster, local.split_id, local.reason)
                adjudication_report.add_local_decision()
                split_decisions.append(local)
                decision_trace.append(self._trace(cluster, route="split_generated", output_decision=local.split_id, reason=local.reason))
            else:
                self._record_locally_resolved_semantic_issue(adjudication_report, cluster, local.decision_id, local.reason)
                adjudication_report.add_local_decision()
                decisions.append(local)
                if cluster.local_recommendation == "boundary_prefix_containment_drop_left":
                    route = "boundary_prefix_containment"
                elif cluster.local_recommendation == "self_repair_drop_aborted":
                    route = "self_repair_aborted_phrase"
                else:
                    route = "local_policy"
                decision_trace.append(self._trace(cluster, route=route, output_decision=local.decision_id, reason=local.reason))
        write_blocker_present = any(blocker.severity == "write_blocker" for blocker in blockers)
        human_review_required = bool(semantic_unresolved_cluster_ids) or write_blocker_present or any(decision.requires_human_review for decision in decisions)
        blocker_codes = [blocker.code for blocker in blockers if blocker.severity in {"fatal", "write_blocker"}]
        if self.deepseek_planner is not None:
            adjudication_report.commit_reused_semantic_cache = bool(getattr(self.deepseek_planner, "commit_reused_semantic_cache", False))
            adjudication_report.semantic_cache_input_hash = str(getattr(self.deepseek_planner, "semantic_cache_input_hash", "") or "")
            adjudication_report.semantic_cache_issue_count = int(getattr(self.deepseek_planner, "semantic_cache_issue_count", 0) or 0)
            adjudication_report.semantic_cache_resolved_count = int(getattr(self.deepseek_planner, "semantic_cache_resolved_count", 0) or 0)
            adjudication_report.semantic_cache_unresolved_count = int(getattr(self.deepseek_planner, "semantic_cache_unresolved_count", 0) or 0)
        final_adjudication_report = adjudication_report.to_report(
            unresolved_issue_ids=semantic_unresolved_cluster_ids,
            blocker_codes=blocker_codes,
        )
        final_adjudication_report["deepseek_provider_config_source"] = self.semantic_provider_config_source
        return DecisionPlan(
            decisions=decisions,
            split_decisions=split_decisions,
            blocked=any(blocker.severity == "fatal" for blocker in blockers),
            blockers=blockers,
            semantic_request_payloads=semantic_request_payloads,
            decision_trace=decision_trace,
            semantic_decision_rows=list(getattr(self.deepseek_planner, "rows", []) or []),
            semantic_adjudication_report=final_adjudication_report,
            semantic_unresolved_count=len(semantic_unresolved_cluster_ids),
            requires_human_review=human_review_required,
            write_allowed=not semantic_unresolved_cluster_ids and not human_review_required and not write_blocker_present,
            dry_run_continued_for_discovery=bool(semantic_unresolved_cluster_ids),
        )

    def _record_locally_resolved_semantic_issue(
        self,
        report: SemanticAdjudicationReportBuilder,
        cluster: RepeatCluster,
        decision_id: str,
        reason: str,
    ) -> None:
        if not any(evidence.requires_semantic_decision for evidence in cluster.evidence) and cluster.local_recommendation != "self_repair_drop_aborted":
            return
        request = request_from_cluster(cluster)
        report.add_result(
            SemanticAdjudicationResult(
                request=request,
                decision=SemanticAdjudicationDecision(
                    issue_id=cluster.cluster_id,
                    decision=SemanticAdjudicationDecisionType.DROP_ABORTED
                    if cluster.local_recommendation == "self_repair_drop_aborted"
                    else SemanticAdjudicationDecisionType.REPAIR_TEXT,
                    reason=reason,
                    confidence=0.92,
                    provider_name="local_policy",
                    metadata={"decision_id": decision_id},
                ),
                resolved=True,
                provider_configured=report.provider_configured,
                provider_called=False,
            )
        )

    def _semantic_decision_for_unit_split_review(
        self,
        cluster: RepeatCluster,
        blockers: list[Blocker],
        decision_trace: list[dict[str, Any]],
    ) -> TakeDecision | UnitSplitPlan | None:
        if self.deepseek_planner is None:
            return None
        if isinstance(self.deepseek_planner, DeepSeekSemanticPlannerAdapter):
            return None
        temp_blockers: list[Blocker] = []
        temp_unresolved: set[str] = set()
        temp_report = SemanticAdjudicationReportBuilder(
            mode=self.semantic_mode,
            provider_configured=self.semantic_provider_configured,
            semantic_decision_cache_used=self.semantic_decision_cache_used,
        )
        decisions = self._deepseek_decisions([cluster], temp_blockers, [], decision_trace, temp_unresolved, temp_report)
        decision = decisions.get(cluster.cluster_id)
        if decision is not None:
            return decision
        for blocker in temp_blockers:
            if blocker.code == "SEMANTIC_DECISION_NOT_PROVIDED":
                continue
            blockers.append(blocker)
        return None

    def _append_unit_split_semantic_request(
        self,
        semantic_request_payloads: list[dict[str, Any]],
        cluster: RepeatCluster,
        blocker: Blocker,
    ) -> None:
        existing = {str(payload.get("cluster_id") or "") for payload in semantic_request_payloads}
        if cluster.cluster_id in existing:
            return
        semantic_request_payloads.append(self._unit_split_semantic_request_payload(cluster, blocker))

    def _unit_split_from_existing_reuse(
        self,
        cluster: RepeatCluster,
        split_decisions: list[UnitSplitPlan],
    ) -> UnitSplitPlan | None:
        if len(cluster.variants) != 1:
            return None
        unit = cluster.variants[0]
        if unit.cut_policy == "unsafe":
            return None
        binding = _reuse_existing_unit_split(unit.unit_id, _unit_split_drop_texts(cluster), split_decisions)
        if binding is None:
            return None
        drop_word_ids = list(binding["drop_word_ids"])
        keep_word_ids = list(binding["keep_word_ids"])
        if not _safe_unit_split_ids(unit, drop_word_ids, keep_word_ids):
            return None
        return UnitSplitPlan(
            split_id=f"split_{cluster.cluster_id}",
            cluster_id=cluster.cluster_id,
            unit_id=unit.unit_id,
            drop_word_ids=drop_word_ids,
            keep_word_ids=keep_word_ids,
            reason="repeat evidence recovered safe whole-word split binding",
            source="local_policy",
            requires_human_review=False,
            metadata={
                "repeat_type": cluster.repeat_type,
                "drop_text": str(binding.get("drop_text") or ""),
                "normalized_drop_text": str(binding.get("normalized_drop_text") or ""),
                "binding_source": str(binding.get("binding_source") or ""),
                "reused_split_id": str(binding.get("reused_split_id") or ""),
            },
        )

    def _suggested_unit_split_word_ids(self, cluster: RepeatCluster) -> dict[str, list[str]]:
        binding = _unit_split_binding(cluster)
        return {"drop_word_ids": list(binding["drop_word_ids"]), "keep_word_ids": list(binding["keep_word_ids"])}

    def _deepseek_decisions(
        self,
        clusters: list[RepeatCluster],
        blockers: list[Blocker],
        semantic_request_payloads: list[dict[str, Any]],
        decision_trace: list[dict[str, Any]],
        semantic_unresolved_cluster_ids: set[str],
        adjudication_report: SemanticAdjudicationReportBuilder,
    ) -> dict[str, TakeDecision | UnitSplitPlan]:
        if self.deepseek_planner is None and self.semantic_mode == SemanticAdjudicationMode.DETERMINISTIC_BASELINE:
            raw_rows = self._deterministic_baseline_rows(clusters)
        elif self.deepseek_planner is None:
            for cluster in clusters:
                request = request_from_cluster(cluster)
                payload = payload_from_request(request)
                provider_missing_code = (
                    SEMANTIC_BATCH_PROVIDER_MISSING_CODE
                    if self.semantic_mode in {SemanticAdjudicationMode.AUTO, SemanticAdjudicationMode.DEEPSEEK}
                    else "SEMANTIC_DECISION_NOT_PROVIDED"
                )
                if request.severity.value == "low" and self.semantic_mode == SemanticAdjudicationMode.AUTO:
                    semantic_request_payloads.append(payload | {"warning_only": True})
                    adjudication_report.add_result(
                        SemanticAdjudicationResult(
                            request=request,
                            resolved=False,
                            provider_configured=False,
                            provider_called=False,
                            blocker_code="SEMANTIC_PROVIDER_SKIPPED_LOW_RISK",
                            message="provider unavailable for low-risk issue; emitted warning only",
                        )
                    )
                    decision_trace.append(
                        self._trace(
                            cluster,
                            route="semantic_warning",
                            blocker="SEMANTIC_PROVIDER_SKIPPED_LOW_RISK",
                            reason="low-risk semantic issue did not require provider fail-closed",
                        )
                    )
                    continue
                semantic_unresolved_cluster_ids.add(cluster.cluster_id)
                semantic_request_payloads.append(payload)
                blockers.append(
                    blocker_for_request(
                        request,
                        code=provider_missing_code,
                        message="semantic adjudication provider is not configured",
                    )
                )
                if provider_missing_code == SEMANTIC_BATCH_PROVIDER_MISSING_CODE:
                    blockers.append(
                        blocker_for_request(
                            request,
                            code="V21_SEMANTIC_ADJUDICATION_PROVIDER_MISSING",
                            message="semantic adjudication provider is not configured",
                        )
                    )
                legacy_missing = Blocker(
                    code="DEEPSEEK_SEMANTIC_PLANNER_NOT_CONFIGURED",
                    message="semantic cluster requires DeepSeek/local semantic planner",
                    layer="decision",
                    severity="write_blocker",
                    context={
                        "cluster_id": cluster.cluster_id,
                        "repeat_type": cluster.repeat_type,
                        "missing_config": "deepseek_semantic_planner",
                        "requires_human_review": True,
                        "allows_dry_run_discovery": True,
                        "write_allowed": False,
                    },
                )
                blockers.append(legacy_missing)
                issue_blocker_code = semantic_blocker_code(request.issue_type, request.severity)
                if issue_blocker_code not in {provider_missing_code, legacy_missing.code}:
                    blockers.append(blocker_for_request(request, code=issue_blocker_code))
                adjudication_report.add_result(
                    SemanticAdjudicationResult(
                        request=request,
                        resolved=False,
                        provider_configured=False,
                        provider_called=False,
                        blocker_code=provider_missing_code,
                        message="provider missing; high/fatal semantic issue fail-closed",
                    )
                )
                decision_trace.append(
                    self._trace(
                        cluster,
                        route="deepseek_required",
                        blocker=provider_missing_code,
                        reason="semantic planner is not configured; request payload emitted",
                    )
                )
                if provider_missing_code == SEMANTIC_BATCH_PROVIDER_MISSING_CODE:
                    decision_trace.append(
                        self._trace(
                            cluster,
                            route="deepseek_required",
                            blocker="V21_SEMANTIC_ADJUDICATION_PROVIDER_MISSING",
                            reason="semantic planner is not configured; legacy provider-missing trace alias",
                        )
                    )
            return {}
        else:
            raw_rows = self.deepseek_planner.decide(clusters)
        adjudication_report.provider_configured = self.semantic_provider_configured
        adjudication_report.provider_error = str(getattr(self.deepseek_planner, "deepseek_provider_error", "") or "")
        called_count = int(getattr(self.deepseek_planner, "provider_called_count", 0) or 0)
        adjudication_report.provider_called_count = called_count
        for field_name in BATCH_METADATA_FIELDS:
            value = getattr(self.deepseek_planner, field_name, None)
            if value is not None:
                setattr(adjudication_report, field_name, value)
        decision_rows = list(getattr(self.deepseek_planner, "decision_rows", []) or [])
        decision_by_issue = {
            str(row.get("issue_id") or ""): row
            for row in decision_rows
            if isinstance(row, dict)
        }
        decisions: dict[str, TakeDecision | UnitSplitPlan] = {}
        valid_unit_ids = {unit.unit_id for cluster in clusters for unit in cluster.variants}
        valid_word_ids = {word_id for cluster in clusters for unit in cluster.variants for word_id in unit.word_ids}
        valid_cluster_ids = {cluster.cluster_id for cluster in clusters}
        processed_cluster_ids: set[str] = set()
        for index, row in enumerate(raw_rows, start=1):
            explicit_blocker = str(row.get("_blocker_code") or "")
            cluster_id = str(row.get("cluster_id") or "")
            if cluster_id:
                processed_cluster_ids.add(cluster_id)
            if explicit_blocker:
                cluster = next((item for item in clusters if item.cluster_id == cluster_id), None)
                if explicit_blocker in SEMANTIC_PROVIDER_FAILURE_BLOCKER_CODES:
                    semantic_unresolved_cluster_ids.add(cluster_id)
                    if cluster is not None:
                        request = request_from_cluster(cluster)
                        adjudication_report.add_result(
                            SemanticAdjudicationResult(
                                request=request,
                                resolved=False,
                                provider_configured=self.semantic_provider_configured,
                                provider_called=called_count > 0,
                                deterministic_baseline_refused=bool(row.get("_deterministic_baseline_refused")),
                                blocker_code=explicit_blocker,
                                message=str(row.get("_message") or explicit_blocker),
                            )
                        )
                        adjudication_report.provider_called_count = called_count
                        existing_payload_ids = {str(payload.get("cluster_id") or "") for payload in semantic_request_payloads}
                        if cluster.cluster_id not in existing_payload_ids:
                            semantic_request_payloads.append(payload_from_request(request))
                blockers.append(
                    Blocker(
                        code=explicit_blocker,
                        message=str(row.get("_message") or "semantic decision row is not usable"),
                        layer="decision",
                        severity=str(row.get("_severity") or "fatal"),  # type: ignore[arg-type]
                        context={
                            "cluster_id": cluster_id,
                            "forbidden_fields": list(row.get("_forbidden_fields") or []),
                            "decision": str(row.get("_decision") or ""),
                        },
                    )
                )
                decision_trace.append(
                    self._trace(
                        cluster or clusters[0],
                        route="blocked" if explicit_blocker != "SEMANTIC_DECISION_NOT_PROVIDED" else "self_review",
                        blocker=explicit_blocker,
                        reason=str(row.get("_message") or explicit_blocker),
                    )
                )
                continue
            forbidden = sorted(FORBIDDEN_DEEPSEEK_FIELDS & set(row.keys()))
            if forbidden:
                blockers.append(
                    Blocker(
                        code="DEEPSEEK_DECISION_HAS_PHYSICAL_FIELDS",
                        message="DeepSeek decision attempted to control physical timeline/material fields",
                        layer="decision",
                        context={"cluster_id": cluster_id, "forbidden_fields": forbidden},
                    )
                )
                decision_trace.append(
                    self._trace(
                        next((cluster for cluster in clusters if cluster.cluster_id == cluster_id), clusters[0]),
                        route="blocked",
                        blocker="DEEPSEEK_DECISION_HAS_PHYSICAL_FIELDS",
                        reason="DeepSeek decision attempted physical control",
                    )
                )
                continue
            if row.get("_decision_kind") == "unit_split":
                unit_id = str(row.get("unit_id") or "")
                drop_word_ids = [str(item) for item in row.get("drop_word_ids") or [] if str(item)]
                keep_word_ids = [str(item) for item in row.get("keep_word_ids") or [] if str(item)]
                if (
                    cluster_id not in valid_cluster_ids
                    or unit_id not in valid_unit_ids
                    or any(word_id not in valid_word_ids for word_id in drop_word_ids + keep_word_ids)
                ):
                    blockers.append(
                        Blocker(
                            code="DEEPSEEK_DECISION_UNKNOWN_UNIT",
                            message="semantic split decision referenced unknown cluster, unit, or word id",
                            layer="decision",
                            context={
                                "cluster_id": cluster_id,
                                "unit_id": unit_id,
                                "drop_word_ids": drop_word_ids,
                                "keep_word_ids": keep_word_ids,
                            },
                        )
                    )
                    continue
                decisions[cluster_id] = UnitSplitPlan(
                    split_id=str(row.get("split_id") or f"deepseek_split_{index:06d}"),
                    cluster_id=cluster_id,
                    unit_id=unit_id,
                    drop_word_ids=drop_word_ids,
                    keep_word_ids=keep_word_ids,
                    reason=str(row.get("reason") or ""),
                    source=str(row.get("_decision_source") or "deepseek_semantic_planner"),  # type: ignore[arg-type]
                    requires_human_review=bool(row.get("requires_human_review")),
                    metadata={"semantic_json_decision": str(row.get("_semantic_json_decision") or "")},
                )
                cluster = next((item for item in clusters if item.cluster_id == cluster_id), None)
                if cluster is not None:
                    adjudication_report.add_result(
                        SemanticAdjudicationResult(
                            request=request_from_cluster(cluster),
                            decision=_adjudication_decision_from_row(row, decision_by_issue.get(cluster_id)),
                            resolved=True,
                            provider_configured=self.semantic_provider_configured,
                            provider_called=called_count > 0,
                        )
                    )
                continue
            keep_unit_id = str(row.get("keep_unit_id") or "")
            drop_unit_ids = [str(item) for item in row.get("drop_unit_ids") or [] if str(item)]
            if cluster_id not in valid_cluster_ids or keep_unit_id not in valid_unit_ids or any(unit_id not in valid_unit_ids for unit_id in drop_unit_ids):
                blockers.append(
                    Blocker(
                        code="DEEPSEEK_DECISION_UNKNOWN_UNIT",
                        message="DeepSeek decision referenced unknown cluster or unit id",
                        layer="decision",
                        context={"cluster_id": cluster_id, "keep_unit_id": keep_unit_id, "drop_unit_ids": drop_unit_ids},
                    )
                )
                continue
            source = str(row.get("_decision_source") or "deepseek_semantic_planner")
            if source not in {"deepseek_semantic_planner", "semantic_decisions_json", "deterministic_baseline"}:
                source = "deepseek_semantic_planner"
            decisions[cluster_id] = TakeDecision(
                decision_id=str(row.get("decision_id") or f"deepseek_decision_{index:06d}"),
                cluster_id=cluster_id,
                keep_unit_id=keep_unit_id,
                drop_unit_ids=drop_unit_ids,
                reason=str(row.get("reason") or ""),
                confidence=float(row.get("confidence") or 0.0),
                requires_human_review=bool(row.get("requires_human_review")),
                source=source,  # type: ignore[arg-type]
            )
            cluster = next((item for item in clusters if item.cluster_id == cluster_id), None)
            if cluster is not None:
                adjudication_report.add_result(
                    SemanticAdjudicationResult(
                        request=request_from_cluster(cluster),
                        decision=_adjudication_decision_from_row(row, decision_by_issue.get(cluster_id)),
                        resolved=True,
                            provider_configured=self.semantic_provider_configured,
                        provider_called=called_count > 0,
                    )
                )
        missing_cluster_ids = {cluster.cluster_id for cluster in clusters} - processed_cluster_ids
        for cluster in clusters:
            if cluster.cluster_id not in missing_cluster_ids:
                continue
            request = request_from_cluster(cluster)
            semantic_unresolved_cluster_ids.add(cluster.cluster_id)
            existing_payload_ids = {str(payload.get("cluster_id") or "") for payload in semantic_request_payloads}
            if cluster.cluster_id not in existing_payload_ids:
                semantic_request_payloads.append(payload_from_request(request))
            is_deterministic_baseline = any(
                str(row.get("_decision_source") or row.get("decision_source") or "") == "deterministic_baseline"
                or str(row.get("_semantic_mode") or row.get("semantic_mode") or "") in {"deterministic_baseline", "deterministic-baseline"}
                for row in raw_rows
                if isinstance(row, dict)
            ) or self.semantic_mode == SemanticAdjudicationMode.DETERMINISTIC_BASELINE
            blocker_code = semantic_blocker_code(request.issue_type, request.severity)
            blockers.append(
                blocker_for_request(
                    request,
                    code=blocker_code,
                    message="semantic planner did not return an actionable decision for this high-risk issue",
                )
            )
            adjudication_report.add_result(
                SemanticAdjudicationResult(
                    request=request,
                    resolved=False,
                    provider_configured=self.semantic_provider_configured,
                    provider_called=called_count > 0,
                    deterministic_baseline_refused=is_deterministic_baseline,
                    blocker_code=blocker_code,
                    message="planner returned no decision row",
                )
            )
        adjudication_report.provider_called_count = called_count
        return decisions

    def _deterministic_baseline_rows(self, clusters: list[RepeatCluster]) -> list[dict[str, Any]]:
        policy = DeterministicBaselinePolicy()
        rows: list[dict[str, Any]] = []
        for cluster in clusters:
            keep_unit_id = cluster.variants[0].unit_id if cluster.variants else ""
            row = policy.decision_for_missing_cluster(
                cluster.cluster_id,
                cluster_type=str(cluster.repeat_type or ""),
                context={
                    "keep_unit_id": keep_unit_id,
                    "drop_unit_ids": [],
                    "reason": "deterministic baseline keeps low-risk semantic speech units only",
                    "severity": severity_for_cluster(cluster).value,
                    "requires_semantic_decision": any(item.requires_semantic_decision for item in cluster.evidence),
                    "confidence": max((float(item.confidence or 0.0) for item in cluster.evidence), default=0.0),
                },
            )
            if row is not None:
                rows.append(row)
                continue
            rows.append(
                {
                    "cluster_id": cluster.cluster_id,
                    "_blocker_code": semantic_blocker_code(issue_type_for_cluster(cluster), severity_for_cluster(cluster)),
                    "_severity": "write_blocker",
                    "_message": "deterministic baseline refused high-risk semantic issue",
                    "_decision_source": "deterministic_baseline",
                    "_semantic_mode": "deterministic_baseline",
                    "_deterministic_baseline_refused": True,
                }
            )
        return rows

    def _unit_split_semantic_request_payload(self, cluster: RepeatCluster, blocker: Blocker) -> dict[str, Any]:
        return unit_split_semantic_request_payload(cluster, blocker)


    def _modifier_candidate(self, cluster: RepeatCluster) -> dict[str, Any]:
        for evidence in cluster.evidence:
            metadata = evidence.metadata if isinstance(evidence.metadata, dict) else {}
            candidate = metadata.get("candidate") if isinstance(metadata.get("candidate"), dict) else {}
            if candidate:
                return candidate
        return {}

    def _trace(
        self,
        cluster: RepeatCluster,
        *,
        route: str,
        output_decision: str = "",
        blocker: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        return decision_trace_row(
            cluster,
            route=route,
            output_decision=output_decision,
            blocker=blocker,
            reason=reason,
        )



def _adjudication_decision_from_row(
    row: dict[str, Any],
    provider_row: dict[str, Any] | None = None,
) -> SemanticAdjudicationDecision:
    provider_row = provider_row or {}
    raw_decision = str(row.get("_semantic_json_decision") or provider_row.get("decision") or "keep_all")
    if raw_decision == "drop_redundant_modifier":
        raw_decision = SemanticAdjudicationDecisionType.REPAIR_TEXT.value
    if raw_decision not in {item.value for item in SemanticAdjudicationDecisionType}:
        raw_decision = SemanticAdjudicationDecisionType.KEEP_ALL.value
    return SemanticAdjudicationDecision(
        issue_id=str(row.get("cluster_id") or provider_row.get("issue_id") or ""),
        decision=SemanticAdjudicationDecisionType(raw_decision),
        reason=str(row.get("reason") or provider_row.get("reason") or ""),
        confidence=float(row.get("confidence") or provider_row.get("confidence") or 0.0),
        provider_name=str(provider_row.get("provider_name") or row.get("_decision_source") or "deepseek_semantic_planner"),
        keep_unit_id=str(row.get("keep_unit_id") or provider_row.get("keep_unit_id") or ""),
        drop_unit_ids=[str(item) for item in row.get("drop_unit_ids") or provider_row.get("drop_unit_ids") or [] if str(item)],
        unit_id=str(row.get("unit_id") or provider_row.get("unit_id") or ""),
        drop_word_ids=[str(item) for item in row.get("drop_word_ids") or provider_row.get("drop_word_ids") or [] if str(item)],
        keep_word_ids=[str(item) for item in row.get("keep_word_ids") or provider_row.get("keep_word_ids") or [] if str(item)],
        repair_text=str(provider_row.get("repair_text") or ""),
        requires_human_review=bool(row.get("requires_human_review") or provider_row.get("requires_human_review")),
        metadata={
            "legacy_row": {
                key: value
                for key, value in row.items()
                if key
                not in {
                    "cluster_id",
                    "keep_unit_id",
                    "drop_unit_ids",
                    "unit_id",
                    "drop_word_ids",
                    "keep_word_ids",
                    "reason",
                    "confidence",
                    "requires_human_review",
                }
            }
        },
    )
