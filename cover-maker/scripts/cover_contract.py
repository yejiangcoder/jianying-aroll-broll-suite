from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps


COVER_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = COVER_ROOT / "cover_maker_config.json"
JOB_SCHEMA_VERSION = "cover_job.v1"
MANIFEST_SCHEMA_VERSION = "cover_generation_manifest.v2"
RENDERER_VERSION = "deterministic_cover_renderer.v1"

CANVAS_SIZES = {
    "16x9": (3840, 2160),
    "9x16": (2160, 3840),
}

CANDIDATE_VARIANTS = {
    "candidate_01": {
        "name": "balanced",
        "subject_scale": 1.00,
        "subject_shift_x": 0.00,
        "subject_shift_y": 0.00,
    },
    "candidate_02": {
        "name": "large_subject",
        "subject_scale": 1.12,
        "subject_shift_x": 0.015,
        "subject_shift_y": 0.015,
    },
    "candidate_03": {
        "name": "more_negative_space",
        "subject_scale": 0.86,
        "subject_shift_x": 0.035,
        "subject_shift_y": 0.00,
    },
}


class CoverContractError(ValueError):
    pass


def load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).resolve()
    try:
        data = json.loads(resolved.read_text("utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CoverContractError(f"Could not read JSON: {resolved}: {exc}") from exc
    if not isinstance(data, dict):
        raise CoverContractError(f"JSON root must be an object: {resolved}")
    return data


def save_json(path: str | Path, payload: dict[str, Any]) -> None:
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pixel_sha256(image: Image.Image) -> str:
    rgb = image.convert("RGB")
    return hashlib.sha256(rgb.tobytes()).hexdigest()


def normalize_title(value: str) -> str:
    return "".join(str(value).split())


def resolve_existing_file(value: str, label: str) -> Path:
    if not value:
        raise CoverContractError(f"{label} is required")
    path = Path(value).resolve()
    if not path.is_file():
        raise CoverContractError(f"{label} not found: {path}")
    return path


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config = load_json(path)
    profiles = config.get("cover_type_profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise CoverContractError("cover_maker_config.cover_type_profiles is required")
    return config


def profile_for_job(job: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    cover_type = str(job.get("cover_type") or "")
    profiles = config["cover_type_profiles"]
    profile = profiles.get(cover_type)
    if not isinstance(profile, dict):
        raise CoverContractError(f"Unsupported cover_type: {cover_type}")
    return profile


def validate_job(
    job: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    config = config or load_config()
    if job.get("schema_version") != JOB_SCHEMA_VERSION:
        raise CoverContractError(
            f"schema_version must be {JOB_SCHEMA_VERSION}, got {job.get('schema_version')!r}"
        )

    required_text = (
        "job_id",
        "project_id",
        "workflow_mode",
        "video_title",
        "cover_title",
        "cover_title_source_location",
        "cover_title_design_reason",
        "source_user_script_path",
        "cover_type",
        "subject_source_path",
        "output_root",
    )
    for key in required_text:
        if not str(job.get(key) or "").strip():
            raise CoverContractError(f"cover job field is required: {key}")
    if job.get("commander_output_dir_confirmed") is not True:
        raise CoverContractError("commander_output_dir_confirmed must be true")

    workflow_mode = str(job["workflow_mode"])
    if workflow_mode not in {"standard_pipeline", "old_video_recovery"}:
        raise CoverContractError(f"Unsupported workflow_mode: {workflow_mode}")
    if workflow_mode == "standard_pipeline":
        for key in ("draft_name", "draft_dir", "source_broll_design_path"):
            if not str(job.get(key) or "").strip():
                raise CoverContractError(f"standard_pipeline requires {key}")

    title_lines = job.get("title_lines")
    if not isinstance(title_lines, list) or not 1 <= len(title_lines) <= 3:
        raise CoverContractError("title_lines must contain 1 to 3 non-empty strings")
    if any(not isinstance(line, str) or not line.strip() for line in title_lines):
        raise CoverContractError("title_lines must contain only non-empty strings")
    rendered_title = normalize_title("".join(title_lines))
    approved_title = normalize_title(str(job["cover_title"]))
    if rendered_title != approved_title:
        raise CoverContractError(
            "title_lines must reproduce cover_title exactly after whitespace normalization: "
            f"rendered={rendered_title!r} approved={approved_title!r}"
        )

    candidate_count = int(job.get("candidate_count", 3))
    if candidate_count != 3:
        raise CoverContractError("candidate_count must be exactly 3 for local deterministic generation")

    profile = profile_for_job(job, config)
    expected_template_set = str(profile.get("template_set_id") or "")
    requested_template_set = str(job.get("template_set_id") or expected_template_set)
    if requested_template_set != expected_template_set:
        raise CoverContractError(
            f"cover_type={job['cover_type']} requires template_set_id={expected_template_set}, "
            f"got {requested_template_set}"
        )

    font_path = resolve_existing_file(str(profile.get("font_file") or ""), "profile font_file")
    subject_path = resolve_existing_file(str(job["subject_source_path"]), "subject_source_path")
    source_script = resolve_existing_file(str(job["source_user_script_path"]), "source_user_script_path")
    if workflow_mode == "standard_pipeline":
        resolve_existing_file(str(job["source_broll_design_path"]), "source_broll_design_path")

    try:
        with Image.open(subject_path) as image:
            image.verify()
        with Image.open(subject_path) as image:
            width, height = image.size
            if width < 512 or height < 512:
                raise CoverContractError(
                    f"subject image is too small: {subject_path} size={width}x{height}; minimum is 512x512"
                )
    except CoverContractError:
        raise
    except Exception as exc:
        raise CoverContractError(f"subject_source_path is not a readable image: {subject_path}: {exc}") from exc

    resolved = dict(job)
    resolved["template_set_id"] = expected_template_set
    resolved["candidate_count"] = candidate_count
    resolved["subject_source_path"] = str(subject_path)
    resolved["source_user_script_path"] = str(source_script)
    output_root = Path(str(job["output_root"])).resolve()
    try:
        output_root.relative_to(COVER_ROOT.resolve())
    except ValueError:
        pass
    else:
        raise CoverContractError(
            f"Runtime cover output cannot be written inside the tool repository: {output_root}"
        )
    resolved["output_root"] = str(output_root)
    if job.get("draft_dir"):
        resolved["draft_dir"] = str(Path(str(job["draft_dir"])).resolve())
    if job.get("source_broll_design_path"):
        resolved["source_broll_design_path"] = str(
            Path(str(job["source_broll_design_path"])).resolve()
        )
    resolved["font_file"] = str(font_path)
    resolved["font_sha256"] = sha256_file(font_path)
    resolved["subject_sha256"] = sha256_file(subject_path)
    return resolved, profile


def _font(path: str, size: int, variation: str) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(path, max(1, int(size)))
    if variation:
        try:
            font.set_variation_by_name(variation)
        except (OSError, ValueError):
            pass
    return font


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font_path: str,
    variation: str,
    max_width: int,
    preferred_size: int,
    minimum_size: int,
) -> ImageFont.FreeTypeFont:
    low = max(1, minimum_size)
    high = max(low, preferred_size)
    best = _font(font_path, low, variation)
    while low <= high:
        middle = (low + high) // 2
        candidate = _font(font_path, middle, variation)
        bbox = draw.textbbox((0, 0), text, font=candidate)
        if bbox[2] - bbox[0] <= max_width:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    return best


def _scaled_box(
    box: tuple[int, int, int, int],
    *,
    scale: float,
    shift_x: int,
    shift_y: int,
    canvas_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    width = right - left
    height = bottom - top
    center_x = (left + right) / 2 + shift_x
    center_y = bottom - height * scale / 2 + shift_y
    new_width = width * scale
    new_height = height * scale
    canvas_width, canvas_height = canvas_size
    new_left = max(0, int(center_x - new_width / 2))
    new_top = max(0, int(center_y - new_height / 2))
    new_right = min(canvas_width, int(center_x + new_width / 2))
    new_bottom = min(canvas_height, int(center_y + new_height / 2))
    return new_left, new_top, new_right, new_bottom


def _paste_subject(
    canvas: Image.Image,
    subject: Image.Image,
    box: tuple[int, int, int, int],
    *,
    background_rgb: tuple[int, int, int],
) -> None:
    target_width = max(1, box[2] - box[0])
    target_height = max(1, box[3] - box[1])
    source = subject.convert("RGBA")
    contained = ImageOps.contain(source, (target_width, target_height), Image.Resampling.LANCZOS)
    x = box[0] + (target_width - contained.width) // 2
    y = box[3] - contained.height

    alpha = contained.getchannel("A")
    if alpha.getextrema() == (255, 255):
        # Opaque subjects are allowed when their own background is already compatible.
        rgb = contained.convert("RGB")
        corners = (
            rgb.getpixel((0, 0)),
            rgb.getpixel((rgb.width - 1, 0)),
            rgb.getpixel((0, rgb.height - 1)),
            rgb.getpixel((rgb.width - 1, rgb.height - 1)),
        )
        distance = max(
            max(abs(int(corner[index]) - background_rgb[index]) for index in range(3))
            for corner in corners
        )
        if distance > 80:
            raise CoverContractError(
                "Opaque subject background is incompatible with the selected cover type. "
                "Use a transparent PNG or a subject image on the matching background."
            )
    canvas.paste(contained, (x, y), contained)


def _draw_title(
    canvas: Image.Image,
    *,
    title_lines: list[str],
    font_path: str,
    font_variation: str,
    title_rgb: tuple[int, int, int],
    title_box: tuple[int, int, int, int],
    aspect: str,
) -> None:
    draw = ImageDraw.Draw(canvas)
    left, top, right, bottom = title_box
    max_width = right - left
    max_height = bottom - top
    kicker_lines = title_lines[:-1]
    hero_line = title_lines[-1]

    if aspect == "16x9":
        kicker_preferred = int(canvas.height * 0.090)
        kicker_minimum = int(canvas.height * 0.052)
        hero_preferred = int(canvas.height * 0.155)
        hero_minimum = int(canvas.height * 0.082)
        line_gap = int(canvas.height * 0.020)
    else:
        kicker_preferred = int(canvas.height * 0.054)
        kicker_minimum = int(canvas.height * 0.033)
        hero_preferred = int(canvas.height * 0.088)
        hero_minimum = int(canvas.height * 0.050)
        line_gap = int(canvas.height * 0.012)

    kicker_fonts = [
        _fit_font(
            draw,
            line,
            font_path=font_path,
            variation=font_variation,
            max_width=max_width,
            preferred_size=kicker_preferred,
            minimum_size=kicker_minimum,
        )
        for line in kicker_lines
    ]
    hero_font = _fit_font(
        draw,
        hero_line,
        font_path=font_path,
        variation=font_variation,
        max_width=max_width,
        preferred_size=hero_preferred,
        minimum_size=hero_minimum,
    )

    line_rows: list[tuple[str, ImageFont.FreeTypeFont]] = list(zip(kicker_lines, kicker_fonts))
    line_rows.append((hero_line, hero_font))
    heights = []
    for text, font in line_rows:
        bbox = draw.textbbox((0, 0), text, font=font)
        heights.append(bbox[3] - bbox[1])
    total_height = sum(heights) + line_gap * max(0, len(line_rows) - 1)
    if total_height > max_height:
        raise CoverContractError(
            f"Title does not fit the locked title area: total_height={total_height} max_height={max_height}"
        )

    y = top
    for index, (text, font) in enumerate(line_rows):
        bbox = draw.textbbox((0, 0), text, font=font)
        draw.text((left, y - bbox[1]), text, font=font, fill=title_rgb)
        y += heights[index] + line_gap


def _layout_box(values: list[float], size: tuple[int, int]) -> tuple[int, int, int, int]:
    width, height = size
    return (
        int(values[0] * width),
        int(values[1] * height),
        int(values[2] * width),
        int(values[3] * height),
    )


def render_cover_image(
    job: dict[str, Any],
    profile: dict[str, Any],
    *,
    candidate_set_id: str,
    aspect: str,
) -> Image.Image:
    if aspect not in CANVAS_SIZES:
        raise CoverContractError(f"Unsupported aspect: {aspect}")
    variant = CANDIDATE_VARIANTS.get(candidate_set_id)
    if not variant:
        raise CoverContractError(f"Unsupported candidate_set_id: {candidate_set_id}")

    size = CANVAS_SIZES[aspect]
    background_rgb = tuple(int(value) for value in profile["background_rgb"])
    title_rgb = tuple(int(value) for value in profile["title_rgb"])
    canvas = Image.new("RGB", size, background_rgb)
    layout = profile["layouts"][aspect]
    subject_box = _layout_box(layout["subject_box"], size)
    subject_box = _scaled_box(
        subject_box,
        scale=float(variant["subject_scale"]),
        shift_x=int(float(variant["subject_shift_x"]) * size[0]),
        shift_y=int(float(variant["subject_shift_y"]) * size[1]),
        canvas_size=size,
    )

    with Image.open(job["subject_source_path"]) as subject:
        _paste_subject(canvas, subject, subject_box, background_rgb=background_rgb)

    title_box = _layout_box(layout["title_box"], size)
    _draw_title(
        canvas,
        title_lines=list(job["title_lines"]),
        font_path=str(job["font_file"]),
        font_variation=str(profile.get("font_variation") or "Black"),
        title_rgb=title_rgb,
        title_box=title_box,
        aspect=aspect,
    )
    return canvas


def image_dimensions(path: str | Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            image.load()
            return image.size
    except Exception as exc:
        raise CoverContractError(f"Not a readable image: {path}: {exc}") from exc


def ensure_exact_image(
    path: str | Path,
    *,
    expected_size: tuple[int, int],
    expected_image: Image.Image | None = None,
) -> dict[str, Any]:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise CoverContractError(f"Cover image not found: {resolved}")
    try:
        with Image.open(resolved) as actual:
            actual.load()
            actual_rgb = actual.convert("RGB")
    except Exception as exc:
        raise CoverContractError(f"Cover image is not decodable: {resolved}: {exc}") from exc
    if actual_rgb.size != expected_size:
        raise CoverContractError(
            f"Cover image has wrong dimensions: {resolved} actual={actual_rgb.size} expected={expected_size}"
        )
    if expected_image is not None and pixel_sha256(actual_rgb) != pixel_sha256(expected_image):
        raise CoverContractError(
            f"Cover pixels do not match the locked renderer output: {resolved}"
        )
    return {
        "path": str(resolved),
        "width": actual_rgb.width,
        "height": actual_rgb.height,
        "file_sha256": sha256_file(resolved),
        "pixel_sha256": pixel_sha256(actual_rgb),
    }
