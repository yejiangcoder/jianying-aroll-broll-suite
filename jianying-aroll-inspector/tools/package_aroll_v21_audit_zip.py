from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


INCLUDE_ROOTS = {
    "src",
    "tests",
    "tools",
    "docs",
    "fixtures",
}

INCLUDE_FILES = {
    "run_aroll_v21_operator.ps1",
    "README.md",
    "README_UAT.md",
    "requirements.txt",
    "pyproject.toml",
    "AGENTS.md",
}

EXCLUDED_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    ".pytest_cache",
    "__pycache__",
    ".venv",
    "venv",
    "runtime",
    "run_dir",
}

EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".log",
    ".mp4",
    ".mov",
    ".mp3",
    ".wav",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}

EXCLUDED_NAMES = {
    ".env",
    "draft_content.json",
    "migration_dry_run_report.json",
    "migration_dry_run_report.md",
    "project_layering_report.json",
    "project_layering_report.md",
    "project_tree_scan_report.json",
    "project_tree_scan_report.md",
    "template-2.tmp",
    "runtime_migration_plan.json",
    "runtime_migration_plan.md",
}


def should_include(path: Path, repo_root: Path) -> bool:
    rel = path.relative_to(repo_root)
    parts = set(rel.parts)
    if parts & EXCLUDED_DIRS:
        return False
    if path.name in EXCLUDED_NAMES:
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if rel.parts[0] in INCLUDE_ROOTS:
        return True
    return str(rel) in INCLUDE_FILES


def build_zip(repo_root: Path, output_zip: Path) -> list[str]:
    repo_root = repo_root.resolve()
    output_zip = output_zip.resolve()
    names: list[str] = []
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(repo_root.rglob("*")):
            if not path.is_file():
                continue
            if path.resolve() == output_zip:
                continue
            if not should_include(path, repo_root):
                continue
            arcname = str(path.relative_to(repo_root)).replace("\\", "/")
            zf.write(path, arcname)
            names.append(arcname)
    return names


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a clean A-Roll V21 architecture audit zip.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-zip", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    names = build_zip(args.repo_root, args.output_zip)
    print(f"wrote={args.output_zip}")
    print(f"file_count={len(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
