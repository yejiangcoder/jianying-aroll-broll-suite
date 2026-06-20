from __future__ import annotations

import gzip
import json
from dataclasses import MISSING, fields
from pathlib import Path
from typing import Any

from aroll_v21.engine import ArollRunInput
from aroll_v21.ingest.real_draft_adapter import RealDraftIngestAdapter, RealDraftIngestResult
from aroll_v21.ir.models import (
    Blocker,
    BlockerReport,
    CandidateEvidence,
    CanonicalSourceGraph,
    CanonicalWord,
    CaptionRenderUnit,
    DecisionPlan,
    EditUnit,
    FinalTimelineSegment,
    RepeatCluster,
    RunReport,
    SourceGraphInvariantReport,
    TakeDecision,
    UnitSplitPlan,
    dataclass_to_dict,
)
from aroll_v21.operator_config import ArollV21OperatorConfig, Mode, _normalize_report_profile


COMPACT_RUNTIME_REPORT_DROP_KEYS = {
    "post_write_actual_draft_audit",
    "staged_post_write_actual_draft_audit",
    "postwrite_actual_draft_audit",
    "actual_draft_data",
    "draft_data",
}


def read_json(path: Path) -> Any:
    if path.exists():
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return json.load(f)
        return json.loads(path.read_text("utf-8"))
    gzip_path = path.with_suffix(path.suffix + ".gz")
    if gzip_path.exists():
        with gzip.open(gzip_path, "rt", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(path.read_text("utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dataclass_to_dict(data), ensure_ascii=False, indent=2), "utf-8")


def write_profiled_report_json(path: Path, data: Any, report_profile: str) -> None:
    profile = _normalize_report_profile(report_profile)
    write_json(path, data if profile == "debug" else _compact_runtime_report(data))


def _compact_runtime_report(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    compact: dict[str, Any] = {}
    omitted: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        if key in COMPACT_RUNTIME_REPORT_DROP_KEYS:
            omitted[key] = {
                "omitted": True,
                "reason": "debug_payload_available_only_in_debug_report_profile",
                "approx_json_bytes": len(json.dumps(dataclass_to_dict(value), ensure_ascii=False)),
            }
            continue
        compact[key] = value
    if omitted:
        compact["compact_report_omitted_debug_payloads"] = omitted
    return compact


def _safe_read_json(path: Path) -> Any:
    try:
        return read_json(path)
    except (OSError, json.JSONDecodeError):
        return None


def _dataclass_from_dict(cls: Any, value: Any) -> Any:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError(f"{getattr(cls, '__name__', cls)} payload must be an object")
    kwargs: dict[str, Any] = {}
    for field in fields(cls):
        if field.name in value:
            kwargs[field.name] = value[field.name]
        elif field.default is not MISSING:
            kwargs[field.name] = field.default
        elif field.default_factory is not MISSING:  # type: ignore[attr-defined]
            kwargs[field.name] = field.default_factory()  # type: ignore[misc]
    return cls(**kwargs)


def _words(rows: Any) -> list[CanonicalWord]:
    return [_dataclass_from_dict(CanonicalWord, row) for row in rows or [] if isinstance(row, dict)]


def _edit_units(rows: Any) -> list[EditUnit]:
    return [_dataclass_from_dict(EditUnit, row) for row in rows or [] if isinstance(row, dict)]


def _source_graph(payload: Any) -> CanonicalSourceGraph | None:
    if not isinstance(payload, dict):
        return None
    invariant = _dataclass_from_dict(SourceGraphInvariantReport, payload.get("invariant_report") or {})
    return CanonicalSourceGraph(
        words=_words(payload.get("words") or []),
        edit_units=_edit_units(payload.get("edit_units") or []),
        subtitle_rows=list(payload.get("subtitle_rows") or []),
        source_materials=list(payload.get("source_materials") or []),
        source_segments=list(payload.get("source_segments") or []),
        text_materials=list(payload.get("text_materials") or []),
        text_segments=list(payload.get("text_segments") or []),
        invariant_report=invariant,
    )


def _repeat_clusters(rows: Any) -> list[RepeatCluster]:
    clusters: list[RepeatCluster] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        clusters.append(
            RepeatCluster(
                cluster_id=str(row.get("cluster_id") or ""),
                variants=_edit_units(row.get("variants") or []),
                repeat_type=row.get("repeat_type") or "exact_repeat",
                evidence=[
                    _dataclass_from_dict(CandidateEvidence, evidence)
                    for evidence in row.get("evidence") or []
                    if isinstance(evidence, dict)
                ],
                local_recommendation=row.get("local_recommendation"),
            )
        )
    return clusters


def _decision_plan(payload: Any) -> DecisionPlan | None:
    if not isinstance(payload, dict):
        return None
    return DecisionPlan(
        decisions=[_dataclass_from_dict(TakeDecision, row) for row in payload.get("decisions") or [] if isinstance(row, dict)],
        split_decisions=[
            _dataclass_from_dict(UnitSplitPlan, row)
            for row in payload.get("split_decisions") or []
            if isinstance(row, dict)
        ],
        blocked=bool(payload.get("blocked")),
        blockers=[_dataclass_from_dict(Blocker, row) for row in payload.get("blockers") or [] if isinstance(row, dict)],
        semantic_request_payloads=list(payload.get("semantic_request_payloads") or []),
        decision_trace=list(payload.get("decision_trace") or []),
        semantic_decision_rows=list(payload.get("semantic_decision_rows") or []),
        semantic_adjudication_report=dict(payload.get("semantic_adjudication_report") or {}),
        final_target_repeat_accepted_cluster_ids=list(payload.get("final_target_repeat_accepted_cluster_ids") or []),
        final_target_repeat_unresolved_cluster_ids=list(payload.get("final_target_repeat_unresolved_cluster_ids") or []),
        modifier_redundancy_accepted_cluster_ids=list(payload.get("modifier_redundancy_accepted_cluster_ids") or []),
        modifier_redundancy_unresolved_cluster_ids=list(payload.get("modifier_redundancy_unresolved_cluster_ids") or []),
        semantic_unresolved_count=int(payload.get("semantic_unresolved_count") or 0),
        requires_human_review=bool(payload.get("requires_human_review")),
        write_allowed=bool(payload.get("write_allowed", True)),
        dry_run_continued_for_discovery=bool(payload.get("dry_run_continued_for_discovery")),
    )


def _final_timeline(rows: Any) -> list[FinalTimelineSegment]:
    return [_dataclass_from_dict(FinalTimelineSegment, row) for row in rows or [] if isinstance(row, dict)]


def _captions(rows: Any) -> list[CaptionRenderUnit]:
    return [_dataclass_from_dict(CaptionRenderUnit, row) for row in rows or [] if isinstance(row, dict)]


def _blocker_report(payload: Any) -> BlockerReport:
    if not isinstance(payload, dict):
        return BlockerReport(blocked=True, blockers=[], summary={})
    return BlockerReport(
        blocked=bool(payload.get("blocked")),
        blockers=[_dataclass_from_dict(Blocker, row) for row in payload.get("blockers") or [] if isinstance(row, dict)],
        summary=dict(payload.get("summary") or {}),
    )


def _load_ready_run_report(ready_run_dir: Path) -> RunReport:
    return RunReport(
        status=str(read_json(ready_run_dir / "run_summary.json").get("status") or "blocked"),  # type: ignore[arg-type]
        source_graph=_source_graph(read_json(ready_run_dir / "source_graph.json")),
        repeat_clusters=_repeat_clusters(read_json(ready_run_dir / "repeat_clusters.json")),
        decision_plan=_decision_plan(read_json(ready_run_dir / "decision_plan.json")),
        final_timeline=_final_timeline(read_json(ready_run_dir / "final_timeline.json")),
        captions=_captions(read_json(ready_run_dir / "captions.json")),
        material_write_plan=dict(read_json(ready_run_dir / "material_write_plan.json") or {}),
        validator_report=dict(read_json(ready_run_dir / "validator_report.json") or {}),
        postwrite_report=dict(read_json(ready_run_dir / "prewrite_report.json") or {}),
        blocker_report=_blocker_report(read_json(ready_run_dir / "blocker_report.json")),
        decision_trace=list(read_json(ready_run_dir / "decision_trace.json") or []),
        resolved_template_map=dict((read_json(ready_run_dir / "writeback_report.json") or {}).get("resolved_template_map") or {}),
        source_binding_report=dict(read_json(ready_run_dir / "writeback_report.json") or {}),
    )


def read_postwrite_materials_json(path: Path) -> list[dict[str, Any]]:
    rows = read_json(path)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("postwrite materials json must be a list of material objects")
    return rows


def _run_input_from_real_draft_result(
    result: RealDraftIngestResult,
    *,
    mode: Mode,
    postwrite_mode: str,
    postwrite_materials: list[dict[str, Any]] | None = None,
) -> ArollRunInput:
    return ArollRunInput(
        draft_data=result.draft_data,
        word_timeline=result.word_timeline,
        subtitles=result.subtitles,
        source_segments=result.source_segments,
        source_materials=result.source_materials,
        text_materials=result.text_materials,
        text_segments=result.text_segments,
        postwrite_materials=postwrite_materials,
        ingest_blockers=result.blockers,
        ingest_metadata=result.metadata,
        postwrite_mode=postwrite_mode,  # type: ignore[arg-type]
        mode=mode,
    )


def load_run_input(
    config: ArollV21OperatorConfig,
    *,
    postwrite_mode: str = "auto",
    real_draft_result: RealDraftIngestResult | None = None,
) -> ArollRunInput:
    use_postwrite_materials = postwrite_mode == "actual_decrypt"
    if config.input_json is None:
        if config.draft_dir is None:
            raise RuntimeError("V21_INPUT_JSON_OR_DRAFT_DIR_REQUIRED")
        result = real_draft_result or RealDraftIngestAdapter(jy_draftc=config.jy_draftc).load(
            config.draft_dir,
            config.run_dir,
            word_timeline_json=config.word_timeline_json,
        )
        postwrite_materials = (
            read_postwrite_materials_json(config.postwrite_materials_json)
            if use_postwrite_materials and config.postwrite_materials_json is not None
            else None
        )
        return _run_input_from_real_draft_result(
            result,
            mode=config.mode,
            postwrite_mode=postwrite_mode,
            postwrite_materials=list(postwrite_materials or []) if postwrite_materials is not None else None,
        )
    payload = read_json(config.input_json)
    postwrite_materials = payload.get("postwrite_materials") if "postwrite_materials" in payload else None
    if use_postwrite_materials and config.postwrite_materials_json is not None:
        postwrite_materials = read_postwrite_materials_json(config.postwrite_materials_json)
    if not use_postwrite_materials:
        postwrite_materials = None
    return ArollRunInput(
        draft_data=payload.get("draft_data") or {},
        word_timeline=list(payload.get("word_timeline") or []),
        subtitles=list(payload.get("subtitles") or []),
        source_segments=list(payload.get("source_segments") or []) if "source_segments" in payload else None,
        source_materials=list(payload.get("source_materials") or []) if "source_materials" in payload else None,
        text_materials=list(payload.get("text_materials") or []) if "text_materials" in payload else None,
        text_segments=list(payload.get("text_segments") or []) if "text_segments" in payload else None,
        postwrite_materials=list(postwrite_materials or []) if postwrite_materials is not None else None,
        postwrite_mode=postwrite_mode,  # type: ignore[arg-type]
        mode=config.mode,
    )
