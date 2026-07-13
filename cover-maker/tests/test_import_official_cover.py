from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "import_official_cover_from_downloads.ps1"


def run_import(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            *args,
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def test_external_import_auto_selects_newest_exact_aspect_pair(tmp_path: Path) -> None:
    episode = tmp_path / "episode"
    source = tmp_path / "source"
    output = episode / "resource" / "covers"
    episode.mkdir()
    source.mkdir()

    old_landscape = source / "z_old_16x9.png"
    new_landscape = source / "a_new_16x9.png"
    old_portrait = source / "z_old_9x16.png"
    new_portrait = source / "a_new_9x16.png"
    Image.new("RGB", (1280, 720), "white").save(old_landscape)
    Image.new("RGB", (1280, 720), "white").save(new_landscape)
    Image.new("RGB", (720, 1280), "white").save(old_portrait)
    Image.new("RGB", (720, 1280), "white").save(new_portrait)
    old_time = time.time() - 3600
    os.utime(old_landscape, (old_time, old_time))
    os.utime(old_portrait, (old_time, old_time))

    result = run_import(
        "-EpisodeDir",
        str(episode),
        "-SourceDir",
        str(source),
        "-OutputDir",
        str(output),
    )
    assert result.returncode == 0, result.stdout
    manifest_path = next(output.glob("*_official_cover_manifest.json"))
    manifest = json.loads(manifest_path.read_text("utf-8-sig"))
    assert Path(manifest["source_16x9_path"]).name == new_landscape.name
    assert Path(manifest["source_9x16_path"]).name == new_portrait.name


def test_external_import_blocks_wrong_current_draft(tmp_path: Path) -> None:
    episode = tmp_path / "episode"
    source = tmp_path / "source"
    episode.mkdir()
    source.mkdir()
    landscape = source / "cover_16x9.png"
    portrait = source / "cover_9x16.png"
    Image.new("RGB", (1280, 720), "white").save(landscape)
    Image.new("RGB", (720, 1280), "white").save(portrait)
    state_path = tmp_path / "current_draft.json"
    state_path.write_text(
        json.dumps(
            {
                "draft_name": "actual-draft",
                "aroll_qc_passed": True,
                "broll_write": {
                    "status": "passed",
                    "commander_qc_passed_at": "2026-07-13T00:00:00+08:00",
                },
                "enhancement_decision_status": "resolved_by_commander",
            }
        ),
        "utf-8",
    )

    result = run_import(
        "-EpisodeDir",
        str(episode),
        "-SourceDir",
        str(source),
        "-Source16x9",
        str(landscape),
        "-Source9x16",
        str(portrait),
        "-CurrentDraftPath",
        str(state_path),
        "-ExpectedDraftName",
        "wrong-draft",
        "-CommanderQcPassed",
        "-UpdateCurrentDraft",
        "-ValidateOnly",
    )
    assert result.returncode != 0
    assert "Current draft mismatch" in result.stdout
