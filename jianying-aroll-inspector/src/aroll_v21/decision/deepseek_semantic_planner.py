from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

from aroll_v21.decision.semantic_adjudication import (
    legacy_row_from_adjudication_decision,
    request_from_cluster,
)
from aroll_v21.decision.semantic_contracts import (
    SemanticAdjudicationDecision,
    SemanticAdjudicationDecisionType,
    SemanticAdjudicationProvider,
    SemanticAdjudicationRequest,
    semantic_contract_to_dict,
)
from aroll_v21.ir.models import RepeatCluster


FORBIDDEN_PROVIDER_FIELDS = {
    "source_start_us",
    "source_end_us",
    "target_start_us",
    "target_end_us",
    "material_id",
    "source_material_id",
    "source_segment_id",
    "segment_id",
    "final_timeline",
    "final_edl",
    "edl",
    "draft_content",
}

DEFAULT_RUNTIME_ROOT = Path(os.environ.get("AUTO_CLIP_RUNTIME_DIR") or (Path.home() / ".auto_clip_runtime"))
RUNTIME_DEEPSEEK_CONFIG_PATH = DEFAULT_RUNTIME_ROOT / "secrets" / "deepseek.local.yaml"
DEFAULT_DEEPSEEK_CONFIG_PATHS = (
    RUNTIME_DEEPSEEK_CONFIG_PATH,
    Path("config/deepseek.local.yaml"),
)


class DeepSeekSemanticProvider:
    provider_name = "deepseek_semantic_planner"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.deepseek.com/chat/completions",
        model: str = "deepseek-chat",
        timeout_s: int = 30,
        config_source: str = "",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout_s = timeout_s
        self.config_source = config_source

    def decide(self, requests: Sequence[SemanticAdjudicationRequest]) -> list[SemanticAdjudicationDecision]:
        if not requests:
            empty_decisions: list[SemanticAdjudicationDecision] = []
            return empty_decisions
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You adjudicate Chinese transcript semantic repeat issues. "
                        "Return JSON only. Do not output physical edit fields such as source_start_us, "
                        "source_end_us, target_start_us, target_end_us, material_id, segment_id, or draft content."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "schema": {
                                "decisions": [
                                    {
                                        "issue_id": "string",
                                        "decision": "keep_all|drop_left|drop_right|keep_longest_drop_others|drop_recommended|drop_aborted|repair_text|requires_human_review|no_decision",
                                        "reason": "string",
                                        "confidence": 0.0,
                                    }
                                ]
                            },
                            "requests": [semantic_contract_to_dict(request) for request in requests],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"DEEPSEEK_SEMANTIC_ADJUDICATION_FAILED: {exc}") from exc
        envelope = json.loads(raw)
        content = str(((envelope.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        decoded = json.loads(content)
        return [_decision_from_provider_row(row) for row in decoded.get("decisions") or [] if isinstance(row, dict)]


class DeepSeekSemanticPlannerAdapter:
    """Adapter from the new request/decision provider contract to the legacy cluster planner shape."""

    provider_name = "deepseek_semantic_planner"

    def __init__(self, provider: SemanticAdjudicationProvider) -> None:
        self.provider = provider
        self.rows: list[dict[str, Any]] = []
        self.request_rows: list[dict[str, Any]] = []
        self.decision_rows: list[dict[str, Any]] = []
        self.provider_called_count = 0
        self.deepseek_provider_configured = True
        self.deepseek_provider_config_source = str(getattr(provider, "config_source", "") or "")
        self.deepseek_provider_error = ""

    def decide(self, clusters: list[RepeatCluster]) -> list[dict[str, Any]]:
        requests = [request_from_cluster(cluster) for cluster in clusters]
        self.request_rows = [semantic_contract_to_dict(request) for request in requests]
        self.provider_called_count += len(requests)
        try:
            decisions = self.provider.decide(requests)
        except (RuntimeError, ValueError, KeyError, TypeError, OSError) as exc:
            self.deepseek_provider_error = str(exc)
            self.decision_rows = []
            self.rows = [
                {
                    "cluster_id": cluster.cluster_id,
                    "_blocker_code": "V21_SEMANTIC_ADJUDICATION_PROVIDER_FAILED",
                    "_severity": "write_blocker",
                    "_message": "DeepSeek provider failed while adjudicating semantic request",
                    "_provider_error": self.deepseek_provider_error,
                }
                for cluster in clusters
            ]
            return list(self.rows)
        self.deepseek_provider_error = ""
        decisions_by_issue = {decision.issue_id: decision for decision in decisions}
        rows: list[dict[str, Any]] = []
        for cluster in clusters:
            decision = decisions_by_issue.get(cluster.cluster_id)
            if decision is None:
                rows.append(
                    {
                        "cluster_id": cluster.cluster_id,
                        "_blocker_code": "SEMANTIC_DECISION_NOT_PROVIDED",
                        "_severity": "write_blocker",
                        "_message": "DeepSeek provider did not return a decision for this semantic request",
                    }
                )
                continue
            forbidden = _forbidden_provider_fields(semantic_contract_to_dict(decision))
            if forbidden:
                rows.append(
                    {
                        "cluster_id": cluster.cluster_id,
                        "_blocker_code": "DEEPSEEK_DECISION_HAS_PHYSICAL_FIELDS",
                        "_severity": "write_blocker",
                        "_message": "DeepSeek provider returned forbidden physical timeline/material fields",
                        "_forbidden_fields": forbidden,
                    }
                )
                continue
            rows.append(legacy_row_from_adjudication_decision(decision, cluster))
        self.decision_rows = [semantic_contract_to_dict(decision) for decision in decisions]
        self.rows = rows
        return rows


def deepseek_provider_from_env() -> DeepSeekSemanticProvider | None:
    return deepseek_provider_from_runtime_config()


def deepseek_provider_from_runtime_config() -> DeepSeekSemanticProvider | None:
    api_key = str(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_API_TOKEN") or "").strip()
    base_url = str(os.environ.get("DEEPSEEK_API_URL") or "").strip()
    model = str(os.environ.get("DEEPSEEK_MODEL") or "").strip()
    timeout_s = int(os.environ.get("DEEPSEEK_TIMEOUT_S") or 30)
    config = _load_deepseek_config_from_files()
    if config is not None and config.get("api_key"):
        return DeepSeekSemanticProvider(
            api_key=config["api_key"],
            base_url=_chat_completions_url(config.get("base_url", "")),
            model=config.get("model") or "deepseek-chat",
            timeout_s=timeout_s,
            config_source=config.get("config_source", ""),
        )
    if not api_key:
        no_provider: DeepSeekSemanticProvider | None = None
        return no_provider
    config_source = "env:DEEPSEEK_API_KEY" if os.environ.get("DEEPSEEK_API_KEY") else "env:DEEPSEEK_API_TOKEN"
    return DeepSeekSemanticProvider(
        api_key=api_key,
        base_url=_chat_completions_url(base_url or "https://api.deepseek.com/chat/completions"),
        model=model or "deepseek-chat",
        timeout_s=timeout_s,
        config_source=config_source,
    )


def deepseek_provider_from_config_file(path: Path) -> DeepSeekSemanticProvider | None:
    try:
        config = _parse_deepseek_yaml_config(path)
    except OSError:
        no_provider: DeepSeekSemanticProvider | None = None
        return no_provider
    if not config.get("api_key") or not config.get("base_url"):
        no_provider: DeepSeekSemanticProvider | None = None
        return no_provider
    return DeepSeekSemanticProvider(
        api_key=config["api_key"],
        base_url=_chat_completions_url(config["base_url"]),
        model=config.get("model") or "deepseek-chat",
        timeout_s=int(os.environ.get("DEEPSEEK_TIMEOUT_S") or 30),
        config_source=path.name,
    )


def _load_deepseek_config_from_files(paths: Sequence[Path] | None = None) -> dict[str, str] | None:
    candidate_paths = _deepseek_config_candidate_paths(paths)
    for path in candidate_paths:
        try:
            if _skip_runtime_secret_during_pytest(path):
                continue
            if not path.exists() or not path.is_file():
                continue
            config = _parse_deepseek_yaml_config(path)
        except OSError:
            continue
        if config.get("api_key") and config.get("base_url"):
            config["config_source"] = path.name
            return config
    no_config: dict[str, str] | None = None
    return no_config


def _skip_runtime_secret_during_pytest(path: Path) -> bool:
    if "pytest" not in sys.modules:
        return False
    try:
        return path.resolve() == RUNTIME_DEEPSEEK_CONFIG_PATH.resolve()
    except OSError:
        return False


def _deepseek_config_candidate_paths(paths: Sequence[Path] | None = None) -> list[Path]:
    use_default_paths = paths is None
    if paths is None:
        paths = DEFAULT_DEEPSEEK_CONFIG_PATHS
    candidates: list[Path] = []
    reference_env = str(os.environ.get("REFERENCE_VIDEO_DATA_CATCHER_DEEPSEEK_CONFIG_PATH") or "").strip()
    if reference_env:
        candidates.append(Path(reference_env))
    path_rows = list(paths)
    if use_default_paths:
        relative_paths = [path for path in path_rows if not path.is_absolute()]
        absolute_paths = [path for path in path_rows if path.is_absolute()]
        path_rows = relative_paths + absolute_paths
    candidates.extend(path_rows)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _parse_deepseek_yaml_config(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    lines = path.read_text("utf-8").splitlines()
    in_deepseek = False
    deepseek_indent = -1
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if stripped == "deepseek:":
            in_deepseek = True
            deepseek_indent = indent
            continue
        if in_deepseek and indent <= deepseek_indent and re.match(r"^[\w.-]+:", stripped):
            in_deepseek = False
        if in_deepseek and ":" in stripped:
            key, raw_value = stripped.split(":", 1)
            normalized_key = key.strip().replace("-", "_")
            if normalized_key in {"api_key", "base_url", "model"}:
                values[normalized_key] = _strip_yaml_scalar(raw_value)
    if not values.get("model"):
        models = [
            _strip_yaml_scalar(match.group(1))
            for match in re.finditer(r"(?m)^\s*model\s*:\s*(.+?)\s*$", "\n".join(lines))
        ]
        if "deepseek-chat" in models:
            values["model"] = "deepseek-chat"
        elif models:
            values["model"] = models[-1]
    return values


def _strip_yaml_scalar(value: str) -> str:
    text = value.strip()
    if "#" in text:
        text = text.split("#", 1)[0].strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1]
    return text.strip()


def _chat_completions_url(base_url: str) -> str:
    url = str(base_url or "").strip().rstrip("/")
    if not url:
        return "https://api.deepseek.com/chat/completions"
    if url.endswith("/chat/completions"):
        return url
    return url + "/chat/completions"


def _decision_from_provider_row(row: dict[str, Any]) -> SemanticAdjudicationDecision:
    decision = str(row.get("decision") or SemanticAdjudicationDecisionType.NO_DECISION.value)
    if decision not in {item.value for item in SemanticAdjudicationDecisionType}:
        decision = SemanticAdjudicationDecisionType.NO_DECISION.value
    return SemanticAdjudicationDecision(
        issue_id=str(row.get("issue_id") or row.get("cluster_id") or ""),
        decision=SemanticAdjudicationDecisionType(decision),
        reason=str(row.get("reason") or ""),
        confidence=float(row.get("confidence") or 0.0),
        provider_name=str(row.get("provider_name") or "deepseek_semantic_planner"),
        keep_unit_id=str(row.get("keep_unit_id") or ""),
        drop_unit_ids=[str(item) for item in row.get("drop_unit_ids") or [] if str(item)],
        unit_id=str(row.get("unit_id") or ""),
        drop_word_ids=[str(item) for item in row.get("drop_word_ids") or [] if str(item)],
        keep_word_ids=[str(item) for item in row.get("keep_word_ids") or [] if str(item)],
        repair_text=str(row.get("repair_text") or ""),
        requires_human_review=bool(row.get("requires_human_review")),
        metadata={key: value for key, value in row.items() if key not in {"issue_id", "cluster_id", "decision", "reason", "confidence"}},
    )


def _forbidden_provider_fields(value: Any) -> list[str]:
    found: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                text = str(key)
                if text in FORBIDDEN_PROVIDER_FIELDS:
                    found.add(text)
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return sorted(found)
