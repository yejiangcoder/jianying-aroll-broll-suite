from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


MICROSECONDS = 1_000_000


@dataclass(frozen=True)
class BrollItem:
    image_id: str
    target_quote: str
    visual_direction: str = ""
    image_title: str = ""


@dataclass(frozen=True)
class ImageAsset:
    image_id: str
    path: Path


@dataclass(frozen=True)
class SemanticPlanItem:
    image_id: str
    image_path: Path
    image_title: str
    target_quote: str
    visual_direction: str
    duration_sec: float


@dataclass(frozen=True)
class SubtitleRow:
    index: int
    text: str
    start_us: int
    end_us: int
    source: str = ""

    @property
    def start_sec(self) -> float:
        return self.start_us / MICROSECONDS

    @property
    def end_sec(self) -> float:
        return self.end_us / MICROSECONDS


@dataclass(frozen=True)
class ExecPlanItem:
    image_id: str
    image_path: Path
    subtitle_index: int
    subtitle_text: str
    start_sec: float
    duration_sec: float
    target_quote: str
    match_method: str
    confidence: float

