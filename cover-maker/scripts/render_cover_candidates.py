from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from cover_contract import (
    CANDIDATE_VARIANTS,
    CANVAS_SIZES,
    CoverContractError,
    MANIFEST_SCHEMA_VERSION,
    RENDERER_VERSION,
    ensure_exact_image,
    load_json,
    render_cover_image,
    save_json,
    sha256_file,
    validate_job,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render three deterministic 16:9/9:16 cover candidate sets from cover_job.v1."
    )
    parser.add_argument("--job", required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def build_contact_sheet(
    candidate_rows: list[dict[str, object]],
    target: Path,
) -> None:
    canvas = Image.new("RGB", (2100, 1650), (238, 238, 236))
    draw = ImageDraw.Draw(canvas)
    try:
        label_font = ImageFont.truetype("C:\\Windows\\Fonts\\msyh.ttc", 34)
    except OSError:
        label_font = ImageFont.load_default()

    for column, row in enumerate(candidate_rows):
        x = 45 + column * 690
        draw.text((x, 32), f"{row['candidate_set_id']} 16:9", fill=(24, 24, 24), font=label_font)
        with Image.open(str(row["cover_16x9_path"])) as landscape:
            preview = ImageOps_fit(landscape.convert("RGB"), (630, 354))
            canvas.paste(preview, (x, 92))
        draw.text((x, 500), f"{row['candidate_set_id']} 9:16", fill=(24, 24, 24), font=label_font)
        with Image.open(str(row["cover_9x16_path"])) as portrait:
            preview = ImageOps_fit(portrait.convert("RGB"), (430, 764))
            canvas.paste(preview, (x + 100, 560))
    canvas.save(target, quality=94)


def ImageOps_fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    # Local helper keeps the contact-sheet code independent from renderer geometry.
    from PIL import ImageOps

    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)


def main() -> int:
    args = parse_args()
    job_path = Path(args.job).resolve()
    raw_job = load_json(job_path)
    job, profile = validate_job(raw_job)
    output_root = Path(job["output_root"])
    manifest_path = output_root / "cover_generation_manifest.json"
    if manifest_path.exists() and not args.force:
        raise CoverContractError(
            f"cover generation manifest already exists; use --force to regenerate: {manifest_path}"
        )
    output_root.mkdir(parents=True, exist_ok=True)

    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    run_prompt_package_path = output_root / "cover_prompt_package.json"
    run_prompt_package = {
        "schema_version": "cover_prompt_package.v2",
        "job_id": job["job_id"],
        "project_id": job["project_id"],
        "cover_type": job["cover_type"],
        "template_set_id": job["template_set_id"],
        "reference_template_ids": profile["reference_template_ids"],
        "cover_title": job["cover_title"],
        "title_lines": job["title_lines"],
        "subject_source_path": job["subject_source_path"],
        "subject_sha256": job["subject_sha256"],
        "background_rgb": profile["background_rgb"],
        "title_rgb": profile["title_rgb"],
        "font_file": job["font_file"],
        "font_sha256": job["font_sha256"],
        "font_variation": profile["font_variation"],
        "renderer_version": RENDERER_VERSION,
        "visible_text_policy": profile["visible_text_policy"],
        "candidate_variants": CANDIDATE_VARIANTS,
    }
    save_json(run_prompt_package_path, run_prompt_package)

    candidate_rows: list[dict[str, object]] = []
    for candidate_set_id, variant in CANDIDATE_VARIANTS.items():
        candidate_dir = output_root / candidate_set_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        landscape_path = candidate_dir / "cover_16x9.png"
        portrait_path = candidate_dir / "cover_9x16.png"
        candidate_prompt_path = candidate_dir / "cover_prompt_package.json"
        candidate_manifest_path = candidate_dir / "cover_generation_manifest.json"

        landscape = render_cover_image(
            job,
            profile,
            candidate_set_id=candidate_set_id,
            aspect="16x9",
        )
        portrait = render_cover_image(
            job,
            profile,
            candidate_set_id=candidate_set_id,
            aspect="9x16",
        )
        landscape.save(landscape_path, format="PNG", optimize=True)
        portrait.save(portrait_path, format="PNG", optimize=True)

        landscape_info = ensure_exact_image(
            landscape_path,
            expected_size=CANVAS_SIZES["16x9"],
            expected_image=landscape,
        )
        portrait_info = ensure_exact_image(
            portrait_path,
            expected_size=CANVAS_SIZES["9x16"],
            expected_image=portrait,
        )
        candidate_prompt = dict(run_prompt_package)
        candidate_prompt["candidate_set_id"] = candidate_set_id
        candidate_prompt["variant"] = variant
        save_json(candidate_prompt_path, candidate_prompt)

        candidate_manifest = {
            "schema_version": "cover_candidate_manifest.v2",
            "job_id": job["job_id"],
            "candidate_set_id": candidate_set_id,
            "variant": variant,
            "cover_type": job["cover_type"],
            "template_set_id": job["template_set_id"],
            "cover_16x9": landscape_info,
            "cover_9x16": portrait_info,
            "cover_prompt_package_path": str(candidate_prompt_path),
            "renderer_version": RENDERER_VERSION,
        }
        save_json(candidate_manifest_path, candidate_manifest)
        candidate_rows.append(
            {
                "candidate_set_id": candidate_set_id,
                "variant_name": variant["name"],
                "cover_16x9_path": str(landscape_path),
                "cover_9x16_path": str(portrait_path),
                "cover_16x9_width": landscape_info["width"],
                "cover_16x9_height": landscape_info["height"],
                "cover_16x9_sha256": landscape_info["file_sha256"],
                "cover_16x9_pixel_sha256": landscape_info["pixel_sha256"],
                "cover_9x16_width": portrait_info["width"],
                "cover_9x16_height": portrait_info["height"],
                "cover_9x16_sha256": portrait_info["file_sha256"],
                "cover_9x16_pixel_sha256": portrait_info["pixel_sha256"],
                "cover_prompt_package_path": str(candidate_prompt_path),
                "cover_generation_manifest_path": str(candidate_manifest_path),
                "subject_source_path": job["subject_source_path"],
                "subject_sha256": job["subject_sha256"],
                "template_set_id": job["template_set_id"],
                "reference_template_ids": profile["reference_template_ids"],
                "selected_as_official": False,
            }
        )

    contact_sheet_path = output_root / "cover_qc_contact_sheet.jpg"
    build_contact_sheet(candidate_rows, contact_sheet_path)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at": created_at,
        "status": "ready_for_commander_qc",
        "ready_for_commander_qc": True,
        "manual_qc_status": "pending_commander_qc",
        "job_id": job["job_id"],
        "cover_job_path": str(job_path),
        "project_id": job["project_id"],
        "workflow_mode": job["workflow_mode"],
        "draft_name": job.get("draft_name", ""),
        "draft_dir": job.get("draft_dir", ""),
        "source_broll_design_path": job.get("source_broll_design_path", ""),
        "source_user_script_path": job["source_user_script_path"],
        "video_title": job["video_title"],
        "cover_title": job["cover_title"],
        "cover_title_source_location": job["cover_title_source_location"],
        "cover_title_design_reason": job["cover_title_design_reason"],
        "cover_generation_mode": "local_agent_deterministic_3_candidate_sets",
        "commander_output_dir_confirmed": job["commander_output_dir_confirmed"],
        "cover_type": job["cover_type"],
        "template_set_id": job["template_set_id"],
        "reference_template_ids": profile["reference_template_ids"],
        "subject_source_path": job["subject_source_path"],
        "subject_sha256": job["subject_sha256"],
        "font_file": job["font_file"],
        "font_sha256": job["font_sha256"],
        "font_variation": profile["font_variation"],
        "renderer_version": RENDERER_VERSION,
        "cover_prompt_package_path": str(run_prompt_package_path),
        "candidate_set_count": len(candidate_rows),
        "cover_candidate_sets": candidate_rows,
        "cover_qc_contact_sheet_path": str(contact_sheet_path),
        "output_root": str(output_root),
        "selected_candidate_set_id": "",
        "cover_16x9_path": "",
        "cover_9x16_path": "",
    }
    save_json(manifest_path, manifest)
    print(
        "\n".join(
            (
                f"COVER_GENERATION_MANIFEST={manifest_path}",
                f"COVER_QC_CONTACT_SHEET={contact_sheet_path}",
                f"CANDIDATE_SET_COUNT={len(candidate_rows)}",
                "READY_FOR_COMMANDER_QC=true",
            )
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CoverContractError as exc:
        print(f"COVER_RENDER_BLOCKED: {exc}", file=sys.stderr)
        raise SystemExit(2)
