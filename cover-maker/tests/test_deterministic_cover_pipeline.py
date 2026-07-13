from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw


COVER_ROOT = Path(__file__).resolve().parents[1]
PREPARE = COVER_ROOT / "scripts" / "prepare_cover_job.py"
RENDER = COVER_ROOT / "scripts" / "render_cover_candidates.py"
VALIDATE = COVER_ROOT / "scripts" / "validate_cover_package.py"
PROMOTE = COVER_ROOT / "scripts" / "promote_cover_candidate.ps1"


def run_python(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python", str(script), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def make_subject(path: Path) -> None:
    image = Image.new("RGBA", (900, 1500), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((250, 80, 650, 480), fill=(220, 180, 150, 255))
    draw.rounded_rectangle((170, 420, 730, 1450), radius=180, fill=(30, 30, 34, 255))
    image.save(path)


def prepare_job(
    tmp_path: Path,
    *,
    output_name: str,
    subject_name: str = "subject.png",
    cover_type: str | None = "white_editorial",
    workflow_mode: str = "standard_pipeline",
) -> tuple[Path, Path, Path, Path]:
    output_root = tmp_path / output_name
    subject = tmp_path / subject_name
    if not subject.exists():
        make_subject(subject)
    script = tmp_path / "script.md"
    script.write_text("source", "utf-8")
    broll = tmp_path / "broll.md"
    broll.write_text("broll", "utf-8")
    draft_dir = tmp_path / "draft-a"
    draft_dir.mkdir(exist_ok=True)

    args = [
        "--project-id",
        "project-a",
        "--workflow-mode",
        workflow_mode,
        "--source-user-script",
        str(script),
        "--video-title",
        "video title",
        "--cover-title",
        "糊弄散户的假身材",
        "--cover-title-source-location",
        "script.md:1",
        "--cover-title-design-reason",
        "test",
        "--title-line",
        "糊弄散户的",
        "--title-line",
        "假身材",
        "--subject-source",
        str(subject),
        "--output-root",
        str(output_root),
        "--commander-confirmed-output-dir",
    ]
    if cover_type is not None:
        args.extend(("--cover-type", cover_type))
    if workflow_mode == "standard_pipeline":
        args.extend(
            (
                "--draft-name",
                "draft-a",
                "--draft-dir",
                str(draft_dir),
                "--source-broll-design",
                str(broll),
            )
        )
    result = run_python(PREPARE, *args)
    assert result.returncode == 0, result.stdout
    return output_root / "cover_job.json", output_root, broll, draft_dir


def test_white_editorial_render_is_exact_and_state_bound(tmp_path: Path) -> None:
    job_path, output_root, broll, draft_dir = prepare_job(tmp_path, output_name="white")

    render = run_python(RENDER, "--job", str(job_path))
    assert render.returncode == 0, render.stdout
    manifest_path = output_root / "cover_generation_manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    assert manifest["cover_type"] == "white_editorial"
    assert manifest["template_set_id"] == "s16_schrodinger_white_black"
    assert manifest["candidate_set_count"] == 3

    landscape_path = Path(manifest["cover_candidate_sets"][0]["cover_16x9_path"])
    portrait_path = Path(manifest["cover_candidate_sets"][0]["cover_9x16_path"])
    with Image.open(landscape_path) as landscape:
        assert landscape.size == (3840, 2160)
        landscape_rgb = landscape.convert("RGB")
        assert landscape_rgb.getpixel((0, 0)) == (250, 250, 249)
        title_crop = landscape_rgb.crop((120, 350, 2100, 1600))
        active_rows = []
        for y in range(title_crop.height):
            dark_pixels = sum(
                1
                for red, green, blue in (title_crop.getpixel((x, y)) for x in range(title_crop.width))
                if max(red, green, blue) < 80
            )
            if dark_pixels > 20:
                active_rows.append(y)
        row_groups = 1 + sum(
            1 for previous, current in zip(active_rows, active_rows[1:]) if current - previous > 30
        )
        assert row_groups >= 2, "title hierarchy collapsed into overlapping rows"
    with Image.open(portrait_path) as portrait:
        assert portrait.size == (2160, 3840)
        assert portrait.convert("RGB").getpixel((0, 0)) == (250, 250, 249)

    state_path = tmp_path / "current_draft.json"
    state = {
        "draft_name": "draft-a",
        "draft_dir": str(draft_dir),
        "aroll_qc_passed": True,
        "broll_design_md_path": str(broll),
        "broll_write": {
            "status": "passed",
            "commander_qc_passed_at": "2026-07-13T00:00:00+08:00",
        },
        "enhancement_decision_status": "resolved_by_commander",
    }
    state_path.write_text(json.dumps(state), "utf-8")
    validated = run_python(
        VALIDATE,
        "--manifest",
        str(manifest_path),
        "--current-draft",
        str(state_path),
    )
    assert validated.returncode == 0, validated.stdout
    assert '"status": "cover_package_valid"' in validated.stdout

    promotion = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROMOTE),
            "-CoverGenerationManifestPath",
            str(manifest_path),
            "-CandidateSetId",
            "candidate_01",
            "-CurrentDraftPath",
            str(state_path),
            "-UpdateCurrentDraft",
            "-CommanderQcPassed",
            "-ValidateOnly",
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert promotion.returncode == 0, promotion.stdout
    assert "validated_only" in promotion.stdout

    state["draft_name"] = "different-draft"
    state_path.write_text(json.dumps(state), "utf-8")
    wrong_draft = run_python(
        VALIDATE,
        "--manifest",
        str(manifest_path),
        "--current-draft",
        str(state_path),
    )
    assert wrong_draft.returncode != 0
    assert "draft_name mismatch" in wrong_draft.stdout

    with Image.open(landscape_path) as image:
        changed = image.convert("RGB")
    changed.putpixel((0, 0), (255, 0, 0))
    changed.save(landscape_path)
    tampered = run_python(VALIDATE, "--manifest", str(manifest_path))
    assert tampered.returncode != 0
    assert "locked renderer output" in tampered.stdout


def test_subject_identity_never_selects_cover_style(tmp_path: Path) -> None:
    default_job, _, _, _ = prepare_job(
        tmp_path,
        output_name="default",
        subject_name="commander_face_screenshot.png",
        cover_type=None,
        workflow_mode="old_video_recovery",
    )
    default_payload = json.loads(default_job.read_text("utf-8"))
    assert default_payload["cover_type"] == "white_editorial"
    assert default_payload["template_set_id"] == "s16_schrodinger_white_black"

    dark_job, dark_output, _, _ = prepare_job(
        tmp_path,
        output_name="dark",
        subject_name="commander_face_screenshot.png",
        cover_type="dark_face",
        workflow_mode="old_video_recovery",
    )
    dark_payload = json.loads(dark_job.read_text("utf-8"))
    assert dark_payload["cover_type"] == "dark_face"
    assert dark_payload["template_set_id"] == "s11_2_confess_face_big_text"
    rendered = run_python(RENDER, "--job", str(dark_job))
    assert rendered.returncode == 0, rendered.stdout
    dark_manifest_path = dark_output / "cover_generation_manifest.json"
    dark_manifest = json.loads(dark_manifest_path.read_text("utf-8"))
    dark_landscape = Path(dark_manifest["cover_candidate_sets"][0]["cover_16x9_path"])
    with Image.open(dark_landscape) as image:
        assert image.convert("RGB").getpixel((0, 0)) == (8, 8, 8)
    validated = run_python(VALIDATE, "--manifest", str(dark_manifest_path))
    assert validated.returncode == 0, validated.stdout


def test_legacy_or_ad_hoc_manifest_cannot_be_promoted(tmp_path: Path) -> None:
    fake = tmp_path / "cover_generation_manifest.json"
    fake.write_text(
        json.dumps(
            {
                "schema_version": "cover_generation_manifest.v1",
                "draft_name": "wrong-draft",
                "cover_candidate_sets": [],
            }
        ),
        "utf-8",
    )
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROMOTE),
            "-CoverGenerationManifestPath",
            str(fake),
            "-CandidateSetId",
            "candidate_01",
            "-ValidateOnly",
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert result.returncode != 0
    assert "legacy or ad hoc manifests are blocked" in result.stdout
