from __future__ import annotations

from pathlib import Path
from typing import Any

from aroll_inspect import run_checks
from jy_bridge import DEFAULT_JY_DRAFTC, read_json


def timeline_id_checks_after(
    draft_dir: Path,
    jy_draftc: Path,
    run_dir: Path,
    plain_path: Path,
    encrypted_path: Path,
    timeline_id: str,
) -> tuple[dict[str, bool], list[str]]:
    data: dict[str, Any] = read_json(plain_path)
    return run_checks(
        draft_dir=draft_dir,
        jy_draftc=jy_draftc or DEFAULT_JY_DRAFTC,
        run_dir=run_dir,
        data=data,
        encrypted_path=encrypted_path,
        timeline_id=timeline_id,
    )
