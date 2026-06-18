from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from aroll_v21.decision import DeterministicBaselinePolicy, SemanticDecisionsJsonPlanner
from aroll_v21.decision.deepseek_semantic_planner import (
    deepseek_provider_from_runtime_config as deepseek_provider_from_env,
)
from aroll_v21.decision.semantic_adjudication import normalize_semantic_mode, severity_for_cluster
from aroll_v21.decision.semantic_contracts import SemanticAdjudicationMode
from aroll_v21.engine import ArollEngine, ArollRunInput, build_run_summary, write_run_artifacts
from aroll_v21.ingest.real_draft_adapter import RealDraftIngestAdapter, RealDraftIngestResult
from aroll_v21.ir.models import Blocker, BlockerReport, RunReport, dataclass_to_dict
from aroll_v21.writeback import RealDraftWriteback, WritebackResult
from aroll_v21.writeback.dynamic_source_binding_preflight import DynamicSourceBindingPreflight


Mode = Literal["dry-run", "write", "verify-only"]


@dataclass(frozen=True)
class ArollV21OperatorConfig:
    mode: Mode
    run_dir: Path
    input_json: Path | None = None
    draft_dir: Path | None = None
    jy_draftc: Path | None = None
    word_timeline_json: Path | None = None
    semantic_decisions_json: Path | None = None
    postwrite_materials_json: Path | None = None
    simulate_write: bool = False
    commit: bool = False
    allow_sacrificial_write_without_postwrite_decrypt: bool = False
    semantic_mode: str = "auto"


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


REQUIRED_ARTIFACTS = (
    "source_graph.json",
    "edit_units.json",
    "repeat_clusters.json",
    "decision_plan.json",
    "semantic_request_payloads.json",
    "semantic_decisions.json",
    "semantic_decisions.resolved.json",
    "semantic_decision_cache.json",
    "semantic_adjudication_report.json",
    "deepseek_decisions.json",
    "local_policy_decisions.json",
    "final_timeline.json",
    "final_edl.json",
    "captions.json",
    "canonical_caption_template.json",
    "material_write_plan.json",
    "validator_report.json",
    "postwrite_report.json",
    "quality_gate_report.json",
    "blocker_report.json",
    "decision_trace.json",
    "run_summary.json",
    "run_report.json",
    "writeback_report.json",
)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dataclass_to_dict(data), ensure_ascii=False, indent=2), "utf-8")


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


def write_operator_artifacts(report: RunReport, run_dir: Path, *, write_status: str, commit_performed: bool) -> dict[str, Any]:
    write_run_artifacts(report, run_dir)
    writeback_path = run_dir / "writeback_report.json"
    if not writeback_path.exists():
        write_json(
            writeback_path,
            {
                "writeback_attempted": False,
                "writeback_success": False,
                "WRITE_SUCCESS": False,
                "ENCRYPT_SUCCESS": False,
            },
        )
    summary = build_run_summary(report, write_status=write_status, commit_performed=commit_performed)
    semantic_report = report.decision_plan.semantic_adjudication_report if report.decision_plan else {}
    summary["deepseek_provider_config_source"] = str(semantic_report.get("deepseek_provider_config_source") or "")
    write_json(run_dir / "run_summary.json", summary)
    return summary


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


SOURCE_TEMPLATE_AVAILABILITY_BLOCKERS = {
    "V21_WRITEBACK_CURRENT_SOURCE_TEMPLATE_INDEX_EMPTY",
    "V21_WRITEBACK_SOURCE_SEGMENT_TEMPLATE_MISSING",
    "V21_WRITEBACK_SOURCE_SEGMENT_TEMPLATE_AMBIGUOUS",
    "V21_DYNAMIC_BINDING_CANDIDATE_INDEX_EMPTY",
    "V21_DYNAMIC_BINDING_MISSING",
    "V21_DYNAMIC_BINDING_AMBIGUOUS",
    "V21_DYNAMIC_BINDING_REQUIRED",
    "V21_DYNAMIC_BINDING_FORBIDS_LOGICAL_SOURCE_SEGMENT_ID",
    "V21_DYNAMIC_BINDING_PRIMARY_VIDEO_MISSING",
    "V21_DYNAMIC_BINDING_PRIMARY_VIDEO_AMBIGUOUS",
    "V21_DYNAMIC_BINDING_DURATION_UNPARSEABLE",
    "V21_WRITEBACK_UNSUPPORTED_SPEED_MAPPING",
    "V21_WRITEBACK_UNSUPPORTED_COMPLEX_EFFECT_TRACK",
    "V21_WRITEBACK_ROOT_MIRROR_DETECTION_FAILED",
}


def _preflight_source_segment_templates(
    report: RunReport,
    config: ArollV21OperatorConfig,
    real_draft_result: RealDraftIngestResult | None,
) -> RunReport:
    if report.status != "ok" or config.input_json is not None or config.draft_dir is None or real_draft_result is None:
        return report
    root_mirror_func = None
    if config.jy_draftc is not None and (
        not isinstance(RealDraftWriteback, type) or str(getattr(RealDraftWriteback, "__module__", "")).startswith("aroll_v21")
    ):
        writeback_backend = RealDraftWriteback(jy_draftc=config.jy_draftc)
        root_mirror_func = getattr(writeback_backend, "root_mirror_func", None)
    root_mirror_func = root_mirror_func or (lambda *_args: False)
    writeback_result = DynamicSourceBindingPreflight(
        jy_draftc=config.jy_draftc,
        root_mirror_func=root_mirror_func,
    ).preflight(
        draft_dir=config.draft_dir,
        real_draft_result=real_draft_result,
        run_report=report,
        run_dir=config.run_dir,
    )
    write_json(config.run_dir / "writeback_report.json", writeback_result.report)
    if not writeback_result.success:
        blocked = _writeback_blocked_report(report, writeback_result)
        _annotate_postwrite_environment(blocked, config, writeback_report=writeback_result.report)
        return blocked
    bound_report = replace(
        report,
        resolved_template_map=dict(writeback_result.report.get("resolved_template_map") or {}),
        source_binding_report=dict(writeback_result.report),
    )
    _annotate_postwrite_environment(bound_report, config, writeback_report=writeback_result.report)
    return bound_report


def _blocked_by_source_template_availability(report: RunReport) -> bool:
    blockers = report.blocker_report.blockers if report.blocker_report else []
    return any(blocker.code in SOURCE_TEMPLATE_AVAILABILITY_BLOCKERS for blocker in blockers)


def write_boundary_block(config: ArollV21OperatorConfig, blocker: Blocker) -> dict[str, Any]:
    config.run_dir.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_ARTIFACTS:
        if name in {"blocker_report.json", "run_summary.json", "postwrite_report.json"}:
            continue
        list_artifacts = {
            "edit_units.json",
            "final_edl.json",
            "semantic_decisions.resolved.json",
            "semantic_decision_cache.json",
        }
        write_json(config.run_dir / name, [] if name.endswith("s.json") or name in list_artifacts else {})
    blocker_report = BlockerReport(blocked=True, blockers=[blocker], summary={"mode": config.mode})
    postwrite_report = {
        "postwrite_mode": "unavailable",
        "postwrite_decrypt_ok": False,
        "postwrite_material_gate_ok": False,
        "block_reason": blocker.code,
    }
    summary = {
        "status": "blocked",
        "mode": config.mode,
        "write_status": "blocked",
        "commit_performed": False,
        "postwrite_mode": "unavailable",
        "postwrite_decrypt_ok": False,
        "postwrite_style_gate_ok": False,
        "commit_only_after_all_validators": True,
        "blocker_count": 1,
        "blocker_codes": [blocker.code],
    }
    write_json(config.run_dir / "blocker_report.json", blocker_report)
    write_json(config.run_dir / "postwrite_report.json", postwrite_report)
    write_json(config.run_dir / "run_summary.json", summary)
    return summary


def _semantic_decisions_planner(config: ArollV21OperatorConfig) -> tuple[Any | None, Any | None, Blocker | None]:
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
        planner = SemanticDecisionsJsonPlanner(rows)
        setattr(planner, "semantic_decision_cache_used", True)
        return planner, None, None
    if config.semantic_decisions_json is None:
        provider = deepseek_provider_from_env() if semantic_mode in {SemanticAdjudicationMode.AUTO, SemanticAdjudicationMode.DEEPSEEK} else None
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


def _postwrite_materials_config_blocker(config: ArollV21OperatorConfig) -> Blocker | None:
    if config.postwrite_materials_json is None:
        return None
    try:
        read_postwrite_materials_json(config.postwrite_materials_json)
    except Exception as exc:
        return Blocker(
            code="POSTWRITE_MATERIALS_JSON_INVALID",
            message="postwrite materials json could not be parsed as a list of material objects",
            layer="operator",
            context={"path": str(config.postwrite_materials_json), "error": str(exc)},
        )
    return None


def run_operator(config: ArollV21OperatorConfig) -> dict[str, Any]:
    config.run_dir.mkdir(parents=True, exist_ok=True)
    if config.input_json is not None and config.draft_dir is not None:
        return write_boundary_block(
            config,
            Blocker(
                code="REAL_DRAFT_INPUT_JSON_NOT_ALLOWED_WITH_DRAFT_DIR",
                message="sanitized input_json cannot be used to masquerade as a real draft ingest",
                layer="operator",
                context={"draft_dir": str(config.draft_dir), "input_json": str(config.input_json)},
            ),
        )
    if config.input_json is None and config.draft_dir is None:
        return write_boundary_block(
            config,
            Blocker(
                code="REAL_DRAFT_DIR_REQUIRED",
                message="pass a disposable DraftDir for V21 real ingest or omit DraftDir and pass input_json for offline fixture mode",
                layer="operator",
            ),
        )

    postwrite_materials_blocker = _postwrite_materials_config_blocker(config)
    if postwrite_materials_blocker is not None:
        return write_boundary_block(config, postwrite_materials_blocker)

    semantic_planner, semantic_provider, semantic_planner_blocker = _semantic_decisions_planner(config)
    if semantic_planner_blocker is not None:
        return write_boundary_block(config, semantic_planner_blocker)
    engine = ArollEngine(
        deepseek_planner=semantic_planner,
        semantic_provider=semantic_provider,
        semantic_mode=normalize_semantic_mode(config.semantic_mode).value,
    )
    real_draft_result: RealDraftIngestResult | None = None
    if config.input_json is None and config.draft_dir is not None:
        real_draft_result = RealDraftIngestAdapter(jy_draftc=config.jy_draftc).load(
            config.draft_dir,
            config.run_dir,
            word_timeline_json=config.word_timeline_json,
        )
        if real_draft_result.blockers and not real_draft_result.draft_data:
            return write_boundary_block(config, real_draft_result.blockers[0])

    if config.mode == "dry-run":
        report = engine.run(load_run_input(config, postwrite_mode="simulated", real_draft_result=real_draft_result))
        report = _preflight_source_segment_templates(report, config, real_draft_result)
        if report.postwrite_report and config.input_json is None and config.draft_dir is not None and real_draft_result is not None:
            write_json(config.run_dir / "prewrite_report.json", report.postwrite_report)
        write_status = "blocked_by_prewrite_source_template_availability" if _blocked_by_source_template_availability(report) else "dry_run_no_write"
        return write_operator_artifacts(report, config.run_dir, write_status=write_status, commit_performed=False)

    if config.mode == "verify-only":
        postwrite_mode = "actual_decrypt" if config.postwrite_materials_json is not None else "unavailable"
        report = engine.run(load_run_input(config, postwrite_mode=postwrite_mode, real_draft_result=real_draft_result))
        write_status = "verify_only_passed" if report.status == "ok" else "verify_only_blocked"
        return write_operator_artifacts(report, config.run_dir, write_status=write_status, commit_performed=False)

    prewrite_report = engine.run(load_run_input(config, postwrite_mode="simulated", real_draft_result=real_draft_result))
    prewrite_report = _preflight_source_segment_templates(prewrite_report, config, real_draft_result)
    write_json(config.run_dir / "prewrite_report.json", prewrite_report.postwrite_report)
    if prewrite_report.status != "ok":
        write_status = (
            "blocked_by_prewrite_source_template_availability"
            if _blocked_by_source_template_availability(prewrite_report)
            else "blocked_by_prewrite_validators"
        )
        return write_operator_artifacts(prewrite_report, config.run_dir, write_status=write_status, commit_performed=False)

    if config.simulate_write:
        simulated = engine.run(load_run_input(config, postwrite_mode="simulated_write", real_draft_result=real_draft_result))
        return write_operator_artifacts(simulated, config.run_dir, write_status="simulated_write_no_commit", commit_performed=False)

    actual_postwrite_available = config.postwrite_materials_json is not None
    if not actual_postwrite_available:
        if config.allow_sacrificial_write_without_postwrite_decrypt:
            if config.draft_dir is None:
                return write_boundary_block(
                    config,
                    Blocker(
                        code="SACRIFICIAL_WRITE_REQUIRES_EXPLICIT_DRAFT_DIR",
                        message="sacrificial write override requires an explicit DraftDir and cannot run from input_json",
                        layer="operator",
                        context={"input_json": str(config.input_json) if config.input_json else ""},
                    ),
                )
            if not config.commit:
                return write_boundary_block(
                    config,
                    Blocker(
                        code="SACRIFICIAL_WRITE_REQUIRES_COMMIT_FLAG",
                        message="sacrificial write override requires explicit commit intent",
                        layer="operator",
                        context={"draft_dir": str(config.draft_dir)},
                    ),
                )
            assert real_draft_result is not None
            writeback_result = RealDraftWriteback(jy_draftc=config.jy_draftc).commit(
                draft_dir=config.draft_dir,
                run_dir=config.run_dir,
                real_draft_result=real_draft_result,
                run_report=prewrite_report,
                sacrificial_write_override_used=True,
            )
            write_json(config.run_dir / "writeback_report.json", writeback_result.report)
            if not writeback_result.success:
                blocked = _writeback_blocked_report(prewrite_report, writeback_result)
                _annotate_postwrite_environment(blocked, config, sacrificial_override_used=True, writeback_report=writeback_result.report)
                return write_operator_artifacts(
                    blocked,
                    config.run_dir,
                    write_status="blocked_writeback_failed",
                    commit_performed=False,
                )
            sacrificial = engine.run(
                load_run_input(
                    config,
                    postwrite_mode="skipped_for_sacrificial_draft",
                    real_draft_result=real_draft_result,
                )
            )
            _annotate_postwrite_environment(
                sacrificial,
                config,
                sacrificial_override_used=True,
                writeback_report=writeback_result.report,
            )
            if sacrificial.status == "ok":
                return write_operator_artifacts(
                    sacrificial,
                    config.run_dir,
                    write_status="committed_sacrificial_without_postwrite_decrypt",
                    commit_performed=True,
                )
            return write_operator_artifacts(
                sacrificial,
                config.run_dir,
                write_status="blocked_sacrificial_write_preconditions_failed",
                commit_performed=False,
            )
        unavailable = engine.run(load_run_input(config, postwrite_mode="unavailable", real_draft_result=real_draft_result))
        _annotate_postwrite_environment(unavailable, config)
        return write_operator_artifacts(unavailable, config.run_dir, write_status="blocked_actual_decrypt_unavailable", commit_performed=False)

    verified = engine.run(load_run_input(config, postwrite_mode="actual_decrypt", real_draft_result=real_draft_result))
    if verified.status != "ok":
        return write_operator_artifacts(verified, config.run_dir, write_status="blocked_by_postwrite_verification", commit_performed=False)
    verified = replace(
        verified,
        resolved_template_map=dict(prewrite_report.resolved_template_map or {}),
        source_binding_report=dict(prewrite_report.source_binding_report or {}),
    )

    if not config.commit:
        return write_operator_artifacts(verified, config.run_dir, write_status="verified_no_commit_flag", commit_performed=False)

    if config.draft_dir is None or real_draft_result is None:
        return write_boundary_block(
            config,
            Blocker(
                code="REAL_WRITE_REQUIRES_EXPLICIT_DRAFT_DIR",
                message="V21 real writeback requires an explicit DraftDir and real draft ingest result",
                layer="operator",
                context={"input_json": str(config.input_json) if config.input_json else ""},
            ),
        )
    writeback_result = RealDraftWriteback(jy_draftc=config.jy_draftc).commit(
        draft_dir=config.draft_dir,
        run_dir=config.run_dir,
        real_draft_result=real_draft_result,
        run_report=verified,
        sacrificial_write_override_used=False,
    )
    write_json(config.run_dir / "writeback_report.json", writeback_result.report)
    if not writeback_result.success:
        blocked = _writeback_blocked_report(verified, writeback_result)
        _annotate_postwrite_environment(blocked, config, writeback_report=writeback_result.report)
        return write_operator_artifacts(blocked, config.run_dir, write_status="blocked_writeback_failed", commit_performed=False)
    _annotate_postwrite_environment(verified, config, writeback_report=writeback_result.report)
    return write_operator_artifacts(verified, config.run_dir, write_status="committed_after_postwrite_verification", commit_performed=True)
