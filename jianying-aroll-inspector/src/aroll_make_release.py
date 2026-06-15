from __future__ import annotations

import argparse
import re
import time
import zipfile
from pathlib import Path
from typing import Any

from aroll_runtime_paths import get_release_dir
from aroll_runtime_mode import fmt_size
from jy_bridge import write_json


TOOL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELEASE_DIR = get_release_dir()

ROOT_FILE_ALLOWLIST = {
    "README_UAT.md",
    "README.md",
    "AGENTS.md",
    ".env.example",
    "run_aroll_operator.ps1",
    "run_aroll_uat_full.ps1",
    "run_aroll_cleanup_runtime.ps1",
    "run_aroll_inspect.ps1",
    "run_aroll_make_dev_snapshot.ps1",
}

SRC_FILE_ALLOWLIST = {
    "aroll_adjacent_boundary_guard.py",
    "aroll_attached_effects_preservation.py",
    "aroll_audio_enhancement.py",
    "aroll_candidate_discovery.py",
    "aroll_cleanup_runtime.py",
    "aroll_codex_self_review.py",
    "aroll_contract_check.py",
    "aroll_decision_merger.py",
    "aroll_decision_plan_builder.py",
    "aroll_display_subtitle_planner.py",
    "aroll_downstream_repair_pipeline.py",
    "aroll_duplicate_family_guard.py",
    "aroll_final_audit_candidate_adapter.py",
    "aroll_final_repeat_gate.py",
    "aroll_final_residual_repeat_auditor.py",
    "aroll_final_target_repeat_repair.py",
    "aroll_gate_runner.py",
    "aroll_hidden_audio_repeat_gate.py",
    "aroll_hidden_repeat_repair.py",
    "aroll_inspect.py",
    "aroll_intra_segment_breath_cutter.py",
    "aroll_llm_semantic_overlap_arbiter.py",
    "aroll_make_dev_snapshot.py",
    "aroll_runtime_paths.py",
    "aroll_multi_material_audio_audit.py",
    "aroll_operator.py",
    "aroll_operator_profile.py",
    "aroll_pause_tightening_pass.py",
    "aroll_poc_writer.py",
    "aroll_postwrite_audio_audit.py",
    "aroll_repeat_detector.py",
    "aroll_repeat_fix_planner.py",
    "aroll_repair_applier.py",
    "aroll_repair_proposal.py",
    "aroll_report_utils.py",
    "aroll_runtime_mode.py",
    "aroll_safe_cut_boundary_gate.py",
    "aroll_safe_cut_boundary_resolver.py",
    "aroll_safe_gap_cutter.py",
    "aroll_script_reference_matcher.py",
    "aroll_semantic_arbiter_prompt.py",
    "aroll_semantic_arbiter_schema.py",
    "aroll_semantic_coverage_gate.py",
    "aroll_semantic_guard.py",
    "aroll_semantic_llm_arbiter.py",
    "aroll_semantic_overlap_trimmer.py",
    "aroll_sentence_gap_compressor.py",
    "aroll_shared_edit_utils.py",
    "aroll_source_draft_integrity_gate.py",
    "aroll_speed_mapping.py",
    "aroll_speed_self_test.py",
    "aroll_subtitle_coverage_gate.py",
    "aroll_subtitle_interval_guard.py",
    "aroll_subtitle_style_integrity_gate.py",
    "aroll_take_clusterer.py",
    "aroll_text_normalize.py",
    "aroll_tiny_segment_guard.py",
    "aroll_uat_full.py",
    "aroll_video_speech_units.py",
    "aroll_word_timeline.py",
    "deepseek_client.py",
    "jy_bridge.py",
    # Current production engine entry. Kept until renamed in a later cleanup.
    "aroll_phase4e_full_aroll.py",
}

PROFILE_ALLOWLIST = {
    "default_profile.json",
    "production.json",
}

CONFIG_ALLOWLIST = {
    "runtime_paths.example.yaml",
}

DOC_ALLOWLIST = {
    "CODEX_ROLES.md",
    "IDEA_SETUP.md",
    "PROJECT_LAYOUT.md",
    "RUNTIME_POLICY.md",
}

TOOL_ALLOWLIST = {
    "migrate_runtime.py",
}

EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".s16le", ".mp4", ".mov", ".png", ".jpg", ".jpeg", ".log", ".jsonl"}

FORBIDDEN_TERMS = [
    "颜值",
    "私域",
    "客户",
    "成交",
    "War Room",
    "Jackson",
    "D:\\idea-project",
    "D:\\video\\S16",
    "D:\\JianyingPro Drafts",
    "6月14日",
    "S16",
    "嘉豪",
    "评论区评论区",
    "你是极你们是",
    "受过的气",
    "随意",
    "肆意",
    "敢张就",
    "最后只",
    "才导致",
    "寻找",
    "API key",
    "token",
    "cookie",
    "password",
    "secret",
    ".env",
]


def is_debug_draft_json(path: Path) -> bool:
    name = path.name.lower()
    return name.startswith("draft_content") and (".dec." in name or ".enc." in name or name.endswith(".dec.json") or name.endswith(".enc.json"))


def should_exclude(path: Path) -> bool:
    path_text = path.as_posix()
    if "__pycache__" in path.parts or "runtime" in path.parts or "release" in path.parts or "audio_vad" in path.parts:
        return True
    if path.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    if is_debug_draft_json(path):
        return True
    if path_text.startswith("src/aroll_phase") and path.name != "aroll_phase4e_full_aroll.py":
        return True
    return False


def iter_release_files(tool_root: Path) -> list[Path]:
    files: list[Path] = []
    for name in ROOT_FILE_ALLOWLIST:
        path = tool_root / name
        if path.exists() and path.is_file() and not should_exclude(path.relative_to(tool_root)):
            files.append(path)
    src_dir = tool_root / "src"
    for name in SRC_FILE_ALLOWLIST:
        path = src_dir / name
        if path.exists() and path.is_file() and not should_exclude(path.relative_to(tool_root)):
            files.append(path)
    profiles_dir = tool_root / "profiles"
    if profiles_dir.exists():
        for name in PROFILE_ALLOWLIST:
            path = profiles_dir / name
            if path.exists() and path.is_file() and not should_exclude(path.relative_to(tool_root)):
                files.append(path)
    config_dir = tool_root / "config"
    if config_dir.exists():
        for name in CONFIG_ALLOWLIST:
            path = config_dir / name
            if path.exists() and path.is_file() and not should_exclude(path.relative_to(tool_root)):
                files.append(path)
    docs_dir = tool_root / "docs"
    if docs_dir.exists():
        for name in DOC_ALLOWLIST:
            path = docs_dir / name
            if path.exists() and path.is_file() and not should_exclude(path.relative_to(tool_root)):
                files.append(path)
    tools_dir = tool_root / "tools"
    if tools_dir.exists():
        for name in TOOL_ALLOWLIST:
            path = tools_dir / name
            if path.exists() and path.is_file() and not should_exclude(path.relative_to(tool_root)):
                files.append(path)
    return sorted(set(files), key=lambda p: str(p.relative_to(tool_root)).lower())


def _allowed_project_specific_file(rel: str) -> bool:
    return rel.replace("\\", "/") in {"README_UAT.md"}


def scan_forbidden_terms(files: list[Path], tool_root: Path) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for path in files:
        rel = path.relative_to(tool_root).as_posix()
        if _allowed_project_specific_file(rel) or rel == "src/aroll_make_release.py":
            continue
        try:
            text = path.read_text("utf-8")
        except UnicodeDecodeError:
            continue
        for term in FORBIDDEN_TERMS:
            if term == ".env":
                pattern = re.compile(r"(^|[\\/])\.env($|[\\/.\s])")
                matches = list(pattern.finditer(text))
            elif term in {"token", "cookie", "password", "secret", "API key"}:
                pattern = re.compile(rf"(?i)\b{re.escape(term)}\b\s*[:=]")
                matches = list(pattern.finditer(text))
            else:
                matches = [m for m in re.finditer(re.escape(term), text)]
            for match in matches:
                line = text.count("\n", 0, match.start()) + 1
                hits.append({"file": rel, "line": line, "term": term})
    return hits


def make_release(version: str, release_dir: Path = DEFAULT_RELEASE_DIR, tool_root: Path = TOOL_ROOT) -> dict[str, Any]:
    release_dir.mkdir(parents=True, exist_ok=True)
    safe_version = version.strip() or time.strftime("v%Y%m%d%H%M%S")
    zip_path = release_dir / f"jianying-aroll-inspector-{safe_version}.zip"
    files = iter_release_files(tool_root)
    names = [path.relative_to(tool_root).as_posix() for path in files]
    forbidden_term_hits = scan_forbidden_terms(files, tool_root)
    release_contains_runtime = any(name.startswith("runtime/") or "/runtime/" in name for name in names)
    current_engine_file = "src/aroll_phase4e_full_aroll.py" if "src/aroll_phase4e_full_aroll.py" in names else ""
    legacy_name_retained = bool(current_engine_file)
    release_contains_legacy_phase_scripts = any(name.startswith("src/aroll_phase") and name != current_engine_file for name in names)
    release_contains_project_specific_terms = bool(forbidden_term_hits)
    forbidden_hits = [
        name
        for name in names
        if name.startswith("runtime/")
        or "/runtime/" in name
        or name.startswith("audio_vad/")
        or "/audio_vad/" in name
        or name.endswith(".s16le")
        or (Path(name).name.lower().startswith("draft_content") and (".dec." in Path(name).name.lower() or ".enc." in Path(name).name.lower()))
    ]
    status = "ok"
    block_reasons: list[str] = []
    if release_contains_runtime:
        block_reasons.append("RELEASE_CONTAINS_RUNTIME")
    if release_contains_legacy_phase_scripts:
        block_reasons.append("RELEASE_CONTAINS_LEGACY_PHASE_SCRIPTS")
    if release_contains_project_specific_terms:
        block_reasons.append("RELEASE_CONTAINS_PROJECT_SPECIFIC_TERMS")
    if forbidden_hits:
        block_reasons.append("RELEASE_CONTAINS_FORBIDDEN_FILES")
    if block_reasons:
        status = "blocked"
    if status == "ok":
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in files:
                zf.write(path, path.relative_to(tool_root).as_posix())
        release_size = zip_path.stat().st_size
    else:
        if zip_path.exists():
            zip_path.unlink()
        release_size = 0
    report = {
        "status": status,
        "version": safe_version,
        "release_zip_path": str(zip_path) if status == "ok" else "",
        "release_size": release_size,
        "release_size_human": fmt_size(release_size),
        "file_count": len(files),
        "release_contains_runtime": release_contains_runtime,
        "release_contains_legacy_phase_scripts": release_contains_legacy_phase_scripts,
        "current_engine_file": current_engine_file,
        "legacy_name_retained": legacy_name_retained,
        "release_contains_project_specific_terms": release_contains_project_specific_terms,
        "forbidden_hits": forbidden_hits,
        "forbidden_term_hits": forbidden_term_hits,
        "block_reasons": block_reasons,
        "included_files": names,
    }
    write_json(release_dir / "release_report.json", report)
    if status != "ok":
        raise RuntimeError(f"RELEASE_BLOCKED:{block_reasons[:10]}:{forbidden_term_hits[:10]}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a clean A-Roll inspector release zip.")
    parser.add_argument("--version", default="v0.1.0")
    parser.add_argument("--release-dir", type=Path, default=DEFAULT_RELEASE_DIR)
    args = parser.parse_args()
    report = make_release(args.version, args.release_dir)
    print("status=ok")
    print(f"release_zip={report['release_zip_path']}")
    print(f"release_size={report['release_size_human']}")
    print(f"release_contains_runtime={str(report['release_contains_runtime']).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
