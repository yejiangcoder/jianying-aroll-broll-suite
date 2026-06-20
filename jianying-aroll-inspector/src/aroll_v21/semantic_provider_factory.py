from __future__ import annotations

import hashlib
from typing import Any

from aroll_v21.decision import DeterministicBaselinePolicy, SemanticDecisionsJsonPlanner
from aroll_v21.decision.deepseek_semantic_planner import (
    deepseek_provider_from_runtime_config as deepseek_provider_from_env,
)
from aroll_v21.decision.semantic_adjudication import normalize_semantic_mode, severity_for_cluster
from aroll_v21.decision.semantic_contracts import SemanticAdjudicationMode
from aroll_v21.ir.models import Blocker
from aroll_v21.operator_config import ArollV21OperatorConfig
from aroll_v21.operator_io import read_json


class DeterministicBaselineSemanticPlanner:
    """Explicit baseline planner for low-risk deterministic semantic clusters."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.policy = DeterministicBaselinePolicy()
        self.deterministic_baseline_refused_count = 0

    def decide(self, clusters) -> list[dict[str, Any]]:
        self.rows = []
        self.deterministic_baseline_refused_count = 0
        for cluster in clusters:
            keep_unit_id = cluster.variants[0].unit_id if cluster.variants else ""
            row = self.policy.decision_for_missing_cluster(
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
                self.rows.append(row)
                continue
            self.deterministic_baseline_refused_count += 1
            self.rows.append(
                {
                    "cluster_id": cluster.cluster_id,
                    "_blocker_code": "V21_FATAL_MODIFIER_REDUNDANCY_UNRESOLVED"
                    if str(cluster.repeat_type or "") == "modifier_redundancy"
                    else "SEMANTIC_DECISION_NOT_PROVIDED",
                    "_severity": "write_blocker",
                    "_message": "deterministic baseline refused high-risk semantic issue",
                    "_decision_source": "deterministic_baseline",
                    "_semantic_mode": "deterministic_baseline",
                    "_deterministic_baseline_refused": True,
                }
            )
        return list(self.rows)


def _semantic_decisions_planner(
    config: ArollV21OperatorConfig,
    *,
    provider_factory=deepseek_provider_from_env,
) -> tuple[Any | None, Any | None, Blocker | None]:
    semantic_mode = normalize_semantic_mode(config.semantic_mode)
    if semantic_mode == SemanticAdjudicationMode.DETERMINISTIC_BASELINE:
        if config.semantic_decisions_json is not None:
            return None, None, Blocker(
                code="SEMANTIC_MODE_CONFLICT",
                message="deterministic baseline semantic mode must not be combined with semantic_decisions_json",
                layer="operator",
                context={"semantic_decisions_json": str(config.semantic_decisions_json)},
            )
        return DeterministicBaselineSemanticPlanner(), None, None
    if str(config.semantic_mode or "") not in {
        "",
        "default",
        "auto",
        "semantic-requests-only",
        "semantic_requests_only",
        "deepseek",
        "fail-closed",
        "fail_closed",
    }:
        return None, None, Blocker(
            code="SEMANTIC_MODE_UNSUPPORTED",
            message="unsupported V21 semantic mode",
            layer="operator",
            context={"semantic_mode": config.semantic_mode},
        )
    cache_path = config.run_dir / "semantic_decision_cache.json"
    cache_input_hash = _semantic_cache_input_hash(config)
    if config.semantic_decisions_json is None and config.mode == "write" and cache_path.exists():
        try:
            rows = read_json(cache_path)
        except Exception as exc:
            return None, None, Blocker(
                code="SEMANTIC_DECISION_CACHE_INVALID",
                message="semantic decision cache could not be parsed",
                layer="operator",
                context={"path": str(cache_path), "error": str(exc)},
            )
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            return None, None, Blocker(
                code="SEMANTIC_DECISION_CACHE_INVALID",
                message="semantic decision cache must be a list of semantic decision rows",
                layer="operator",
                context={"path": str(cache_path)},
            )
        previous_report_path = config.run_dir / "semantic_adjudication_report.json"
        previous_report = read_json(previous_report_path) if previous_report_path.exists() else {}
        if isinstance(previous_report, dict):
            previous_hash = str(previous_report.get("semantic_cache_input_hash") or "")
            if previous_hash and previous_hash != cache_input_hash:
                return None, None, Blocker(
                    code="SEMANTIC_DECISION_CACHE_INPUT_HASH_MISMATCH",
                    message="semantic decision cache does not match current run input hash",
                    layer="operator",
                    context={"path": str(cache_path), "expected_hash": cache_input_hash, "cache_hash": previous_hash},
                )
            if int(previous_report.get("semantic_cache_unresolved_count") or previous_report.get("deepseek_batch_unresolved_count") or 0) > 0:
                return None, None, Blocker(
                    code="SEMANTIC_DECISION_CACHE_UNRESOLVED",
                    message="semantic decision cache contains unresolved provider-required issues",
                    layer="operator",
                    context={"path": str(cache_path)},
                )
        planner = SemanticDecisionsJsonPlanner(rows)
        setattr(planner, "semantic_decision_cache_used", True)
        setattr(planner, "commit_reused_semantic_cache", True)
        setattr(planner, "semantic_cache_input_hash", cache_input_hash)
        setattr(planner, "semantic_cache_issue_count", len(rows))
        setattr(planner, "semantic_cache_resolved_count", len(rows))
        setattr(planner, "semantic_cache_unresolved_count", 0)
        return planner, None, None
    if (
        config.semantic_decisions_json is None
        and config.mode == "write"
        and semantic_mode in {SemanticAdjudicationMode.AUTO, SemanticAdjudicationMode.DEEPSEEK}
    ):
        return None, None, None
    if config.semantic_decisions_json is None:
        provider = provider_factory() if semantic_mode in {SemanticAdjudicationMode.AUTO, SemanticAdjudicationMode.DEEPSEEK} else None
        if provider is not None:
            setattr(provider, "semantic_cache_input_hash", cache_input_hash)
            setattr(provider, "semantic_cache_issue_count", 0)
            setattr(provider, "semantic_cache_resolved_count", 0)
            setattr(provider, "semantic_cache_unresolved_count", 0)
        return None, provider, None
    try:
        rows = read_json(config.semantic_decisions_json)
    except Exception as exc:
        return None, None, Blocker(
            code="SEMANTIC_DECISIONS_JSON_INVALID",
            message="semantic decisions json could not be parsed",
            layer="operator",
            context={"path": str(config.semantic_decisions_json), "error": str(exc)},
        )
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return None, None, Blocker(
            code="SEMANTIC_DECISIONS_JSON_INVALID",
            message="semantic decisions json must be a list of objects",
            layer="operator",
            context={"path": str(config.semantic_decisions_json)},
        )
    return SemanticDecisionsJsonPlanner(rows), None, None


def _semantic_cache_input_hash(config: ArollV21OperatorConfig) -> str:
    digest = hashlib.sha256()
    digest.update(str(config.semantic_mode or "").encode("utf-8"))
    if config.input_json is not None and config.input_json.exists():
        digest.update(config.input_json.read_bytes())
    elif config.draft_dir is not None:
        digest.update(str(config.draft_dir).encode("utf-8"))
    return digest.hexdigest()
