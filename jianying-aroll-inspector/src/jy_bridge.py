from __future__ import annotations

import sys
from pathlib import Path


ALIGNER_ROOT = Path(r"D:\video tools\jianying-ai-image-aligner")
ALIGNER_SRC = ALIGNER_ROOT / "src"

if not ALIGNER_SRC.exists():
    raise RuntimeError(f"Existing Jianying draft bridge source not found: {ALIGNER_SRC}")

src_text = str(ALIGNER_SRC)
if src_text not in sys.path:
    sys.path.insert(0, src_text)

from direct_draft_broll_writer import (  # noqa: E402
    AI_TRACK_NAME,
    DEFAULT_JY_DRAFTC,
    DEFAULT_RUNTIME,
    assert_all_project_timeline_files_match_folder_ids,
    assert_layout_has_no_duplicate_timeline_ids,
    assert_timeline_content_id,
    decrypt,
    dice_score,
    encrypt,
    guid,
    norm_text,
    read_json,
    resolve_timeline_id,
    root_mirrors_timeline_id,
    text_score,
    write_json,
)


__all__ = [
    "ALIGNER_ROOT",
    "ALIGNER_SRC",
    "AI_TRACK_NAME",
    "DEFAULT_JY_DRAFTC",
    "DEFAULT_RUNTIME",
    "assert_all_project_timeline_files_match_folder_ids",
    "assert_layout_has_no_duplicate_timeline_ids",
    "assert_timeline_content_id",
    "decrypt",
    "dice_score",
    "encrypt",
    "guid",
    "norm_text",
    "read_json",
    "resolve_timeline_id",
    "root_mirrors_timeline_id",
    "text_score",
    "write_json",
]
