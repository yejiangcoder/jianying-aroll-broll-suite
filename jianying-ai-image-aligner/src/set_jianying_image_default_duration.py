from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from runtime_paths import get_runs_dir


TOOL_ROOT = Path(__file__).resolve().parents[1]
VENDOR = TOOL_ROOT / "vendor"
if VENDOR.exists():
    sys.path.insert(0, str(VENDOR))
    for extra in ["pywin32_system32", "win32", r"win32\lib", "pythonwin"]:
        extra_path = VENDOR / extra
        if extra_path.exists():
            sys.path.insert(0, str(extra_path))
            try:
                os.add_dll_directory(str(extra_path))
            except Exception:
                pass

from jianying_ai_image_ui_builder import JsonLogger, foreground_jianying, screenshot  # noqa: E402

try:
    import pyautogui  # noqa: E402
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"需要 pyautogui 才能设置剪映图片默认时长：{exc}")


DEFAULT_RUNTIME = get_runs_dir()
BASE_W = 3840
BASE_H = 2160


def scaled_xy(x: int, y: int) -> tuple[int, int]:
    screen_w, screen_h = pyautogui.size()
    return round(x * screen_w / BASE_W), round(y * screen_h / BASE_H)


def click_scaled(logger: JsonLogger, name: str, x: int, y: int, delay: float = 0.35) -> None:
    sx, sy = scaled_xy(x, y)
    logger.event("click", "start", name=name, xy=[sx, sy], base_xy=[x, y])
    pyautogui.click(sx, sy)
    time.sleep(delay)
    logger.event("click", "ok", name=name, xy=[sx, sy])


def find_cyan_button_center(image_path: Path) -> tuple[int, int] | None:
    """Find the large cyan Save button in Jianying settings screenshots."""
    import numpy as np

    from PIL import Image

    img = Image.open(image_path).convert("RGB")
    arr = np.array(img)
    mask = (arr[:, :, 1] > 150) & (arr[:, :, 2] > 120) & (arr[:, :, 0] < 100)
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    best: tuple[int, int, int, int, int] | None = None
    for y in range(h):
        xs = np.where(mask[y] & ~seen[y])[0]
        for x0 in xs:
            if seen[y, x0] or not mask[y, x0]:
                continue
            stack = [(int(x0), y)]
            seen[y, x0] = True
            min_x = max_x = int(x0)
            min_y = max_y = y
            count = 0
            while stack:
                x, yy = stack.pop()
                count += 1
                min_x = min(min_x, x)
                max_x = max(max_x, x)
                min_y = min(min_y, yy)
                max_y = max(max_y, yy)
                for nx, ny in ((x + 1, yy), (x - 1, yy), (x, yy + 1), (x, yy - 1)):
                    if 0 <= nx < w and 0 <= ny < h and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((nx, ny))
            width = max_x - min_x + 1
            height = max_y - min_y + 1
            if count > 1000 and width > 120 and height > 20:
                if best is None or count > best[0]:
                    best = (count, min_x, min_y, max_x, max_y)
    if best is None:
        return None
    _, min_x, min_y, max_x, max_y = best
    return (min_x + max_x) // 2, (min_y + max_y) // 2


def set_duration(args: argparse.Namespace) -> int:
    ts = time.strftime("%Y%m%d_%H%M%S")
    log_dir = DEFAULT_RUNTIME / f"set_image_default_duration_{ts}"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = JsonLogger(log_dir)
    logger.event("start", "ok", duration=args.duration, log_dir=str(log_dir))

    pyautogui.FAILSAFE = True
    foreground_jianying(logger)
    pyautogui.press("esc")
    time.sleep(0.2)
    before = screenshot(log_dir, "01_before.png")
    logger.event("screenshot", "ok", name="before", path=str(before))

    # Known-good maximized Jianying 10.7 positions. They are scaled from a
    # 3840x2160 reference screenshot and guarded by foreground/window checks.
    click_scaled(logger, "top_menu", 150, 25, 0.4)
    menu = screenshot(log_dir, "02_menu_open.png")
    logger.event("screenshot", "ok", name="menu_open", path=str(menu))

    click_scaled(logger, "global_settings", 162, 319, 0.9)
    settings = screenshot(log_dir, "03_settings_open.png")
    logger.event("screenshot", "ok", name="settings_open", path=str(settings))

    save_center = find_cyan_button_center(settings)
    if not save_center:
        raise RuntimeError("没有找到全局设置窗口里的保存按钮，停止，避免误点其他选项")
    logger.event("settings_geometry", "ok", save_center=list(save_center))

    # If settings opens on the Draft tab, the Save button is much higher. Move
    # to the Edit tab first; this is only navigation and does not change options.
    if save_center[1] < 1650:
        edit_tab_x = save_center[0] + 70
        edit_tab_y = save_center[1] - 944
        logger.event("settings_tab", "start", tab="edit", xy=[edit_tab_x, edit_tab_y])
        pyautogui.click(edit_tab_x, edit_tab_y)
        time.sleep(0.6)
        settings = screenshot(log_dir, "03b_edit_tab_open.png")
        logger.event("screenshot", "ok", name="edit_tab_open", path=str(settings))
        save_center = find_cyan_button_center(settings)
        if not save_center:
            raise RuntimeError("切到剪辑页后没有找到保存按钮，停止")
        logger.event("settings_geometry", "ok", save_center=list(save_center), after_tab="edit")

    # On the Edit tab, the image duration field is above Save by a stable offset.
    field_x = save_center[0] + 80
    field_y = save_center[1] - 1210
    logger.event("field", "start", name="image_default_duration", xy=[field_x, field_y])
    pyautogui.click(field_x, field_y)
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.1)
    pyautogui.write(str(args.duration), interval=0.03)
    time.sleep(0.3)
    entered = screenshot(log_dir, "04_duration_entered.png")
    logger.event("screenshot", "ok", name="duration_entered", path=str(entered))

    pyautogui.click(*save_center)
    logger.event("click", "ok", name="save_settings", xy=list(save_center))
    time.sleep(1.0)
    saved = screenshot(log_dir, "05_after_save.png")
    logger.event("screenshot", "ok", name="after_save", path=str(saved))

    if args.verify_reopen:
        click_scaled(logger, "top_menu_verify", 150, 25, 0.4)
        click_scaled(logger, "global_settings_verify", 162, 319, 0.9)
        verify = screenshot(log_dir, "06_verify_reopen.png")
        logger.event("screenshot", "ok", name="verify_reopen", path=str(verify))
        pyautogui.press("esc")
        time.sleep(0.3)
        closed = screenshot(log_dir, "07_verify_closed.png")
        logger.event("screenshot", "ok", name="verify_closed", path=str(closed))

    logger.event("done", "ok", duration=args.duration, log_dir=str(log_dir))
    print("OK_SET_IMAGE_DEFAULT_DURATION")
    print(f"duration: {args.duration}")
    print(f"log_dir: {log_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", default="1.3")
    parser.add_argument("--verify-reopen", action="store_true", default=True)
    parser.add_argument("--no-verify-reopen", dest="verify_reopen", action="store_false")
    args = parser.parse_args()
    return set_duration(args)


if __name__ == "__main__":
    raise SystemExit(main())
