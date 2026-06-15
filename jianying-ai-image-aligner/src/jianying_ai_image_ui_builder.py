from __future__ import annotations

import argparse
import csv
import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from runtime_paths import get_runs_dir

try:
    from PIL import ImageGrab
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"Pillow/ImageGrab is required for screenshots: {exc}")


DEFAULT_OUTPUT_ROOT = get_runs_dir()
DEFAULT_IDS = ["02", "04", "06"]


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_ulong]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12
VK_RETURN = 0x0D
KEYEVENTF_KEYUP = 0x0002
SW_RESTORE = 9
SW_MAXIMIZE = 3
HWND_TOPMOST = wintypes.HWND(-1)
HWND_NOTOPMOST = wintypes.HWND(-2)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_SHOWWINDOW = 0x0040
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


@dataclass
class WindowInfo:
    hwnd: int
    pid: int
    title: str
    rect: tuple[int, int, int, int]


@dataclass
class ImageJob:
    image_id: str
    path: Path
    start_sec: float = 0.0
    duration_sec: float = 3.0


class JsonLogger:
    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.events_path = log_dir / "events.jsonl"
        self.csv_path = log_dir / "ui_builder_log.csv"
        self._csv_ready = False

    def event(self, step: str, status: str, **data: object) -> None:
        row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "step": step, "status": status, **data}
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def image_status(self, job: ImageJob, stage: str, status: str, reason: str = "") -> None:
        exists = self.csv_path.exists()
        with self.csv_path.open("a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            if not exists:
                writer.writerow(
                    [
                        "image_id",
                        "image_path",
                        "target_start_sec",
                        "target_duration_sec",
                        "stage",
                        "status",
                        "reason",
                    ]
                )
            writer.writerow(
                [
                    job.image_id,
                    str(job.path),
                    f"{job.start_sec:.3f}",
                    f"{job.duration_sec:.3f}",
                    stage,
                    status,
                    reason,
                ]
            )


def run_powershell(args: list[str]) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


def get_jianying_process_ids() -> list[int]:
    output = run_powershell(["-Command", "Get-Process JianyingPro -ErrorAction Stop | Select-Object -ExpandProperty Id"])
    return [int(line.strip()) for line in output.splitlines() if line.strip().isdigit()]


def enum_jianying_windows(pids: set[int]) -> list[WindowInfo]:
    windows: list[WindowInfo] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in pids:
            return True
        title_buffer = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title_buffer, 512)
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        title = title_buffer.value
        # Minimized Jianying windows can report a tiny off-screen rectangle.
        # Keep title-matched windows so foreground_jianying can restore them.
        title_matched = "剪映" in title or "Jianying" in title or "JianyingPro" in title
        if (width > 300 and height > 200) or title_matched:
            windows.append(
                WindowInfo(
                    hwnd=hwnd,
                    pid=pid.value,
                    title=title,
                    rect=(rect.left, rect.top, width, height),
                )
            )
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return sorted(windows, key=lambda item: item.rect[2] * item.rect[3], reverse=True)


def foreground_jianying(logger: JsonLogger) -> WindowInfo:
    pids = set(get_jianying_process_ids())
    windows = enum_jianying_windows(pids)
    if not windows:
        raise RuntimeError("JianyingPro process exists, but no visible main window was found")

    win = windows[0]
    hwnd = wintypes.HWND(win.hwnd)
    target_pid = wintypes.DWORD()
    target_thread = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid))
    foreground_before = user32.GetForegroundWindow()
    foreground_thread = user32.GetWindowThreadProcessId(foreground_before, None) if foreground_before else 0
    current_thread = kernel32.GetCurrentThreadId()
    user32.AttachThreadInput(current_thread, target_thread, True)
    if foreground_thread and foreground_thread != target_thread:
        user32.AttachThreadInput(current_thread, foreground_thread, True)
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.2)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.SetForegroundWindow(hwnd)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.2)
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
        time.sleep(0.5)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.SetForegroundWindow(hwnd)
    finally:
        if foreground_thread and foreground_thread != target_thread:
            user32.AttachThreadInput(current_thread, foreground_thread, False)
        user32.AttachThreadInput(current_thread, target_thread, False)
    time.sleep(0.8)

    foreground = user32.GetForegroundWindow()
    if foreground != hwnd.value:
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        click_x = rect.left + max(120, min(width - 120, width // 2))
        click_y = rect.top + max(120, min(height - 120, height // 2))
        logger.event(
            "window_retry_click",
            "start",
            expected=f"0x{hwnd.value:X}",
            actual=f"0x{foreground:X}",
            click=[click_x, click_y],
        )
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.ShowWindow(hwnd, SW_MAXIMIZE)
        time.sleep(0.2)
        user32.SetCursorPos(click_x, click_y)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.4)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        foreground = user32.GetForegroundWindow()
        if foreground != hwnd.value:
            raise RuntimeError(f"Foreground window is not Jianying. expected=0x{hwnd.value:X}, actual=0x{foreground:X}")

    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    win.rect = (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    logger.event("window", "ok", hwnd=f"0x{win.hwnd:X}", pid=win.pid, title=win.title, rect=win.rect)
    return win


def screenshot(log_dir: Path, name: str) -> Path:
    out = log_dir / name
    img = ImageGrab.grab()
    img.save(out)
    return out


def set_clipboard_text(text: str) -> None:
    # Use an STA clipboard call; Set-Clipboard can fail under some desktop hosts.
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-STA",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::SetText($args[0])",
            text,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def key_input(vk: int, keyup: bool = False) -> INPUT:
    item = INPUT()
    item.type = 1
    item.union.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if keyup else 0, 0, None)
    return item


def send_inputs(inputs: list[INPUT]) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise RuntimeError(f"SendInput sent {sent}/{len(inputs)} inputs")


def hotkey(*keys: int) -> None:
    inputs: list[INPUT] = []
    for key in keys:
        inputs.append(key_input(key, False))
    for key in reversed(keys):
        inputs.append(key_input(key, True))
    send_inputs(inputs)
    time.sleep(0.25)


def press(key: int) -> None:
    send_inputs([key_input(key, False), key_input(key, True)])
    time.sleep(0.25)


def apply_start_id(jobs: list[ImageJob], start_id: str) -> list[ImageJob]:
    marker = start_id.strip().zfill(2)
    if not marker:
        return jobs
    return [job for job in jobs if job.image_id >= marker]


def resolve_jobs(
    ai_dir: Path,
    ids: list[str],
    logger: JsonLogger,
    allow_first_existing: bool = False,
    start_id: str = "",
) -> list[ImageJob]:
    jobs: list[ImageJob] = []
    missing: list[str] = []
    for image_id in ids:
        matches = sorted(ai_dir.glob(f"S16-1_AI_{image_id}_*.png"))
        if not matches:
            missing.append(image_id)
            continue
        jobs.append(ImageJob(image_id=image_id, path=matches[0]))

    if missing and allow_first_existing:
        existing = sorted(ai_dir.glob("S16-1_AI_*.png"))
        jobs = [
            ImageJob(image_id=f"{index:02d}", path=path)
            for index, path in enumerate(existing[: len(ids)], start=1)
        ]
        jobs = apply_start_id(jobs, start_id)
        logger.event(
            "resolve_images",
            "fallback_first_existing",
            requested_ids=ids,
            missing_ids=missing,
            resolved=[str(job.path) for job in jobs],
        )
        return jobs

    if missing:
        logger.event("resolve_images", "failed", requested_ids=ids, missing_ids=missing, ai_dir=str(ai_dir))
        raise FileNotFoundError(f"Missing requested AI image ids: {', '.join(missing)}")

    jobs = apply_start_id(jobs, start_id)
    if not jobs:
        logger.event("resolve_images", "failed", requested_ids=ids, start_id=start_id, reason="no jobs after start-id")
        raise FileNotFoundError(f"No AI image jobs remain after start-id: {start_id}")
    logger.event("resolve_images", "ok", requested_ids=ids, start_id=start_id, resolved=[str(job.path) for job in jobs])
    return jobs


def write_plan(log_dir: Path, jobs: list[ImageJob]) -> Path:
    plan = log_dir / "poc_plan.csv"
    with plan.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["image_id", "image_path", "start_sec", "end_sec", "duration_sec", "matched_subtitle"])
        cursor = 0.0
        for job in jobs:
            job.start_sec = cursor
            job.duration_sec = 3.0
            writer.writerow([job.image_id, str(job.path), f"{cursor:.3f}", f"{cursor + 3.0:.3f}", "3.000", "POC"])
            cursor += 3.0
    return plan


def quote_for_file_dialog(paths: list[Path]) -> str:
    return " ".join(f'"{path}"' for path in paths)


def import_images(jobs: list[ImageJob], log_dir: Path, logger: JsonLogger) -> None:
    logger.event("save_project", "start")
    hotkey(VK_CONTROL, ord("S"))
    logger.event("save_project", "sent_ctrl_s")
    screenshot(log_dir, "10_after_save_hotkey.png")

    logger.event("import", "start", count=len(jobs))
    hotkey(VK_CONTROL, ord("I"))
    time.sleep(1.5)
    screenshot(log_dir, "20_after_ctrl_i.png")

    # The standard file dialog accepts quoted full paths in the File name field.
    set_clipboard_text(quote_for_file_dialog([job.path for job in jobs]))
    hotkey(VK_CONTROL, ord("V"))
    time.sleep(0.3)
    screenshot(log_dir, "21_after_paste_paths.png")
    press(VK_RETURN)
    time.sleep(4.0)
    screenshot(log_dir, "22_after_import_enter.png")

    for job in jobs:
        logger.image_status(job, "import", "requested")
    logger.event("import", "requested", count=len(jobs))


def guarded_run(args: argparse.Namespace) -> int:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_dir = args.output_root / f"ui_builder_poc_{stamp}"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = JsonLogger(log_dir)
    logger.event("start", "ok", argv=sys.argv[1:], log_dir=str(log_dir))

    try:
        win = foreground_jianying(logger)
        shot = screenshot(log_dir, "00_window_state.png")
        logger.event("screenshot", "ok", path=str(shot))

        ids = [part.strip().zfill(2) for part in args.ids.split(",") if part.strip()]
        jobs = resolve_jobs(args.ai_dir, ids, logger, args.allow_first_existing, args.start_id)
        plan = write_plan(log_dir, jobs)
        logger.event("plan", "ok", path=str(plan), count=len(jobs))

        if not args.assume_editor:
            logger.event(
                "guard_editor",
                "stopped",
                reason="--assume-editor was not provided; no keyboard or mouse construction steps were executed",
            )
            print("STOPPED_SAFE_GUARD")
            print(f"reason: --assume-editor not provided")
            print(f"log_dir: {log_dir}")
            print(f"screenshot: {shot}")
            print(f"plan: {plan}")
            return 2

        import_images(jobs, log_dir, logger)

        if not args.import_only:
            logger.event(
                "insert_timeline",
                "stopped",
                reason="timeline insertion is intentionally gated until editor screenshot landmarks are verified",
            )
            print("STOPPED_AFTER_IMPORT")
            print(f"log_dir: {log_dir}")
            return 3

        print("OK_IMPORT_REQUESTED")
        print(f"log_dir: {log_dir}")
        return 0
    except Exception as exc:
        logger.event("fatal", "failed", error=str(exc))
        print("FAILED")
        print(f"reason: {exc}")
        print(f"log_dir: {log_dir}")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UI builder POC for inserting independent AI images into Jianying.")
    parser.add_argument("--draft", type=Path, required=True)
    parser.add_argument("--ai-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--ids", default=",".join(DEFAULT_IDS), help="Comma-separated AI-only image ids, e.g. 02,04,06.")
    parser.add_argument("--start-id", default="", help="Resume marker for future batch runs.")
    parser.add_argument("--allow-first-existing", action="store_true", help="Use first existing images if requested ids are missing.")
    parser.add_argument("--assume-editor", action="store_true", help="Allow Ctrl+S/Ctrl+I only after human-verified editor screenshot.")
    parser.add_argument("--import-only", action="store_true", help="Stop after importing media into the current project.")
    args = parser.parse_args(argv)
    return guarded_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
