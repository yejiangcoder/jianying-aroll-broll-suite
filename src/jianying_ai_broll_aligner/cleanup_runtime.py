from __future__ import annotations

import shutil
import time
from pathlib import Path


def cleanup_runtime(runtime_dir: Path, max_age_hours: float = 24.0) -> tuple[int, int]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - max_age_hours * 3600
    deleted = 0
    failed = 0
    for child in runtime_dir.iterdir():
        try:
            if child.stat().st_mtime >= cutoff:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            deleted += 1
        except OSError:
            failed += 1
    return deleted, failed

