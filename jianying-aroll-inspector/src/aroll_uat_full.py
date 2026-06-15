from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from aroll_attached_effects_preservation import inspect_attached_effects
from aroll_audio_enhancement import inspect_audio_enhancement
from aroll_cleanup_runtime import run_cleanup
from aroll_inspect import DEFAULT_RUNTIME, build_report as inspect_build_report
from aroll_phase4e_full_aroll import (
    DEFAULT_REPEAT_CLUSTERS,
    DEFAULT_V5_DIR,
    DEFAULT_WORD_TIMELINE,
    assert_jianying_closed,
    running_jianying_processes,
)
from aroll_poc_writer import get_track
from aroll_runtime_paths import get_aroll_runs_dir
from aroll_source_draft_integrity_gate import audit_source_draft_integrity
from aroll_speed_self_test import run_speed_mapping_self_test
from jy_bridge import DEFAULT_JY_DRAFTC, read_json, resolve_timeline_id, root_mirrors_timeline_id, write_json


TOOL_ROOT = Path(__file__).resolve().parents[1]


def copy_if_exists(src: Path, dst: Path, copied: list[str]) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        copied.append(str(dst))


def create_baseline_backup(draft_dir: Path, run_dir: Path, jy_draftc: Path) -> tuple[Path, list[str]]:
    timeline_id, _ = resolve_timeline_id(draft_dir, "")
    timeline_dir = draft_dir / "Timelines" / timeline_id
    backup_dir = run_dir / "baseline_backup"
    copied: list[str] = []
    copy_if_exists(timeline_dir / "draft_content.json", backup_dir / "timeline" / "draft_content.json", copied)
    copy_if_exists(timeline_dir / "template-2.tmp", backup_dir / "timeline" / "template-2.tmp", copied)
    copy_if_exists(draft_dir / "draft_content.json", backup_dir / "root" / "draft_content.json", copied)
    copy_if_exists(draft_dir / "template-2.tmp", backup_dir / "root" / "template-2.tmp", copied)
    if len(copied) < 2:
        raise RuntimeError(f"BASELINE_BACKUP_INCOMPLETE:{copied}")
    return backup_dir, copied


def run_preflight_inspect(args: argparse.Namespace, run_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    inspect_args = SimpleNamespace(
        draft_dir=args.draft_dir,
        timeline_name="",
        main_video_track_index=-1,
        main_material_path="",
        jy_draftc=args.jy_draftc,
        runtime=run_dir / "inspect_runtime",
        max_allowed_speed=args.max_allowed_speed,
    )
    _inspect_dir, report_path, _subtitle_path = inspect_build_report(inspect_args)
    inspect_report = read_json(report_path)
    draft_content = read_json(Path(inspect_report["draft_content_dec_path"]))
    selected_main = inspect_report.get("selected_main_video_track") or {}
    main_track = get_track(draft_content, str(selected_main.get("track_id") or "")) if selected_main else None
    subtitles = read_json(Path(inspect_report["runtime_dir"]) / "subtitle_timeline.json")
    speed_self_test = run_speed_mapping_self_test(main_track or {}, subtitles, args.max_allowed_speed)
    audio_report = inspect_audio_enhancement(
        draft_content,
        selected_main,
        inspect_report.get("audio_tracks") or [],
        inspect_report.get("filter_tracks") or [],
    )
    attached_report = inspect_attached_effects(draft_content, selected_main)
    speed_report = inspect_report.get("selected_main_video_track") or {}
    write_json(run_dir / "uat_preflight_report.json", inspect_report)
    write_json(run_dir / "speed_report.json", speed_report)
    write_json(run_dir / "speed_mapping_self_test.json", speed_self_test)
    write_json(run_dir / "audio_enhancement_report.json", audio_report)
    write_json(run_dir / "attached_effects_report.json", attached_report)
    return inspect_report, speed_report, speed_self_test, audio_report, attached_report


def build_uat_gate(
    process_running: bool,
    backup_available: bool,
    inspect_report: dict[str, Any],
    speed_report: dict[str, Any],
    audio_report: dict[str, Any],
    attached_report: dict[str, Any],
    speed_self_test: dict[str, Any],
    allow_constant_speed: bool,
    source_integrity_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_integrity_report = source_integrity_report or {}
    fatal_reasons: list[str] = []
    if process_running:
        fatal_reasons.append("JIANYING_PROCESS_RUNNING_REFUSE_DRAFT_WRITE")
    selected_main = inspect_report.get("selected_main_video_track") or {}
    selected_text = next((row for row in inspect_report.get("text_tracks") or [] if row.get("selected_as_subtitle_track")), {})
    speed_requires_mapping = bool(speed_report.get("speed_requires_mapping"))
    if speed_requires_mapping and not allow_constant_speed:
        fatal_reasons.append("CONSTANT_SPEED_REQUIRES_ALLOW_CONSTANT_SPEED")
    if speed_requires_mapping and allow_constant_speed:
        if not speed_self_test.get("passed"):
            fatal_reasons.append("SPEED_MAPPING_SELF_TEST_FAILED")
            fatal_reasons.extend(speed_self_test.get("fatal_reasons") or [])
    if not speed_report.get("speed_supported", True):
        fatal_reasons.append("SPEED_UNSUPPORTED")
    if audio_report.get("fatal_reasons"):
        fatal_reasons.extend(audio_report.get("fatal_reasons") or [])
    if attached_report.get("fatal_reasons"):
        fatal_reasons.extend(attached_report.get("fatal_reasons") or [])
    if source_integrity_report.get("fatal_reasons"):
        fatal_reasons.extend(source_integrity_report.get("fatal_reasons") or [])
    if not selected_main:
        fatal_reasons.append("MAIN_VIDEO_TRACK_NOT_FOUND")
    if not selected_text:
        fatal_reasons.append("SUBTITLE_TRACK_NOT_FOUND")
    for reason in inspect_report.get("fatal_reasons") or []:
        if reason in {
            "MAIN_VIDEO_SPEED_REQUIRES_MAPPING",
            "MAIN_VIDEO_HAS_NON_1X_SPEED",
            "MAIN_VIDEO_SPEED_UNSAFE",
            "MAIN_VIDEO_HAS_UNRECOGNIZED_ATTACHED_EFFECT_REFS",
        }:
            continue
        fatal_reasons.append(str(reason))

    gate = {
        "jianying_process_running": process_running,
        "draft_backup_available": backup_available,
        "main_video_track_detected": bool(selected_main),
        "subtitle_track_detected": bool(selected_text),
        "audio_track_supported": bool(audio_report.get("audio_track_supported")),
        "filter_track_supported": bool(audio_report.get("filter_track_supported")),
        "speed_supported": bool(speed_report.get("speed_supported", True)),
        "speed_mapping_validated": (not speed_requires_mapping) or bool(speed_self_test.get("passed")),
        "attached_effects_gate_passed": not bool(attached_report.get("fatal_reasons")),
        "source_draft_integrity_gate_passed": bool(source_integrity_report.get("source_draft_integrity_gate_passed", True)),
        "detected_as_processed_aroll_output": bool(source_integrity_report.get("detected_as_processed_aroll_output")),
        "source_duration_ratio": source_integrity_report.get("source_duration_ratio"),
        "subtitle_count_ratio": source_integrity_report.get("subtitle_count_ratio"),
        "attached_ref_count": int(attached_report.get("attached_ref_count") or 0),
        "unknown_uncloneable_ref_count": int(attached_report.get("unknown_uncloneable_ref_count") or 0),
        "semantic_coverage_passed": None,
        "duplicate_family_guard_passed": None,
        "multi_material_audio_audit_valid": None,
        "subtitle_interval_overlap_count": None,
        "overlong_subtitle_count": None,
        "single_char_subtitle_count": None,
        "fatal_reasons": sorted(set(fatal_reasons)),
    }
    gate["uat_gate_passed"] = not gate["fatal_reasons"]
    return gate


def write_blocked_report(
    run_dir: Path,
    gate: dict[str, Any],
    inspect_report: dict[str, Any],
    speed_report: dict[str, Any],
    audio_report: dict[str, Any],
    attached_report: dict[str, Any],
) -> None:
    blocked = {
        "status": "blocked",
        "uat_gate": gate,
        "inspect_report_path": inspect_report.get("runtime_dir"),
        "speed_report": speed_report,
        "audio_enhancement_report": audio_report,
        "attached_effects_report": attached_report,
        "writeback_performed": False,
    }
    write_json(run_dir / "uat_blocked_report.json", blocked)


def run_phase4e(args: argparse.Namespace, run_dir: Path, backup_dir: Path) -> int:
    command = [
        sys.executable,
        str(TOOL_ROOT / "src" / "aroll_phase4e_full_aroll.py"),
        "--draft-dir",
        str(args.draft_dir),
        "--backup-dir",
        str(backup_dir),
        "--jy-draftc",
        str(args.jy_draftc),
        "--runtime",
        str(args.runtime),
        "--run-dir",
        str(run_dir),
        "--runtime-prefix",
        "aroll_uat_full",
        "--runtime-mode",
        args.runtime_mode,
    ]
    if args.v5_dir:
        command.extend(["--v5-dir", str(args.v5_dir)])
    if args.repeat_clusters:
        command.extend(["--repeat-clusters", str(args.repeat_clusters)])
    if args.word_timeline:
        command.extend(["--word-timeline", str(args.word_timeline)])
    preflight = read_json(run_dir / "uat_preflight_report.json") if (run_dir / "uat_preflight_report.json").exists() else {}
    selected_main = preflight.get("selected_main_video_track") or {}
    selected_text = next((row for row in preflight.get("text_tracks") or [] if row.get("selected_as_subtitle_track")), {})
    if args.backup_dir is None and selected_main.get("total_target_duration_us") is not None:
        command.extend(["--expected-duration-us", str(int(selected_main.get("total_target_duration_us") or 0))])
    if args.backup_dir is None and selected_text.get("segment_count") is not None:
        command.extend(["--expected-subtitle-count", str(int(selected_text.get("segment_count") or 0))])
    if args.script_path:
        command.extend(["--script-path", str(args.script_path)])
    if args.keep_debug_dec_json:
        command.append("--keep-debug-dec-json")
    if args.keep_audio_pcm:
        command.append("--keep-audio-pcm")
    if args.allow_constant_speed:
        command.append("--allow-constant-speed")
    command.extend(["--max-allowed-speed", str(args.max_allowed_speed)])
    completed = subprocess.run(command, cwd=str(TOOL_ROOT), text=True, capture_output=True, check=False)
    (run_dir / "phase4e_stdout.txt").write_text(completed.stdout or "", "utf-8")
    (run_dir / "phase4e_stderr.txt").write_text(completed.stderr or "", "utf-8")
    return completed.returncode


def alias_uat_reports(run_dir: Path) -> None:
    aliases = {
        "full_gate_check.json": "gate_check.json",
        "full_subtitle_readability_report.json": "subtitle_readability_report.json",
    }
    for src_name, dst_name in aliases.items():
        src = run_dir / src_name
        if src.exists():
            (run_dir / dst_name).write_bytes(src.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser(description="Formal UAT entry for full A-Roll writeback.")
    parser.add_argument("--draft-dir", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, default=None)
    parser.add_argument("--script-path", type=Path, default=None)
    parser.add_argument("--runtime-mode", choices=["production", "debug"], default="production")
    parser.add_argument("--allow-constant-speed", dest="allow_constant_speed", action="store_true", default=True)
    parser.add_argument("--no-allow-constant-speed", dest="allow_constant_speed", action="store_false")
    parser.add_argument("--max-allowed-speed", type=float, default=1.25)
    parser.add_argument("--keep-debug-dec-json", action="store_true")
    parser.add_argument("--keep-audio-pcm", action="store_true")
    parser.add_argument("--run-cleanup-before", action="store_true", default=True)
    parser.add_argument("--no-run-cleanup-before", action="store_false", dest="run_cleanup_before")
    parser.add_argument("--run-cleanup-after", action="store_true", default=True)
    parser.add_argument("--no-run-cleanup-after", action="store_false", dest="run_cleanup_after")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--v5-dir", type=Path, default=DEFAULT_V5_DIR)
    parser.add_argument("--repeat-clusters", type=Path, default=DEFAULT_REPEAT_CLUSTERS)
    parser.add_argument("--word-timeline", type=Path, default=DEFAULT_WORD_TIMELINE)
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=get_aroll_runs_dir())
    args = parser.parse_args()

    run_dir = args.runtime / f"aroll_phase6b_llm_first_decision_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    if args.run_cleanup_before:
        run_cleanup(
            output_dir=run_dir / "cleanup_before",
            dry_run=True,
            execute=False,
            delete_temp_audio=True,
            delete_debug_draft_json=True,
        )

    process_running = bool(running_jianying_processes())
    backup_available = False
    backup_dir = args.backup_dir
    backup_paths: list[str] = []

    inspect_report, speed_report, speed_self_test, audio_report, attached_report = run_preflight_inspect(args, run_dir)
    draft_content = read_json(Path(inspect_report["draft_content_dec_path"]))
    source_integrity_report = audit_source_draft_integrity(
        inspect_report,
        draft_content,
        output_path=run_dir / "source_draft_integrity_report.json",
    )
    if not process_running and source_integrity_report.get("source_draft_integrity_gate_passed"):
        if backup_dir:
            backup_available = backup_dir.exists()
        else:
            backup_dir, backup_paths = create_baseline_backup(args.draft_dir, run_dir, args.jy_draftc)
            backup_available = True
    gate = build_uat_gate(
        process_running,
        backup_available,
        inspect_report,
        speed_report,
        audio_report,
        attached_report,
        speed_self_test,
        args.allow_constant_speed,
        source_integrity_report,
    )
    gate["baseline_backup_dir"] = str(backup_dir) if backup_dir else ""
    gate["baseline_backup_paths"] = backup_paths
    write_json(run_dir / "uat_gate_check.json", gate)

    if not gate["uat_gate_passed"]:
        write_blocked_report(run_dir, gate, inspect_report, speed_report, audio_report, attached_report)
        print("status=blocked")
        print(f"runtime={run_dir}")
        print(f"blocked_report={run_dir / 'uat_blocked_report.json'}")
        print("fatal_reasons=" + ",".join(gate["fatal_reasons"]))
        return 0

    if args.preflight_only:
        write_json(
            run_dir / "uat_preflight_only_report.json",
            {
                "status": "preflight_passed",
                "writeback_performed": False,
                "uat_gate": gate,
            },
        )
        print("status=preflight_passed")
        print(f"runtime={run_dir}")
        print(f"preflight_only_report={run_dir / 'uat_preflight_only_report.json'}")
        return 0

    assert_jianying_closed()
    rc = run_phase4e(args, run_dir, backup_dir or Path())
    alias_uat_reports(run_dir)
    if args.run_cleanup_after:
        _cleanup_plan, cleanup_report = run_cleanup(
            output_dir=run_dir / "cleanup_after",
            dry_run=False,
            execute=True,
            delete_temp_audio=True,
            delete_debug_draft_json=True,
        )
        write_json(run_dir / "cleanup_report.json", cleanup_report)
    else:
        write_json(run_dir / "cleanup_report.json", {"dry_run": True, "skipped": "run_cleanup_after_disabled"})
    write_json(run_dir / "release_report.json", {"status": "skipped", "reason": "release build is not part of UAT runtime"})
    if rc != 0:
        write_json(run_dir / "uat_blocked_report.json", {"status": "phase4e_failed", "returncode": rc, "writeback_attempted": True})
        print("status=failed")
        print(f"runtime={run_dir}")
        print(f"stderr={run_dir / 'phase4e_stderr.txt'}")
        return rc

    print("status=ok")
    print(f"runtime={run_dir}")
    print(f"write_report={run_dir / 'write_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
