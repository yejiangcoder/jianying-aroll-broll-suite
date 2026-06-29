from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from aroll_v21.decision.semantic_adjudication import normalize_semantic_mode
from aroll_v21.engine import build_run_summary, write_run_artifacts
from aroll_v21.ingest.real_draft_adapter import RealDraftIngestResult
from aroll_v21.ir.models import Blocker, BlockerReport, RunReport, dataclass_to_dict
from aroll_v21.operator_config import ArollV21OperatorConfig, _effective_report_profile, _normalize_report_profile
from aroll_v21.operator_io import _safe_read_json, write_json


MINIMAL_ARTIFACTS = (
    "run_summary.json",
    "blocker_report.json",
    "artifact_manifest.json",
    "writeback_report.json",
)

DEBUG_ONLY_ARTIFACTS = (
    "run_report.json",
    "deepseek_batch_request.json",
    "deepseek_batch_response.json",
    "deepseek_batch_error.json",
)

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
    "final_timeline_quality_guard_report.json",
    "quality_gate_report.json",
    "blocker_report.json",
    "decision_trace.json",
    "run_summary.json",
    "writeback_report.json",
    "artifact_manifest.json",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(dataclass_to_dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_json(value: Any) -> str:
    return _sha256_bytes(_canonical_json_bytes(value))


def _hash_file(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        if path.exists() and path.is_file():
            return _sha256_bytes(path.read_bytes())
        gzip_path = path.with_suffix(path.suffix + ".gz")
        if gzip_path.exists() and gzip_path.is_file():
            return _sha256_bytes(gzip_path.read_bytes())
    except OSError:
        return ""
    return ""


def _code_version_hash() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    for relative in (
        "src/aroll_v21/operator.py",
        "src/aroll_v21/engine.py",
        "src/aroll_v21/cli.py",
        "scripts/uat_fresh_draft.ps1",
    ):
        path = repo_root / relative
        digest.update(relative.encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
    return digest.hexdigest()


def _pipeline_config_hash(config: ArollV21OperatorConfig) -> str:
    return _hash_json(
        {
            "semantic_mode": normalize_semantic_mode(config.semantic_mode).value,
            "word_timeline_json": str(config.word_timeline_json or ""),
        }
    )


def _draft_hashes_from_real_result(result: RealDraftIngestResult | None, config: ArollV21OperatorConfig) -> dict[str, str]:
    if result is None:
        input_hash = _hash_file(config.input_json)
        fingerprint = _hash_json(
            {
                "input_json": str(config.input_json or ""),
                "input_json_hash": input_hash,
                "semantic_mode": normalize_semantic_mode(config.semantic_mode).value,
            }
        )
        return {
            "draft_fingerprint": fingerprint,
            "draft_content_hash": input_hash,
            "template_hash": "",
            "timeline_hash": input_hash,
        }
    metadata = result.metadata or {}
    draft_content_path = Path(str(metadata.get("draft_content_path") or "")) if metadata.get("draft_content_path") else None
    template_path = Path(str(metadata.get("template_path") or "")) if metadata.get("template_path") else None
    draft_content_hash = _hash_file(draft_content_path) or _hash_json(result.draft_data)
    template_hash = _hash_file(template_path) or _hash_json(
        {
            "text_materials": result.text_materials,
            "text_segments": result.text_segments,
        }
    )
    timeline_hash = _hash_json(
        {
            "timeline_id": str(metadata.get("timeline_id") or ""),
            "source_segments": result.source_segments,
            "text_segments": result.text_segments,
            "word_timeline_count": len(result.word_timeline or []),
        }
    )
    fingerprint = _hash_json(
        {
            "draft_dir": str(config.draft_dir or ""),
            "draft_content_hash": draft_content_hash,
            "template_hash": template_hash,
            "timeline_hash": timeline_hash,
            "semantic_mode": normalize_semantic_mode(config.semantic_mode).value,
        }
    )
    return {
        "draft_fingerprint": fingerprint,
        "draft_content_hash": draft_content_hash,
        "template_hash": template_hash,
        "timeline_hash": timeline_hash,
    }


def _semantic_artifact_input_hash(run_dir: Path) -> str:
    payload = {
        "semantic_adjudication_report": _safe_read_json(run_dir / "semantic_adjudication_report.json") or {},
        "semantic_decision_cache": _safe_read_json(run_dir / "semantic_decision_cache.json") or [],
        "semantic_request_payloads": _safe_read_json(run_dir / "semantic_request_payloads.json") or [],
    }
    return _hash_json(payload)


def _artifact_hashes(run_dir: Path, names: list[str] | None = None) -> dict[str, str]:
    selected = names or sorted(
        path.name
        for pattern in ("*.json", "*.json.gz")
        for path in run_dir.glob(pattern)
        if path.is_file()
    )
    hashes: dict[str, str] = {}
    for name in selected:
        path = run_dir / name
        digest = _hash_file(path)
        if digest:
            hashes[name] = digest
    return hashes


def _stage_timing_defaults(timings: dict[str, float] | None = None) -> dict[str, float]:
    base = {
        "total_seconds": 0.0,
        "dry_run_seconds": 0.0,
        "planning_seconds": 0.0,
        "semantic_adjudication_seconds": 0.0,
        "quality_gate_seconds": 0.0,
        "report_write_seconds": 0.0,
        "writeback_seconds": 0.0,
        "postwrite_core_audit_seconds": 0.0,
        "postwrite_debug_audit_seconds": 0.0,
    }
    for key, value in (timings or {}).items():
        if key in base:
            base[key] = round(float(value or 0.0), 6)
    return base


def _run_metadata(config: ArollV21OperatorConfig, real_draft_result: RealDraftIngestResult | None) -> dict[str, Any]:
    hashes = _draft_hashes_from_real_result(real_draft_result, config)
    return {
        **hashes,
        "pipeline_config_hash": _pipeline_config_hash(config),
        "code_version_hash": _code_version_hash(),
        "requested_report_profile": _normalize_report_profile(config.report_profile),
    }


def _write_artifact_manifest(
    run_dir: Path,
    *,
    report_profile: str,
    summary: dict[str, Any],
    metadata: dict[str, Any],
) -> None:
    effective_profile = _normalize_report_profile(report_profile)
    metadata_payload = dict(metadata)
    requested_profile = _normalize_report_profile(
        str(metadata_payload.pop("requested_report_profile", metadata_payload.pop("report_profile", effective_profile)))
    )
    reuse_artifacts = [
        "source_graph.json",
        "final_timeline.json",
        "captions.json",
        "material_write_plan.json",
        "semantic_decision_cache.json",
        "semantic_adjudication_report.json",
        "quality_gate_report.json",
        "final_timeline_quality_guard_report.json",
        "prewrite_report.json",
        "writeback_report.json",
    ]
    manifest = {
        "artifact_manifest_version": 1,
        **metadata_payload,
        "report_profile": effective_profile,
        "requested_report_profile": requested_profile,
        "effective_report_profile": effective_profile,
        "run_dir": str(run_dir),
        "status": str(summary.get("status") or ""),
        "ready_for_disposable_write_pre_audit": bool(summary.get("READY_FOR_DISPOSABLE_WRITE_PRE_AUDIT")),
        "blocker_codes": list(summary.get("blocker_codes") or []),
        "artifact_files": sorted(
            str(path.relative_to(run_dir)).replace("\\", "/")
            for pattern in ("*.json", "*.json.gz", "*.md")
            for path in run_dir.rglob(pattern)
            if path.is_file() and path.name != "artifact_manifest.json"
        ),
        "artifact_hashes": _artifact_hashes(run_dir, reuse_artifacts),
        "reuse_required_artifacts": reuse_artifacts,
        "semantic_cache_input_hash": _semantic_artifact_input_hash(run_dir),
    }
    write_json(run_dir / "artifact_manifest.json", manifest)


def write_operator_artifacts(
    report: RunReport,
    run_dir: Path,
    *,
    write_status: str,
    commit_performed: bool,
    report_profile: str = "standard",
    runtime_metadata: dict[str, Any] | None = None,
    stage_timings: dict[str, float] | None = None,
) -> dict[str, Any]:
    profile = _normalize_report_profile(report_profile)
    effective_profile = _effective_report_profile(profile, report.status)
    report_write_started = time.monotonic()
    write_run_artifacts(report, run_dir, report_profile=effective_profile)
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
    metadata = dict(runtime_metadata or {})
    summary.update(metadata)
    summary["requested_report_profile"] = profile
    summary["effective_report_profile"] = effective_profile
    summary["report_profile"] = effective_profile
    timings = dict(stage_timings or {})
    timings["report_write_seconds"] = time.monotonic() - report_write_started
    summary.update(_stage_timing_defaults(timings))
    write_json(run_dir / "run_summary.json", summary)
    manifest_metadata = {
        **metadata,
        "requested_report_profile": profile,
        "effective_report_profile": effective_profile,
    }
    _write_artifact_manifest(run_dir, report_profile=effective_profile, summary=summary, metadata=manifest_metadata)
    return summary


def write_boundary_block(config: ArollV21OperatorConfig, blocker: Blocker) -> dict[str, Any]:
    config.run_dir.mkdir(parents=True, exist_ok=True)
    profile = _normalize_report_profile(config.report_profile)
    effective_profile = _effective_report_profile(profile, "blocked")
    for name in REQUIRED_ARTIFACTS:
        if effective_profile == "minimal" and name not in MINIMAL_ARTIFACTS:
            continue
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
        "deepseek_provider_configured": False,
        "deepseek_provider_called_count": 0,
        "deepseek_provider_error": "",
        "deepseek_batch_enabled": False,
        "deepseek_batch_request_count": 0,
        "deepseek_batch_attempt_count": 0,
        "deepseek_batch_retry_count": 0,
        "deepseek_batch_issue_count": 0,
        "deepseek_batch_resolved_count": 0,
        "deepseek_batch_unresolved_count": 0,
        "deepseek_batch_missing_issue_ids": [],
        "deepseek_batch_error": "",
        "commit_reused_semantic_cache": False,
        "semantic_cache_input_hash": str(blocker.context.get("semantic_cache_input_hash") or ""),
        "semantic_cache_issue_count": 0,
        "semantic_cache_resolved_count": 0,
        "semantic_cache_unresolved_count": 0,
        "blocker_count": 1,
        "blocker_codes": [blocker.code],
        "requested_report_profile": profile,
        "effective_report_profile": effective_profile,
        "report_profile": effective_profile,
        **_stage_timing_defaults(),
    }
    write_json(config.run_dir / "blocker_report.json", blocker_report)
    if effective_profile != "minimal":
        write_json(config.run_dir / "postwrite_report.json", postwrite_report)
    write_json(config.run_dir / "writeback_report.json", postwrite_report)
    write_json(config.run_dir / "run_summary.json", summary)
    _write_artifact_manifest(
        config.run_dir,
        report_profile=effective_profile,
        summary=summary,
        metadata={
            "pipeline_config_hash": _pipeline_config_hash(config),
            "code_version_hash": _code_version_hash(),
            "requested_report_profile": profile,
            "effective_report_profile": effective_profile,
        },
    )
    return summary
