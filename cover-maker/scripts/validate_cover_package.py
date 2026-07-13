from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from cover_contract import (
    CANDIDATE_VARIANTS,
    CANVAS_SIZES,
    CoverContractError,
    MANIFEST_SCHEMA_VERSION,
    RENDERER_VERSION,
    ensure_exact_image,
    load_json,
    render_cover_image,
    sha256_file,
    validate_job,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail-closed validation for deterministic local cover packages."
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--current-draft", default="")
    return parser.parse_args()


def normalized_path(value: str) -> str:
    return os.path.normcase(str(Path(value).resolve()))


def require_text(payload: dict[str, Any], field: str) -> str:
    value = str(payload.get(field) or "").strip()
    if not value:
        raise CoverContractError(f"manifest field is required: {field}")
    return value


def validate_state_binding(manifest: dict[str, Any], state_path: Path) -> dict[str, Any]:
    state = load_json(state_path)
    if manifest.get("workflow_mode") != "standard_pipeline":
        raise CoverContractError(
            "Only standard_pipeline cover packages may update current_draft. "
            "old_video_recovery packages remain project-local."
        )
    expected_name = require_text(manifest, "draft_name")
    actual_name = str(state.get("draft_name") or "")
    if actual_name != expected_name:
        raise CoverContractError(
            f"current_draft draft_name mismatch: manifest={expected_name!r} state={actual_name!r}"
        )

    expected_dir = require_text(manifest, "draft_dir")
    actual_dir = str(state.get("draft_dir") or "")
    if not actual_dir or normalized_path(actual_dir) != normalized_path(expected_dir):
        raise CoverContractError(
            f"current_draft draft_dir mismatch: manifest={expected_dir!r} state={actual_dir!r}"
        )
    if not bool(state.get("aroll_qc_passed")):
        raise CoverContractError("current_draft.aroll_qc_passed must be true")

    broll_write = state.get("broll_write")
    if not isinstance(broll_write, dict) or broll_write.get("status") != "passed":
        raise CoverContractError("current_draft.broll_write.status must be passed")
    if not str(broll_write.get("commander_qc_passed_at") or ""):
        raise CoverContractError("current_draft.broll_write.commander_qc_passed_at is required")

    enhancement_status = str(state.get("enhancement_decision_status") or "").lower()
    if not any(token in enhancement_status for token in ("resolved", "passed", "skipped")):
        raise CoverContractError(
            "current_draft.enhancement_decision_status must be resolved, passed, or skipped"
        )

    state_broll = str(state.get("broll_design_md_path") or "")
    manifest_broll = str(manifest.get("source_broll_design_path") or "")
    if state_broll and manifest_broll and normalized_path(state_broll) != normalized_path(manifest_broll):
        raise CoverContractError(
            "cover package source_broll_design_path does not match current_draft.broll_design_md_path"
        )
    return state


def validate_package(manifest_path: Path, current_draft_path: Path | None) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise CoverContractError(
            f"schema_version must be {MANIFEST_SCHEMA_VERSION}; legacy or ad hoc manifests are blocked"
        )
    if manifest.get("renderer_version") != RENDERER_VERSION:
        raise CoverContractError(
            f"renderer_version must be {RENDERER_VERSION}, got {manifest.get('renderer_version')!r}"
        )
    if manifest.get("ready_for_commander_qc") is not True:
        raise CoverContractError("ready_for_commander_qc must be true before candidate promotion")
    if manifest.get("commander_output_dir_confirmed") is not True:
        raise CoverContractError("commander_output_dir_confirmed must be true")
    if manifest.get("status") not in {"ready_for_commander_qc", "commander_qc_passed"}:
        raise CoverContractError(
            f"manifest status is not promotable: {manifest.get('status')!r}"
        )

    required = (
        "job_id",
        "project_id",
        "workflow_mode",
        "cover_job_path",
        "source_user_script_path",
        "video_title",
        "cover_title",
        "cover_title_source_location",
        "cover_title_design_reason",
        "cover_type",
        "template_set_id",
        "subject_source_path",
        "subject_sha256",
        "font_file",
        "font_sha256",
        "cover_prompt_package_path",
        "output_root",
    )
    for field in required:
        require_text(manifest, field)

    job_path = Path(str(manifest["cover_job_path"])).resolve()
    raw_job = load_json(job_path)
    job, profile = validate_job(raw_job)
    exact_fields = (
        "job_id",
        "project_id",
        "workflow_mode",
        "draft_name",
        "draft_dir",
        "source_broll_design_path",
        "source_user_script_path",
        "video_title",
        "cover_title",
        "cover_title_source_location",
        "cover_title_design_reason",
        "cover_type",
        "template_set_id",
        "subject_source_path",
        "subject_sha256",
        "font_file",
        "font_sha256",
    )
    for field in exact_fields:
        if str(manifest.get(field) or "") != str(job.get(field) or ""):
            raise CoverContractError(
                f"manifest/job mismatch for {field}: manifest={manifest.get(field)!r} job={job.get(field)!r}"
            )
    if sha256_file(job["subject_source_path"]) != manifest["subject_sha256"]:
        raise CoverContractError("subject source changed after cover generation")
    if sha256_file(job["font_file"]) != manifest["font_sha256"]:
        raise CoverContractError("font file changed after cover generation")

    output_root = Path(str(manifest["output_root"])).resolve()
    if output_root != manifest_path.parent.resolve():
        raise CoverContractError(
            f"manifest must live directly under output_root: manifest={manifest_path} output_root={output_root}"
        )
    prompt_path = Path(str(manifest["cover_prompt_package_path"])).resolve()
    prompt = load_json(prompt_path)
    if prompt.get("job_id") != job["job_id"] or prompt.get("cover_type") != job["cover_type"]:
        raise CoverContractError("run cover_prompt_package is not bound to this cover job")

    rows = manifest.get("cover_candidate_sets")
    if not isinstance(rows, list) or len(rows) != 3:
        raise CoverContractError("cover_candidate_sets must contain exactly 3 rows")
    if int(manifest.get("candidate_set_count", -1)) != 3:
        raise CoverContractError("candidate_set_count must be exactly 3")
    expected_ids = list(CANDIDATE_VARIANTS)
    actual_ids = [str(row.get("candidate_set_id") or "") for row in rows if isinstance(row, dict)]
    if actual_ids != expected_ids:
        raise CoverContractError(
            f"candidate_set_ids must be {expected_ids}, got {actual_ids}"
        )

    validated_rows = []
    for row in rows:
        candidate_id = str(row["candidate_set_id"])
        expected_dir = output_root / candidate_id
        landscape_path = Path(str(row.get("cover_16x9_path") or "")).resolve()
        portrait_path = Path(str(row.get("cover_9x16_path") or "")).resolve()
        if landscape_path.parent != expected_dir or portrait_path.parent != expected_dir:
            raise CoverContractError(
                f"candidate paths must stay inside {expected_dir}: {landscape_path}, {portrait_path}"
            )
        if row.get("template_set_id") != job["template_set_id"]:
            raise CoverContractError(f"{candidate_id} template_set_id drifted")
        if row.get("subject_sha256") != job["subject_sha256"]:
            raise CoverContractError(f"{candidate_id} does not use the locked subject source")

        expected_landscape = render_cover_image(
            job,
            profile,
            candidate_set_id=candidate_id,
            aspect="16x9",
        )
        expected_portrait = render_cover_image(
            job,
            profile,
            candidate_set_id=candidate_id,
            aspect="9x16",
        )
        landscape = ensure_exact_image(
            landscape_path,
            expected_size=CANVAS_SIZES["16x9"],
            expected_image=expected_landscape,
        )
        portrait = ensure_exact_image(
            portrait_path,
            expected_size=CANVAS_SIZES["9x16"],
            expected_image=expected_portrait,
        )
        if row.get("cover_16x9_sha256") != landscape["file_sha256"]:
            raise CoverContractError(f"{candidate_id} 16x9 file hash mismatch")
        if row.get("cover_9x16_sha256") != portrait["file_sha256"]:
            raise CoverContractError(f"{candidate_id} 9x16 file hash mismatch")

        candidate_prompt = load_json(str(row.get("cover_prompt_package_path") or ""))
        if candidate_prompt.get("job_id") != job["job_id"]:
            raise CoverContractError(f"{candidate_id} prompt package job_id mismatch")
        if candidate_prompt.get("candidate_set_id") != candidate_id:
            raise CoverContractError(f"{candidate_id} prompt package candidate id mismatch")
        validated_rows.append(
            {
                "candidate_set_id": candidate_id,
                "cover_16x9": landscape,
                "cover_9x16": portrait,
            }
        )

    contact_sheet = Path(str(manifest.get("cover_qc_contact_sheet_path") or "")).resolve()
    ensure_exact_image(contact_sheet, expected_size=(2100, 1650))
    if current_draft_path is not None:
        validate_state_binding(manifest, current_draft_path)

    return {
        "status": "cover_package_valid",
        "manifest_path": str(manifest_path),
        "job_id": job["job_id"],
        "project_id": job["project_id"],
        "workflow_mode": job["workflow_mode"],
        "cover_type": job["cover_type"],
        "template_set_id": job["template_set_id"],
        "candidate_set_count": len(validated_rows),
        "current_draft_binding_checked": current_draft_path is not None,
        "validated_candidates": validated_rows,
    }


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).resolve()
    current_draft = Path(args.current_draft).resolve() if args.current_draft else None
    try:
        report = validate_package(manifest_path, current_draft)
    except CoverContractError as exc:
        print(
            json.dumps(
                {
                    "status": "cover_package_blocked",
                    "manifest_path": str(manifest_path),
                    "blocker": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
