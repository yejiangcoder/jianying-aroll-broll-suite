from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

from jy_bridge import write_json


TEMP_AUDIO_PATTERNS = [
    "audio_vad/**/*.s16le",
    "**/audio_vad/**/*.s16le",
]

DEBUG_DRAFT_JSON_PATTERNS = [
    "draft_content.modified.enc.json",
    "draft_content.modified.dec.json",
    "draft_content.before.dec.json",
    "draft_content.after.dec.json",
    "audit_*.dec.json",
    "audit_root_before.dec.json",
    "inspect_runtime/**/draft_content.dec.json",
    "inspect_runtime/**/audit_*.dec.json",
    "**/draft_content.modified.enc.json",
    "**/draft_content.modified.dec.json",
    "**/draft_content.before.dec.json",
    "**/draft_content.after.dec.json",
    "**/audit_*.dec.json",
    "**/audit_root_before.dec.json",
]


def fmt_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} GB"


def matched_files(root: Path, patterns: list[str]) -> list[Path]:
    results: dict[str, Path] = {}
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file():
                results[str(path.resolve()).lower()] = path
    return sorted(results.values(), key=lambda p: str(p).lower())


def safe_unlink(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    if path.exists() and path.is_file():
        path.unlink()
        return True
    return False


def cleanup_current_runtime(
    run_dir: Path,
    runtime_mode: str = "production",
    keep_debug_dec_json: bool = False,
    keep_audio_pcm: bool = False,
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    if runtime_mode == "debug":
        report = {
            "runtime_mode": runtime_mode,
            "skipped": True,
            "reason": "DEBUG_MODE_KEEP_ALL_RUNTIME_FILES",
            "deleted_temp_audio_files": 0,
            "deleted_debug_json_files": 0,
            "released_size": 0,
            "released_size_human": fmt_size(0),
        }
        write_json(run_dir / "cleanup_report.json", report)
        (run_dir / "cleanup_report.md").write_text("# Runtime Cleanup\n\n- skipped: debug mode\n", "utf-8")
        return report

    delete_audio = [] if keep_audio_pcm else matched_files(run_dir, TEMP_AUDIO_PATTERNS)
    delete_json = [] if keep_debug_dec_json else matched_files(run_dir, DEBUG_DRAFT_JSON_PATTERNS)
    targets: dict[str, Path] = {}
    for path in delete_audio + delete_json:
        targets[str(path.resolve()).lower()] = path

    deleted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for path in targets.values():
        size = path.stat().st_size if path.exists() else 0
        kind = "temp_audio" if fnmatch.fnmatch(path.name.lower(), "*.s16le") else "debug_json"
        if safe_unlink(path, run_dir):
            deleted.append({"path": str(path), "size": size, "kind": kind})
        else:
            skipped.append({"path": str(path), "size": size, "kind": kind, "reason": "guard_rejected_or_missing"})

    released_size = sum(int(row["size"]) for row in deleted)
    report = {
        "runtime_mode": runtime_mode,
        "skipped": False,
        "keep_debug_dec_json": keep_debug_dec_json,
        "keep_audio_pcm": keep_audio_pcm,
        "deleted_temp_audio_files": sum(1 for row in deleted if row["kind"] == "temp_audio"),
        "deleted_debug_json_files": sum(1 for row in deleted if row["kind"] == "debug_json"),
        "released_size": released_size,
        "released_size_human": fmt_size(released_size),
        "deleted": deleted,
        "skipped_targets": skipped,
    }
    write_json(run_dir / "cleanup_report.json", report)
    lines = [
        "# Runtime Cleanup",
        "",
        f"- runtime_mode: {runtime_mode}",
        f"- released_size: {fmt_size(released_size)}",
        f"- deleted_temp_audio_files: {report['deleted_temp_audio_files']}",
        f"- deleted_debug_json_files: {report['deleted_debug_json_files']}",
        "",
        "## Deleted",
    ]
    if not deleted:
        lines.append("- none")
    for row in deleted:
        lines.append(f"- {row['kind']} | {row['path']} | {fmt_size(int(row['size']))}")
    (run_dir / "cleanup_report.md").write_text("\n".join(lines) + "\n", "utf-8")
    return report
