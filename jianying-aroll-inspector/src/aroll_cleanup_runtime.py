from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any

from aroll_runtime_mode import DEBUG_DRAFT_JSON_PATTERNS, TEMP_AUDIO_PATTERNS, fmt_size
from aroll_runtime_paths import get_aroll_runs_dir
from jy_bridge import write_json


RUNTIME_DIR = get_aroll_runs_dir()

HARD_PRESERVE_RUNTIME_NAMES: set[str] = set()


def path_size(path: Path) -> int:
    if path.is_dir():
        total = 0
        for child in path.rglob("*"):
            if child.is_file():
                total += path_size(child)
        return total
    try:
        return path.stat().st_size
    except OSError:
        return 0


def latest_runtime_names(runtime_dir: Path, prefix: str, keep_count: int) -> set[str]:
    if not runtime_dir.exists() or keep_count <= 0:
        return set()
    dirs = sorted(
        [path for path in runtime_dir.iterdir() if path.is_dir() and path.name.startswith(prefix)],
        key=lambda path: path.name,
        reverse=True,
    )
    return {path.name for path in dirs[:keep_count]}


def matched_files(root: Path, patterns: list[str]) -> list[Path]:
    found: dict[str, Path] = {}
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file():
                found[str(path.resolve()).lower()] = path
    return sorted(found.values(), key=lambda path: str(path).lower())


def is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def build_cleanup_plan(
    runtime_dir: Path = RUNTIME_DIR,
    output_dir: Path | None = None,
    keep_latest_engine: int = 2,
    keep_latest_phase6b: int = 3,
    keep_latest_operator: int = 3,
    keep_latest_uat: int = 3,
    keep_latest_inspect: int = 1,
    delete_temp_audio: bool = False,
    delete_debug_draft_json: bool = False,
    prune_old_runtime_dirs: bool = False,
    keep_current_run: bool = True,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    output_dir = Path(output_dir) if output_dir else None
    preserved_names = set(HARD_PRESERVE_RUNTIME_NAMES)
    preserved_names |= latest_runtime_names(runtime_dir, "aroll_phase4e_full_aroll_", keep_latest_engine)
    preserved_names |= latest_runtime_names(runtime_dir, "aroll_phase6b_llm_first_decision_", keep_latest_phase6b)
    preserved_names |= latest_runtime_names(runtime_dir, "aroll_operator_", keep_latest_operator)
    preserved_names |= latest_runtime_names(runtime_dir, "aroll_uat_full_", keep_latest_uat)
    preserved_names |= latest_runtime_names(runtime_dir, "aroll_inspect_", keep_latest_inspect)

    file_targets: list[dict[str, Any]] = []
    dir_targets: list[dict[str, Any]] = []
    preserved_dirs: list[str] = []
    scanned_dirs: list[str] = []
    if runtime_dir.exists():
        for run_dir in sorted([path for path in runtime_dir.iterdir() if path.is_dir()], key=lambda path: path.name):
            if output_dir and run_dir.resolve() == output_dir.resolve():
                if keep_current_run:
                    preserved_dirs.append(run_dir.name)
                    continue
                continue
            if run_dir.name in preserved_names:
                preserved_dirs.append(run_dir.name)
                continue
            scanned_dirs.append(run_dir.name)
            if prune_old_runtime_dirs:
                size = path_size(run_dir)
                dir_targets.append({"path": str(run_dir), "runtime_dir": run_dir.name, "kind": "runtime_dir", "size": size})
                continue
            patterns: list[str] = []
            if delete_temp_audio:
                patterns.extend(TEMP_AUDIO_PATTERNS)
            if delete_debug_draft_json:
                patterns.extend(DEBUG_DRAFT_JSON_PATTERNS)
            for file_path in matched_files(run_dir, patterns):
                kind = "temp_audio" if file_path.suffix.lower() == ".s16le" else "debug_json"
                file_targets.append(
                    {
                        "path": str(file_path),
                        "runtime_dir": run_dir.name,
                        "kind": kind,
                        "size": path_size(file_path),
                    }
                )

    estimated = sum(int(row["size"]) for row in file_targets) + sum(int(row["size"]) for row in dir_targets)
    return {
        "runtime_dir": str(runtime_dir),
        "output_dir": str(output_dir) if output_dir else "",
        "keep_latest_engine": keep_latest_engine,
        "keep_current_run": keep_current_run,
        "keep_latest_phase6b": keep_latest_phase6b,
        "keep_latest_operator": keep_latest_operator,
        "keep_latest_uat": keep_latest_uat,
        "keep_latest_inspect": keep_latest_inspect,
        "delete_temp_audio": delete_temp_audio,
        "delete_debug_draft_json": delete_debug_draft_json,
        "prune_old_runtime_dirs": prune_old_runtime_dirs,
        "preserved_dirs": sorted(set(preserved_dirs)),
        "hard_preserved_dirs": sorted(HARD_PRESERVE_RUNTIME_NAMES),
        "scanned_non_preserved_dirs": scanned_dirs,
        "file_delete_targets": file_targets,
        "runtime_dir_delete_targets": dir_targets,
        "estimated_space_freed": estimated,
        "estimated_space_freed_human": fmt_size(estimated),
    }


def write_cleanup_plan_md(path: Path, plan: dict[str, Any]) -> None:
    lines = [
        "# A-Roll Runtime Cleanup Plan",
        "",
        f"- runtime_dir: {plan['runtime_dir']}",
        f"- dry_run_default: true",
        f"- estimated_space_freed: {plan['estimated_space_freed_human']}",
        f"- file_delete_targets: {len(plan['file_delete_targets'])}",
        f"- runtime_dir_delete_targets: {len(plan['runtime_dir_delete_targets'])}",
        "",
        "## File delete targets",
    ]
    if not plan["file_delete_targets"]:
        lines.append("- none")
    for row in plan["file_delete_targets"]:
        lines.append(f"- {row['kind']} | {row['path']} | {fmt_size(int(row['size']))}")
    lines.extend(["", "## Runtime dir delete targets"])
    if not plan["runtime_dir_delete_targets"]:
        lines.append("- none")
    for row in plan["runtime_dir_delete_targets"]:
        lines.append(f"- {row['runtime_dir']} | {row['path']} | {fmt_size(int(row['size']))}")
    lines.extend(["", "## Preserved dirs"])
    for name in plan["preserved_dirs"]:
        lines.append(f"- {name}")
    path.write_text("\n".join(lines) + "\n", "utf-8")


def execute_cleanup(plan: dict[str, Any], runtime_dir: Path) -> dict[str, Any]:
    runtime_size_before = path_size(runtime_dir)
    deleted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in plan["file_delete_targets"]:
        path = Path(row["path"])
        if not is_relative_to(path, runtime_dir):
            skipped.append(row | {"reason": "target_outside_runtime"})
            continue
        if not path.exists():
            skipped.append(row | {"reason": "missing"})
            continue
        path.unlink()
        deleted.append(row)
    deleted_dirs: list[dict[str, Any]] = []
    for row in plan["runtime_dir_delete_targets"]:
        path = Path(row["path"])
        if not is_relative_to(path, runtime_dir):
            skipped.append(row | {"reason": "target_outside_runtime"})
            continue
        if not path.exists():
            skipped.append(row | {"reason": "missing"})
            continue
        shutil.rmtree(path)
        deleted_dirs.append(row)
    released = sum(int(row["size"]) for row in deleted)
    released += sum(int(row["size"]) for row in deleted_dirs)
    runtime_size_after = path_size(runtime_dir)
    return {
        "deleted_runtime_dirs": deleted_dirs,
        "deleted_temp_audio_files": sum(1 for row in deleted if row["kind"] == "temp_audio"),
        "deleted_debug_json_files": sum(1 for row in deleted if row["kind"] == "debug_json"),
        "deleted_files": deleted,
        "skipped": skipped,
        "released_size": released,
        "released_size_human": fmt_size(released),
        "runtime_size_before": runtime_size_before,
        "runtime_size_before_human": fmt_size(runtime_size_before),
        "runtime_size_after": runtime_size_after,
        "runtime_size_after_human": fmt_size(runtime_size_after),
        "preserved_dirs": plan["preserved_dirs"],
    }


def dry_run_report(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "dry_run": True,
        "deleted_runtime_dirs": [],
        "deleted_temp_audio_files": 0,
        "deleted_debug_json_files": 0,
        "deleted_files": [],
        "skipped": [],
        "released_size": 0,
        "released_size_human": fmt_size(0),
        "runtime_size_before": 0,
        "runtime_size_before_human": "",
        "runtime_size_after": 0,
        "runtime_size_after_human": "",
        "estimated_space_freed": plan["estimated_space_freed"],
        "estimated_space_freed_human": plan["estimated_space_freed_human"],
        "preserved_dirs": plan["preserved_dirs"],
    }


def write_cleanup_report_md(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# A-Roll Runtime Cleanup Report",
        "",
        f"- dry_run: {report.get('dry_run', False)}",
        f"- released_size: {report.get('released_size_human')}",
        f"- runtime_size_before: {report.get('runtime_size_before_human', '')}",
        f"- runtime_size_after: {report.get('runtime_size_after_human', '')}",
        f"- estimated_space_freed: {report.get('estimated_space_freed_human', '')}",
        f"- deleted_temp_audio_files: {report.get('deleted_temp_audio_files')}",
        f"- deleted_debug_json_files: {report.get('deleted_debug_json_files')}",
        f"- deleted_runtime_dirs: {len(report.get('deleted_runtime_dirs') or [])}",
        "",
        "## Deleted files",
    ]
    if not report.get("deleted_files"):
        lines.append("- none")
    for row in report.get("deleted_files") or []:
        lines.append(f"- {row['kind']} | {row['path']} | {fmt_size(int(row['size']))}")
    lines.extend(["", "## Deleted runtime dirs"])
    if not report.get("deleted_runtime_dirs"):
        lines.append("- none")
    for row in report.get("deleted_runtime_dirs") or []:
        lines.append(f"- {row['runtime_dir']} | {fmt_size(int(row['size']))}")
    lines.extend(["", "## Preserved dirs"])
    for name in report.get("preserved_dirs") or []:
        lines.append(f"- {name}")
    path.write_text("\n".join(lines) + "\n", "utf-8")


def run_cleanup(
    output_dir: Path,
    runtime_dir: Path = RUNTIME_DIR,
    keep_latest_engine: int = 2,
    keep_latest_phase6b: int = 3,
    keep_latest_operator: int = 3,
    keep_latest_uat: int = 3,
    keep_latest_inspect: int = 1,
    delete_temp_audio: bool = False,
    delete_debug_draft_json: bool = False,
    prune_old_runtime_dirs: bool = False,
    keep_current_run: bool = True,
    dry_run: bool = True,
    execute: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    plan = build_cleanup_plan(
        runtime_dir=runtime_dir,
        output_dir=output_dir,
        keep_latest_engine=keep_latest_engine,
        keep_latest_phase6b=keep_latest_phase6b,
        keep_latest_operator=keep_latest_operator,
        keep_latest_uat=keep_latest_uat,
        keep_latest_inspect=keep_latest_inspect,
        delete_temp_audio=delete_temp_audio,
        delete_debug_draft_json=delete_debug_draft_json,
        prune_old_runtime_dirs=prune_old_runtime_dirs,
        keep_current_run=keep_current_run,
    )
    write_json(output_dir / "cleanup_plan.json", plan)
    write_cleanup_plan_md(output_dir / "cleanup_plan.md", plan)
    if execute and not dry_run:
        report = execute_cleanup(plan, runtime_dir)
        report["dry_run"] = False
    else:
        report = dry_run_report(plan)
    write_json(output_dir / "cleanup_report.json", report)
    write_cleanup_report_md(output_dir / "cleanup_report.md", report)
    return plan, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Retention-based cleanup for A-Roll runtime temporary files.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, default=RUNTIME_DIR)
    parser.add_argument("--keep-latest-engine", type=int, default=2)
    parser.add_argument("--keep-latest-phase6b", type=int, default=3)
    parser.add_argument("--keep-latest-operator", type=int, default=3)
    parser.add_argument("--keep-latest-uat", type=int, default=3)
    parser.add_argument("--keep-latest-inspect", type=int, default=1)
    parser.add_argument("--delete-temp-audio", action="store_true")
    parser.add_argument("--delete-debug-draft-json", action="store_true")
    parser.add_argument("--prune-old-runtime-dirs", action="store_true")
    parser.add_argument("--keep-current-run", action="store_true", default=True)
    parser.add_argument("--no-keep-current-run", dest="keep_current_run", action="store_false")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    dry_run = args.dry_run or not args.execute
    plan, report = run_cleanup(
        output_dir=args.output_dir,
        runtime_dir=args.runtime_dir,
        keep_latest_engine=args.keep_latest_engine,
        keep_latest_phase6b=args.keep_latest_phase6b,
        keep_latest_operator=args.keep_latest_operator,
        keep_latest_uat=args.keep_latest_uat,
        keep_latest_inspect=args.keep_latest_inspect,
        delete_temp_audio=args.delete_temp_audio,
        delete_debug_draft_json=args.delete_debug_draft_json,
        prune_old_runtime_dirs=args.prune_old_runtime_dirs,
        keep_current_run=args.keep_current_run,
        dry_run=dry_run,
        execute=args.execute,
    )
    print("status=ok")
    print(f"cleanup_plan={args.output_dir / 'cleanup_plan.md'}")
    print(f"cleanup_report={args.output_dir / 'cleanup_report.md'}")
    print(f"file_delete_target_count={len(plan['file_delete_targets'])}")
    print(f"runtime_dir_delete_target_count={len(plan['runtime_dir_delete_targets'])}")
    print(f"estimated_space_freed={plan['estimated_space_freed_human']}")
    print(f"dry_run={report.get('dry_run')}")
    print(f"released_size={report.get('released_size_human')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
