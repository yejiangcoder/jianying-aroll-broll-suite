from __future__ import annotations

import argparse
import json
import time
import zipfile
from pathlib import Path
from typing import Any

from aroll_runtime_paths import get_dev_snapshot_dir
from aroll_runtime_mode import fmt_size
from jy_bridge import write_json


TOOL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT_DIR = get_dev_snapshot_dir()

ROOT_FILES = {
    "README.md",
    "README_UAT.md",
    "AGENTS.md",
    ".env.example",
    ".gitignore",
    "run_aroll_operator.ps1",
    "run_aroll_uat_full.ps1",
    "run_aroll_cleanup_runtime.ps1",
    "run_aroll_inspect.ps1",
    "run_aroll_make_release.ps1",
    "run_aroll_make_dev_snapshot.ps1",
}

SRC_FILES = {
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
    "aroll_make_release.py",
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
    "aroll_phase4e_full_aroll.py",
}

PROFILE_FILES = {
    "default_profile.json",
    "production.json",
}

CONFIG_FILES = {
    "runtime_paths.example.yaml",
}

EXCLUDED_PARTS = {"runtime", "release", "dev_snapshot", "__pycache__", "inspect_runtime"}
EXCLUDED_SUFFIXES = {".s16le", ".tmp", ".pyc", ".pyo", ".mp4", ".mov", ".png", ".jpg", ".jpeg", ".log", ".jsonl"}


def is_forbidden_artifact(path: Path) -> bool:
    name = path.name.lower()
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return True
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    if name.startswith("draft_content") and (".dec." in name or ".enc." in name or name.endswith(".dec.json") or name.endswith(".enc.json")):
        return True
    return False


def collect_files(tool_root: Path) -> list[Path]:
    files: list[Path] = []
    for name in ROOT_FILES:
        path = tool_root / name
        if path.exists() and path.is_file() and not is_forbidden_artifact(path.relative_to(tool_root)):
            files.append(path)
    src_dir = tool_root / "src"
    for name in SRC_FILES:
        path = src_dir / name
        if path.exists() and path.is_file() and not is_forbidden_artifact(path.relative_to(tool_root)):
            files.append(path)
    profiles_dir = tool_root / "profiles"
    for name in PROFILE_FILES:
        path = profiles_dir / name
        if path.exists() and path.is_file() and not is_forbidden_artifact(path.relative_to(tool_root)):
            files.append(path)
    config_dir = tool_root / "config"
    for name in CONFIG_FILES:
        path = config_dir / name
        if path.exists() and path.is_file() and not is_forbidden_artifact(path.relative_to(tool_root)):
            files.append(path)
    for folder in ("docs", "tools"):
        base = tool_root / folder
        if base.exists():
            for path in base.rglob("*"):
                if path.is_file() and not is_forbidden_artifact(path.relative_to(tool_root)):
                    files.append(path)
    tests_dir = tool_root / "tests"
    if tests_dir.exists():
        for path in tests_dir.rglob("*"):
            if path.is_file() and not is_forbidden_artifact(path.relative_to(tool_root)):
                files.append(path)
    return sorted(set(files), key=lambda p: p.relative_to(tool_root).as_posix().lower())


def sanitized_root_profile() -> str:
    profile = {
        "profile_name": "local_template",
        "default_draft_root": "EDIT_ME_DRAFT_ROOT",
        "default_draft_name": "EDIT_ME_DRAFT_NAME",
        "default_script_path": "",
        "allow_constant_speed": True,
        "max_allowed_speed": 1.25,
        "runtime_mode": "production",
        "run_cleanup_before": True,
        "run_cleanup_after": True,
        "keep_debug_dec_json": False,
        "keep_audio_pcm": False,
        "auto_close_jianying": False,
        "preflight_only": False,
    }
    return json.dumps(profile, ensure_ascii=False, indent=2) + "\n"


def build_dev_snapshot(snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR, tool_root: Path = TOOL_ROOT) -> dict[str, Any]:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    zip_path = snapshot_dir / f"jianying-aroll-inspector-dev-snapshot-{stamp}.zip"
    files = collect_files(tool_root)
    names = [path.relative_to(tool_root).as_posix() for path in files]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, path.relative_to(tool_root).as_posix())
        zf.writestr("aroll_operator_profile.json", sanitized_root_profile())
    with zipfile.ZipFile(zip_path, "r") as zf:
        zipped_names = zf.namelist()
    report = {
        "status": "ok",
        "dev_snapshot_path": str(zip_path),
        "dev_snapshot_size": zip_path.stat().st_size,
        "dev_snapshot_size_human": fmt_size(zip_path.stat().st_size),
        "file_count": len(zipped_names),
        "runtime_in_dev_snapshot": any(name.startswith("runtime/") or "/runtime/" in name for name in zipped_names),
        "release_in_dev_snapshot": any(name.startswith("release/") or "/release/" in name for name in zipped_names),
        "inspect_runtime_in_dev_snapshot": any("inspect_runtime/" in name or name.startswith("inspect_runtime/") for name in zipped_names),
        "debug_draft_json_in_dev_snapshot": any(Path(name).name.lower().startswith("draft_content") and (".dec." in Path(name).name.lower() or ".enc." in Path(name).name.lower()) for name in zipped_names),
        "included_files": zipped_names,
        "excluded_legacy_note": "Snapshot intentionally includes production/review source files only; legacy phase PoC scripts are excluded.",
    }
    write_json(snapshot_dir / "dev_snapshot_report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a reviewable A-Roll dev snapshot without runtime artifacts.")
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    args = parser.parse_args()
    report = build_dev_snapshot(args.snapshot_dir)
    print("status=ok")
    print(f"dev_snapshot={report['dev_snapshot_path']}")
    print(f"dev_snapshot_size={report['dev_snapshot_size_human']}")
    print(f"runtime_in_dev_snapshot={str(report['runtime_in_dev_snapshot']).lower()}")
    print(f"release_in_dev_snapshot={str(report['release_in_dev_snapshot']).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
