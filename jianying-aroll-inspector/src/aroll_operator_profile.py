from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TOOL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_PATH = TOOL_ROOT / "aroll_operator_profile.json"
DEFAULT_RELEASE_PROFILE_PATH = TOOL_ROOT / "profiles" / "production.json"


DEFAULT_PROFILE: dict[str, Any] = {
    "profile_name": "production_default",
    "default_draft_root": "",
    "default_draft_name": "",
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


def load_operator_profile(profile_path: Path | None = None) -> dict[str, Any]:
    path = profile_path or DEFAULT_PROFILE_PATH
    if not profile_path and not path.exists() and DEFAULT_RELEASE_PROFILE_PATH.exists():
        path = DEFAULT_RELEASE_PROFILE_PATH
    profile = dict(DEFAULT_PROFILE)
    if path.exists():
        loaded = json.loads(path.read_text("utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"OPERATOR_PROFILE_NOT_OBJECT:{path}")
        profile.update(loaded)
    return profile


def resolve_draft_dir(profile: dict[str, Any], draft_name: str = "", draft_dir: str = "") -> Path:
    if draft_dir:
        return Path(draft_dir)
    name = draft_name or str(profile.get("default_draft_name") or "")
    root_text = str(profile.get("default_draft_root") or "")
    if not root_text or root_text.startswith("EDIT_ME"):
        raise ValueError("PROFILE_NOT_CONFIGURED: edit profiles/production.json or pass -DraftDir / -DraftName")
    root = Path(root_text)
    if not name or name.startswith("EDIT_ME"):
        raise ValueError("PROFILE_NOT_CONFIGURED: edit profiles/production.json or pass -DraftDir / -DraftName")
    return root / name


def bool_profile(profile: dict[str, Any], key: str, default: bool = False) -> bool:
    value = profile.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)
