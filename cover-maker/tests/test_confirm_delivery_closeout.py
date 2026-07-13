from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "cover-maker" / "scripts" / "confirm_delivery_closeout.ps1"


def run_closeout(state_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-CurrentDraftPath",
            str(state_path),
            "-ValidateOnly",
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def write_state(tmp_path: Path, *, include_final_export: bool) -> Path:
    cover16 = tmp_path / "cover_16.png"
    cover9 = tmp_path / "cover_9.png"
    Image.new("RGB", (1280, 720), "white").save(cover16)
    Image.new("RGB", (720, 1280), "white").save(cover9)
    import_manifest = tmp_path / "official_cover_manifest.json"
    import_manifest.write_text(
        json.dumps(
            {
                "schema_version": "official_cover_import.v1",
                "status": "commander_qc_passed",
                "expected_draft_name": "draft-a",
                "cover_16x9_path": str(cover16),
                "cover_9x16_path": str(cover9),
            }
        ),
        "utf-8",
    )
    state = {
        "version": "video_pipeline_current_draft_v1",
        "draft_name": "draft-a",
        "cover_generation_mode": "commander_web_llm_external_import",
        "cover_generation_manifest_path": str(import_manifest),
        "cover_qc_passed": True,
        "factory_chain_complete": True,
        "cover_16x9_path": str(cover16),
        "cover_9x16_path": str(cover9),
    }
    if include_final_export:
        video = tmp_path / "final.mp4"
        video.write_bytes(b"video")
        state["final_export"] = {"video_path": str(video)}
    path = tmp_path / "current_draft.json"
    path.write_text(json.dumps(state, ensure_ascii=False), "utf-8")
    return path


def test_closeout_blocks_without_final_export_path(tmp_path: Path) -> None:
    state_path = write_state(tmp_path, include_final_export=False)

    result = run_closeout(state_path)

    assert result.returncode != 0
    assert "final_export.video_path is required" in result.stdout


def test_closeout_validates_final_export_path(tmp_path: Path) -> None:
    state_path = write_state(tmp_path, include_final_export=True)

    result = run_closeout(state_path)

    assert result.returncode == 0, result.stdout
    assert "validated_closed_loop_ready" in result.stdout
