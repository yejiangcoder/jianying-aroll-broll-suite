from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime
from pathlib import Path

from cover_contract import CoverContractError, JOB_SCHEMA_VERSION, save_json, validate_job


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a machine-bound cover job before local cover generation."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument(
        "--workflow-mode",
        choices=("standard_pipeline", "old_video_recovery"),
        required=True,
    )
    parser.add_argument("--draft-name", default="")
    parser.add_argument("--draft-dir", default="")
    parser.add_argument("--source-broll-design", default="")
    parser.add_argument("--source-user-script", required=True)
    parser.add_argument("--video-title", required=True)
    parser.add_argument("--cover-title", required=True)
    parser.add_argument("--cover-title-source-location", required=True)
    parser.add_argument("--cover-title-design-reason", required=True)
    parser.add_argument(
        "--cover-type",
        choices=("white_editorial", "dark_face"),
        default="white_editorial",
    )
    parser.add_argument(
        "--title-line",
        action="append",
        dest="title_lines",
        required=True,
        help="Repeat 1-3 times. The final line is rendered as the largest title line.",
    )
    parser.add_argument("--subject-source", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--commander-confirmed-output-dir", action="store_true", required=True)
    parser.add_argument("--job-path", default="")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_root = Path(args.output_root).resolve()
    job_path = Path(args.job_path).resolve() if args.job_path else output_root / "cover_job.json"
    if job_path.exists() and not args.force:
        raise CoverContractError(f"cover job already exists; use --force to replace it: {job_path}")

    job = {
        "schema_version": JOB_SCHEMA_VERSION,
        "job_id": str(uuid.uuid4()),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "project_id": args.project_id,
        "workflow_mode": args.workflow_mode,
        "draft_name": args.draft_name,
        "draft_dir": args.draft_dir,
        "source_broll_design_path": args.source_broll_design,
        "source_user_script_path": args.source_user_script,
        "video_title": args.video_title,
        "cover_title": args.cover_title,
        "cover_title_source_location": args.cover_title_source_location,
        "cover_title_design_reason": args.cover_title_design_reason,
        "cover_type": args.cover_type,
        "title_lines": args.title_lines,
        "subject_source_path": args.subject_source,
        "output_root": str(output_root),
        "commander_output_dir_confirmed": True,
        "candidate_count": 3,
    }
    resolved_job, _ = validate_job(job)
    output_root.mkdir(parents=True, exist_ok=True)
    save_json(job_path, resolved_job)
    print(
        "\n".join(
            (
                f"COVER_JOB={job_path}",
                f"COVER_TYPE={resolved_job['cover_type']}",
                f"TEMPLATE_SET_ID={resolved_job['template_set_id']}",
                f"SUBJECT_SHA256={resolved_job['subject_sha256']}",
            )
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CoverContractError as exc:
        print(f"COVER_JOB_BLOCKED: {exc}", file=sys.stderr)
        raise SystemExit(2)
