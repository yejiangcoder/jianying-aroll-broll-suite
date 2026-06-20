from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from aroll_v21.artifact_manifest import (
    _hash_file,
    _semantic_artifact_input_hash,
    write_boundary_block,
    write_operator_artifacts,
)
from aroll_v21.ingest.real_draft_adapter import RealDraftIngestResult
from aroll_v21.ir.models import Blocker
from aroll_v21.operator_config import ArollV21OperatorConfig
from aroll_v21.operator_io import _load_ready_run_report, read_json, write_profiled_report_json
from aroll_v21.operator_summary import _annotate_postwrite_environment, _summary_blocker_codes, _writeback_blocked_report
from aroll_v21.writeback import RealDraftWriteback


def _ready_reuse_rejected(reason: str, *, context: dict[str, Any] | None = None) -> Blocker:
    return Blocker(
        code="READY_RUN_REUSE_REJECTED",
        message=f"READY dry-run cannot be reused for commit: {reason}",
        layer="operator",
        severity="fatal",
        context={"reason": reason, **dict(context or {})},
    )


def _validate_ready_run_dir(
    config: ArollV21OperatorConfig,
    *,
    current_metadata: dict[str, Any],
) -> Blocker | None:
    ready_run_dir = Path(config.ready_run_dir or "")
    if not ready_run_dir.exists() or not ready_run_dir.is_dir():
        return _ready_reuse_rejected("ready_run_dir_missing", context={"ready_run_dir": str(ready_run_dir)})
    summary_path = ready_run_dir / "run_summary.json"
    manifest_path = ready_run_dir / "artifact_manifest.json"
    if not summary_path.exists() or not manifest_path.exists():
        return _ready_reuse_rejected(
            "ready_run_missing_summary_or_manifest",
            context={"summary_path": str(summary_path), "manifest_path": str(manifest_path)},
        )
    summary = read_json(summary_path)
    manifest = read_json(manifest_path)
    if not isinstance(summary, dict) or not isinstance(manifest, dict):
        return _ready_reuse_rejected("ready_run_summary_or_manifest_invalid")
    blocker_codes = _summary_blocker_codes(summary)
    if str(summary.get("status") or "") != "ok":
        return _ready_reuse_rejected("ready_run_status_not_ok", context={"status": str(summary.get("status") or "")})
    if not bool(summary.get("READY_FOR_DISPOSABLE_WRITE_PRE_AUDIT")):
        return _ready_reuse_rejected("ready_run_not_ready")
    if blocker_codes:
        return _ready_reuse_rejected("ready_run_has_blockers", context={"blocker_codes": blocker_codes})
    for key in ("draft_fingerprint", "draft_content_hash", "template_hash", "timeline_hash"):
        expected = str(manifest.get(key) or summary.get(key) or "")
        current = str(current_metadata.get(key) or "")
        if expected and current and expected != current:
            return _ready_reuse_rejected(
                f"{key}_mismatch",
                context={"field": key, "ready_value": expected, "current_value": current},
            )
    for key in ("pipeline_config_hash", "code_version_hash"):
        expected = str(manifest.get(key) or summary.get(key) or "")
        current = str(current_metadata.get(key) or "")
        if expected and current and expected != current:
            return _ready_reuse_rejected(
                f"{key}_mismatch",
                context={"field": key, "ready_value": expected, "current_value": current},
            )
    recorded_semantic_hash = str(manifest.get("semantic_cache_input_hash") or summary.get("semantic_cache_input_hash") or "")
    current_semantic_hash = _semantic_artifact_input_hash(ready_run_dir)
    if recorded_semantic_hash and recorded_semantic_hash != current_semantic_hash:
        return _ready_reuse_rejected(
            "semantic_cache_input_hash_mismatch",
            context={"ready_value": recorded_semantic_hash, "current_value": current_semantic_hash},
        )
    artifact_hashes = manifest.get("artifact_hashes") or {}
    if not isinstance(artifact_hashes, dict):
        return _ready_reuse_rejected("artifact_hashes_invalid")
    for name in manifest.get("reuse_required_artifacts") or []:
        artifact = ready_run_dir / str(name)
        artifact_hash = _hash_file(artifact)
        if not artifact_hash:
            return _ready_reuse_rejected("required_reuse_artifact_missing", context={"artifact": str(artifact)})
        expected_hash = str(artifact_hashes.get(str(name)) or "")
        if expected_hash and expected_hash != artifact_hash:
            return _ready_reuse_rejected("required_reuse_artifact_hash_mismatch", context={"artifact": str(artifact)})
    final_timeline = read_json(ready_run_dir / "final_timeline.json")
    captions = read_json(ready_run_dir / "captions.json")
    material_write_plan = read_json(ready_run_dir / "material_write_plan.json")
    writeback_report = read_json(ready_run_dir / "writeback_report.json")
    if not isinstance(final_timeline, list) or not final_timeline:
        return _ready_reuse_rejected("final_timeline_missing_or_empty")
    if not isinstance(captions, list) or not captions:
        return _ready_reuse_rejected("captions_missing_or_empty")
    if not isinstance(material_write_plan, dict):
        return _ready_reuse_rejected("material_write_plan_invalid")
    plan_segments = material_write_plan.get("segments") or []
    plan_materials = material_write_plan.get("materials") or []
    if len(plan_segments) != len(captions) or len(plan_materials) != len(captions):
        return _ready_reuse_rejected(
            "material_write_plan_caption_count_mismatch",
            context={
                "caption_count": len(captions),
                "segment_count": len(plan_segments),
                "material_count": len(plan_materials),
            },
        )
    resolved_template_map = (writeback_report or {}).get("resolved_template_map") if isinstance(writeback_report, dict) else {}
    if not isinstance(resolved_template_map, dict) or len(resolved_template_map) != len(final_timeline):
        return _ready_reuse_rejected(
            "resolved_template_map_incomplete",
            context={
                "resolved_template_map_count": len(resolved_template_map) if isinstance(resolved_template_map, dict) else 0,
                "final_timeline_count": len(final_timeline),
            },
        )
    return None


def _commit_from_ready_run_dir(
    config: ArollV21OperatorConfig,
    *,
    real_draft_result: RealDraftIngestResult,
    runtime_metadata: dict[str, Any],
    stage_timings: dict[str, float],
    writeback_cls=RealDraftWriteback,
) -> dict[str, Any]:
    if config.draft_dir is None:
        return write_boundary_block(
            config,
            _ready_reuse_rejected("commit_from_ready_run_requires_draft_dir"),
        )
    if not config.commit:
        return write_boundary_block(
            config,
            _ready_reuse_rejected("commit_from_ready_run_requires_commit_flag"),
        )
    rejection = _validate_ready_run_dir(config, current_metadata=runtime_metadata)
    if rejection is not None:
        return write_boundary_block(config, rejection)
    ready_run_dir = Path(config.ready_run_dir or "")
    try:
        ready_report = _load_ready_run_report(ready_run_dir)
    except Exception as exc:
        return write_boundary_block(
            config,
            _ready_reuse_rejected("ready_run_artifacts_could_not_be_loaded", context={"error": str(exc)}),
        )
    if ready_report.status != "ok":
        return write_boundary_block(
            config,
            _ready_reuse_rejected("ready_run_report_status_not_ok", context={"status": ready_report.status}),
        )
    ready_report.postwrite_report.update(
        {
            "commit_from_ready_run_dir": True,
            "ready_run_dir": str(ready_run_dir),
            "planning_reused_from_ready_run": True,
            "deepseek_reused_from_ready_run": True,
        }
    )
    if config.simulate_write:
        return write_operator_artifacts(
            ready_report,
            config.run_dir,
            write_status="ready_run_reused_simulated_write_no_commit",
            commit_performed=False,
            report_profile=config.report_profile,
            runtime_metadata=runtime_metadata,
            stage_timings=stage_timings,
        )
    writeback_started = time.monotonic()
    writeback_result = writeback_cls(jy_draftc=config.jy_draftc).commit(
        draft_dir=config.draft_dir,
        run_dir=config.run_dir,
        real_draft_result=real_draft_result,
        run_report=ready_report,
        sacrificial_write_override_used=bool(config.allow_sacrificial_write_without_postwrite_decrypt),
    )
    stage_timings["writeback_seconds"] = time.monotonic() - writeback_started
    stage_timings["postwrite_core_audit_seconds"] = stage_timings["writeback_seconds"]
    write_profiled_report_json(config.run_dir / "writeback_report.json", writeback_result.report, config.report_profile)
    if not writeback_result.success:
        blocked = _writeback_blocked_report(ready_report, writeback_result)
        _annotate_postwrite_environment(
            blocked,
            config,
            sacrificial_override_used=bool(config.allow_sacrificial_write_without_postwrite_decrypt),
            writeback_report=writeback_result.report,
        )
        return write_operator_artifacts(
            blocked,
            config.run_dir,
            write_status="blocked_ready_run_reuse_writeback_failed",
            commit_performed=False,
            report_profile=config.report_profile,
            runtime_metadata=runtime_metadata,
            stage_timings=stage_timings,
        )
    _annotate_postwrite_environment(
        ready_report,
        config,
        sacrificial_override_used=bool(config.allow_sacrificial_write_without_postwrite_decrypt),
        writeback_report=writeback_result.report,
    )
    return write_operator_artifacts(
        ready_report,
        config.run_dir,
        write_status="committed_from_ready_run_without_replanning",
        commit_performed=bool(writeback_result.success),
        report_profile=config.report_profile,
        runtime_metadata=runtime_metadata,
        stage_timings=stage_timings,
    )
