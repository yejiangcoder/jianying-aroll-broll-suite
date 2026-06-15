from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from aroll_cleanup_runtime import run_cleanup
from aroll_operator_profile import TOOL_ROOT, bool_profile, load_operator_profile, resolve_draft_dir
from aroll_runtime_paths import get_aroll_runs_dir


RUNTIME_DIR = get_aroll_runs_dir()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text("utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def parse_key_value_output(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def close_jianying_processes() -> dict[str, Any]:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "$targets = @(Get-Process | Where-Object "
            "{$_.ProcessName -like 'JianyingPro*' -or $_.ProcessName -like 'CapCut*' -or $_.ProcessName -like '*剪映*'}); "
            "$before = @($targets | Select-Object ProcessName,Id); "
            "foreach ($p in $targets) { try { [void]$p.CloseMainWindow() } catch {} }; "
            "Start-Sleep -Seconds 10; "
            "$remaining = @(Get-Process | Where-Object "
            "{$_.ProcessName -like 'JianyingPro*' -or $_.ProcessName -like 'CapCut*' -or $_.ProcessName -like '*剪映*'}); "
            "$forced = @($remaining | Select-Object ProcessName,Id); "
            "foreach ($p in $remaining) { try { Stop-Process -Id $p.Id -Force } catch {} }; "
            "[pscustomobject]@{graceful_attempted=$true; before=$before; forced=$forced} | ConvertTo-Json -Depth 4 -Compress"
        ),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def run_uat(profile: dict[str, Any], draft_dir: Path, intent: str, operator_run_dir: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        str(TOOL_ROOT / "src" / "aroll_uat_full.py"),
        "--draft-dir",
        str(draft_dir),
        "--runtime-mode",
        str(profile.get("runtime_mode") or "production"),
        "--max-allowed-speed",
        str(profile.get("max_allowed_speed") or 1.25),
    ]
    if bool_profile(profile, "allow_constant_speed", True):
        command.append("--allow-constant-speed")
    else:
        command.append("--no-allow-constant-speed")
    if not bool_profile(profile, "run_cleanup_before", True):
        command.append("--no-run-cleanup-before")
    if not bool_profile(profile, "run_cleanup_after", True):
        command.append("--no-run-cleanup-after")
    script_path = str(profile.get("default_script_path") or "")
    if script_path:
        command.extend(["--script-path", script_path])
    if bool_profile(profile, "keep_debug_dec_json", False):
        command.append("--keep-debug-dec-json")
    if bool_profile(profile, "keep_audio_pcm", False):
        command.append("--keep-audio-pcm")
    if intent == "PreflightOnly" or bool_profile(profile, "preflight_only", False):
        command.append("--preflight-only")

    completed = subprocess.run(command, cwd=str(TOOL_ROOT), text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    (operator_run_dir / "uat_stdout.txt").write_text(completed.stdout or "", "utf-8")
    (operator_run_dir / "uat_stderr.txt").write_text(completed.stderr or "", "utf-8")
    parsed = parse_key_value_output((completed.stdout or "") + "\n" + (completed.stderr or ""))
    return {
        "returncode": completed.returncode,
        "command": command,
        "stdout_path": str(operator_run_dir / "uat_stdout.txt"),
        "stderr_path": str(operator_run_dir / "uat_stderr.txt"),
        "parsed_output": parsed,
    }


def legacy_run_uat_command(profile: dict[str, Any], draft_dir: Path, intent: str) -> list[str]:
    command = [
        str(TOOL_ROOT / "run_aroll_uat_full.ps1"),
        "-DraftDir",
        str(draft_dir),
        "-RuntimeMode",
        str(profile.get("runtime_mode") or "production"),
        "-AllowConstantSpeed",
        "$true" if bool_profile(profile, "allow_constant_speed", True) else "$false",
        "-MaxAllowedSpeed",
        str(profile.get("max_allowed_speed") or 1.25),
        "-RunCleanupBefore",
        "$true" if bool_profile(profile, "run_cleanup_before", True) else "$false",
        "-RunCleanupAfter",
        "$true" if bool_profile(profile, "run_cleanup_after", True) else "$false",
    ]
    script_path = str(profile.get("default_script_path") or "")
    if script_path:
        command.extend(["-ScriptPath", script_path])
    if bool_profile(profile, "keep_debug_dec_json", False):
        command.append("-KeepDebugDecJson")
    if bool_profile(profile, "keep_audio_pcm", False):
        command.append("-KeepAudioPcm")
    if intent == "PreflightOnly" or bool_profile(profile, "preflight_only", False):
        command.append("-PreflightOnly")
    return command


def summarize_uat(uat_result: dict[str, Any]) -> dict[str, Any]:
    parsed = uat_result.get("parsed_output") or {}
    runtime = Path(str(parsed.get("runtime") or ""))
    if not parsed.get("runtime"):
        runtime = Path()
    gate = read_json(runtime / "uat_gate_check.json") if runtime else {}
    write_report = read_json(runtime / "write_report.json") if runtime else {}
    blocked_report = read_json(runtime / "uat_blocked_report.json") if runtime else {}
    attached = read_json(runtime / "attached_effects_report.json") if runtime else {}
    speed = read_json(runtime / "speed_report.json") if runtime else {}
    status = str(parsed.get("status") or ("failed" if uat_result.get("returncode") else "unknown"))
    human_review_focus = runtime / "human_review_focus.md" if runtime else Path()
    write_report_path = runtime / "write_report.json" if runtime else Path()
    gate_check_path = runtime / "uat_gate_check.json" if runtime else Path()
    blocked_report_path = runtime / "uat_blocked_report.json" if runtime else Path()
    preflight_only_report_path = runtime / "uat_preflight_only_report.json" if runtime else Path()
    return {
        "status": status,
        "runtime": str(runtime) if runtime else "",
        "gate": gate,
        "write_report": write_report,
        "blocked_report": blocked_report,
        "attached_effects_report": attached,
        "speed_report": speed,
        "fatal_reasons": gate.get("fatal_reasons") or [],
        "writeback_performed": bool(write_report.get("status") == "ok"),
        "final_duration_s": write_report.get("final_duration_s"),
        "human_review_focus": str(human_review_focus) if human_review_focus.exists() else "",
        "write_report_path": str(write_report_path) if write_report_path.exists() else "",
        "gate_check_path": str(gate_check_path) if gate_check_path.exists() else "",
        "blocked_report_path": str(blocked_report_path) if blocked_report_path.exists() else "",
        "preflight_only_report_path": str(preflight_only_report_path) if preflight_only_report_path.exists() else "",
    }


def run_cleanup_intent(operator_run_dir: Path) -> dict[str, Any]:
    plan, report = run_cleanup(
        output_dir=operator_run_dir / "cleanup",
        keep_latest_engine=2,
        keep_latest_phase6b=3,
        keep_latest_operator=3,
        keep_latest_uat=3,
        keep_latest_inspect=1,
        delete_temp_audio=True,
        delete_debug_draft_json=True,
        prune_old_runtime_dirs=True,
        keep_current_run=True,
        dry_run=False,
        execute=True,
    )
    return {"plan": plan, "report": report}


def print_operator_summary(profile: dict[str, Any], draft_dir: Path, intent: str, summary: dict[str, Any]) -> None:
    status = summary.get("status") or "unknown"
    fatal = summary.get("fatal_reasons") or []
    if status in {"ok", "preflight_passed"}:
        label = "A-Roll 预检通过" if intent == "PreflightOnly" else "A-Roll 已完成"
    elif status == "blocked":
        label = "A-Roll 阻塞"
    else:
        label = "A-Roll 失败"
    print(label)
    print(f"草稿：{draft_dir}")
    print(f"是否写回：{'是' if summary.get('writeback_performed') else '否'}")
    if summary.get("final_duration_s") is not None:
        print(f"最终时长：{summary.get('final_duration_s')} s")
    gate_passed = status in {"ok", "preflight_passed"} and not fatal
    print(f"Gate：{'通过' if gate_passed else '失败'}")
    if fatal:
        print("阻塞原因：" + ",".join(str(item) for item in fatal))
    print(f"默认变速支持：allow_constant_speed={bool_profile(profile, 'allow_constant_speed', True)} max={profile.get('max_allowed_speed')}")
    if summary.get("human_review_focus"):
        print(f"验收重点：{summary.get('human_review_focus')}")
    if summary.get("write_report_path"):
        print(f"write_report：{summary.get('write_report_path')}")
    if summary.get("blocked_report_path"):
        print(f"blocked_report：{summary.get('blocked_report_path')}")
    if summary.get("preflight_only_report_path"):
        print(f"preflight_report：{summary.get('preflight_only_report_path')}")
    if summary.get("gate_check_path"):
        print(f"gate_check：{summary.get('gate_check_path')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Operator entry for A-Roll production workflow.")
    parser.add_argument("--intent", choices=["RunFull", "PreflightOnly", "Cleanup"], default="RunFull")
    parser.add_argument("--draft-name", default="")
    parser.add_argument("--draft-dir", default="")
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--auto-close-jianying", action="store_true")
    args = parser.parse_args()

    profile = load_operator_profile(args.profile)
    operator_run_dir = RUNTIME_DIR / f"aroll_operator_{time.strftime('%Y%m%d_%H%M%S')}"
    operator_run_dir.mkdir(parents=True, exist_ok=True)

    if args.intent == "Cleanup":
        cleanup = run_cleanup_intent(operator_run_dir)
        write_json(operator_run_dir / "operator_summary.json", {"intent": args.intent, "cleanup": cleanup})
        print("A-Roll runtime 清理完成")
        print(f"输出目录：{operator_run_dir}")
        print(f"释放空间：{cleanup['report'].get('released_size_human')}")
        return 0

    draft_dir = resolve_draft_dir(profile, args.draft_name, args.draft_dir)
    if not draft_dir.exists():
        summary = {"status": "blocked", "fatal_reasons": [f"DRAFT_DIR_NOT_FOUND:{draft_dir}"]}
        write_json(operator_run_dir / "operator_summary.json", summary)
        print("A-Roll 阻塞")
        print(f"草稿不存在：{draft_dir}")
        print(f"输出目录：{operator_run_dir}")
        return 0

    auto_close = args.auto_close_jianying or bool_profile(profile, "auto_close_jianying", False)
    close_report = None
    if auto_close:
        close_report = close_jianying_processes()
        write_json(operator_run_dir / "auto_close_jianying_report.json", close_report)

    uat_result = run_uat(profile, draft_dir, args.intent, operator_run_dir)
    summary = summarize_uat(uat_result)
    summary.update(
        {
            "intent": args.intent,
            "draft_dir": str(draft_dir),
            "operator_runtime_dir": str(operator_run_dir),
            "auto_close_jianying": bool(auto_close),
            "auto_close_report": close_report,
            "uat_result": uat_result,
            "legacy_powershell_equivalent": legacy_run_uat_command(profile, draft_dir, args.intent),
            "profile": profile,
        }
    )
    write_json(operator_run_dir / "operator_summary.json", summary)
    print_operator_summary(profile, draft_dir, args.intent, summary)
    print(f"operator_summary：{operator_run_dir / 'operator_summary.json'}")
    return int(uat_result.get("returncode") or 0)


if __name__ == "__main__":
    raise SystemExit(main())
