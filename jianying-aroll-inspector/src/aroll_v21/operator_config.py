from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


Mode = Literal["dry-run", "write", "verify-only"]
ReportProfile = Literal["minimal", "standard", "debug"]


@dataclass(frozen=True)
class ArollV21OperatorConfig:
    mode: Mode
    run_dir: Path
    input_json: Path | None = None
    draft_dir: Path | None = None
    jy_draftc: Path | None = None
    word_timeline_json: Path | None = None
    semantic_decisions_json: Path | None = None
    postwrite_materials_json: Path | None = None
    simulate_write: bool = False
    commit: bool = False
    allow_sacrificial_write_without_postwrite_decrypt: bool = False
    semantic_mode: str = "auto"
    ready_run_dir: Path | None = None
    report_profile: ReportProfile = "standard"


def _normalize_report_profile(value: str | None) -> ReportProfile:
    profile = str(value or "standard").strip().lower()
    if profile not in {"minimal", "standard", "debug"}:
        return "standard"
    return profile  # type: ignore[return-value]


def _effective_report_profile(value: str | None, status: str | None) -> ReportProfile:
    profile = _normalize_report_profile(value)
    if profile == "standard" and str(status or "") != "ok":
        return "debug"
    return profile
