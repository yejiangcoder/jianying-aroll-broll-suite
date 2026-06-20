from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from aroll_text_normalize import normalize_text


TINY_CAPTION_MAX_CHARS = 3
TINY_CAPTION_DENSITY_WINDOW_US = 5_000_000
MIN_RESIDUAL_TINY_CAPTIONS_IN_WINDOW = 3
WEAK_FUNCTION_WORDS = frozenset(
    {
        "啊",
        "呃",
        "嗯",
        "呐",
        "呢",
        "吧",
        "嘛",
        "的",
        "了",
        "着",
        "过",
        "是",
        "在",
        "把",
        "给",
        "对",
        "从",
        "向",
        "被",
        "让",
        "和",
        "但",
        "就",
    }
)
HALF_START_TAILS = frozenset({"只", "还", "都", "也", "才", "会", "能", "要", "把", "给", "在", "被", "让"})
PRONOUN_STARTS = ("你", "我", "他", "她", "它", "咱")


@dataclass(frozen=True)
class TinyCaptionClassification:
    caption_id: str
    segment_id: str
    caption_text: str
    duration_us: int
    char_count: int
    word_ids: list[str]
    classification: str
    severity: str
    classification_reason: str
    risk_tags: list[str]
    density_window_id: str = ""

    def to_report_row(self) -> dict[str, Any]:
        return {
            "caption_id": self.caption_id,
            "segment_id": self.segment_id,
            "caption_text": self.caption_text,
            "text": self.caption_text,
            "duration_us": int(self.duration_us),
            "char_count": int(self.char_count),
            "chars": int(self.char_count),
            "word_ids": list(self.word_ids),
            "classification": self.classification,
            "severity": self.severity,
            "classification_reason": self.classification_reason,
            "risk_tags": list(self.risk_tags),
            "density_window_id": self.density_window_id,
        }


def build_tiny_caption_classification_report(captions: list[Any]) -> dict[str, Any]:
    rows = sorted(captions, key=lambda row: (int(getattr(row, "target_start_us", 0)), int(getattr(row, "target_end_us", 0)), str(getattr(row, "caption_id", ""))))
    classifications = _classify_rows(rows)
    density_windows = _residual_density_windows(classifications, rows)
    density_ids = {
        str(window.get("density_window_id") or ""): set(str(caption_id) for caption_id in list(window.get("caption_ids") or []))
        for window in density_windows
    }
    enriched: list[TinyCaptionClassification] = []
    for classification in classifications:
        density_window_id = ""
        for window_id, caption_ids in density_ids.items():
            if classification.caption_id in caption_ids:
                density_window_id = window_id
                break
        enriched.append(
            TinyCaptionClassification(
                caption_id=classification.caption_id,
                segment_id=classification.segment_id,
                caption_text=classification.caption_text,
                duration_us=classification.duration_us,
                char_count=classification.char_count,
                word_ids=list(classification.word_ids),
                classification=classification.classification,
                severity=classification.severity,
                classification_reason=classification.classification_reason,
                risk_tags=list(classification.risk_tags),
                density_window_id=density_window_id,
            )
        )
    report_rows = [classification.to_report_row() for classification in enriched]
    return {
        "tiny_caption_classification_enabled": True,
        "tiny_caption_max_chars": TINY_CAPTION_MAX_CHARS,
        "tiny_caption_classification_count": len(report_rows),
        "tiny_caption_fatal_count": sum(1 for row in report_rows if row["severity"] == "fatal"),
        "tiny_caption_warning_count": sum(1 for row in report_rows if row["severity"] == "warning"),
        "tiny_caption_allow_count": sum(1 for row in report_rows if row["severity"] == "allow"),
        "tiny_caption_classifications": report_rows,
        "tiny_caption_residual_density_window_count": len(density_windows),
        "tiny_caption_residual_density_windows": density_windows,
        "tiny_caption_residual_density_window_us": TINY_CAPTION_DENSITY_WINDOW_US,
        "tiny_caption_residual_density_threshold": MIN_RESIDUAL_TINY_CAPTIONS_IN_WINDOW,
    }


def _classify_rows(rows: list[Any]) -> list[TinyCaptionClassification]:
    tiny_rows = [row for row in rows if _is_tiny_caption_text(str(getattr(row, "text", "") or ""))]
    text_counts: dict[str, int] = {}
    for row in tiny_rows:
        text = normalize_text(str(getattr(row, "text", "") or ""))
        if text:
            text_counts[text] = text_counts.get(text, 0) + 1
    return [_classify_row(row, text_counts) for row in tiny_rows]


def _classify_row(row: Any, text_counts: dict[str, int]) -> TinyCaptionClassification:
    text = str(getattr(row, "text", "") or "").strip()
    normalized = normalize_text(text)
    duration_us = max(0, int(getattr(row, "target_end_us", 0)) - int(getattr(row, "target_start_us", 0)))
    char_count = len(normalized)
    classification = "semantic_short_phrase"
    severity = "allow"
    reason = "short caption carries visible semantic content"
    risk_tags: list[str] = []
    if not normalized:
        classification = "empty_caption"
        severity = "fatal"
        reason = "empty tiny caption is unreadable residual"
        risk_tags.append("empty_text")
    elif _is_english_abbreviation(text):
        classification = "english_abbreviation"
        reason = "letter or mixed letter abbreviation is a valid compact caption"
        risk_tags.append("abbreviation")
    elif _is_numeric_abbreviation(text):
        classification = "numeric_abbreviation"
        reason = "numeric or symbol abbreviation is a valid compact caption"
        risk_tags.append("numeric")
    elif normalized in WEAK_FUNCTION_WORDS:
        classification = "isolated_function_word"
        severity = "fatal"
        reason = "isolated function or filler word is an unreadable residual"
        risk_tags.append("isolated_function_word")
    elif char_count <= 1:
        classification = "one_char_fragment"
        severity = "fatal"
        reason = "single CJK character is not enough visible context"
        risk_tags.append("single_cjk_char")
    elif _is_half_start_fragment(normalized):
        classification = "half_start_fragment"
        severity = "fatal"
        reason = "short caption ends with a dependent modal or function tail"
        risk_tags.append("dependent_tail")
    elif _looks_like_asr_residual(normalized):
        classification = "asr_residual_fragment"
        severity = "fatal"
        reason = "short caption has repeated residual-like ASR pattern"
        risk_tags.append("asr_residual")
    elif text_counts.get(normalized, 0) > 1:
        classification = "topic_term"
        reason = "short term recurs and is treated as topic or address reuse"
        risk_tags.append("recurring_short_term")
    return TinyCaptionClassification(
        caption_id=str(getattr(row, "caption_id", "") or ""),
        segment_id=_caption_segment_id(row),
        caption_text=text,
        duration_us=duration_us,
        char_count=char_count,
        word_ids=[str(word_id) for word_id in list(getattr(row, "word_ids", []) or []) if str(word_id)],
        classification=classification,
        severity=severity,
        classification_reason=reason,
        risk_tags=risk_tags,
    )


def _residual_density_windows(
    classifications: list[TinyCaptionClassification],
    rows: list[Any],
) -> list[dict[str, Any]]:
    by_caption_id = {str(getattr(row, "caption_id", "") or ""): row for row in rows}
    residuals = [row for row in classifications if row.severity == "fatal"]
    windows: list[dict[str, Any]] = []
    emitted: set[tuple[str, ...]] = set()
    for index, row in enumerate(residuals):
        source_row = by_caption_id.get(row.caption_id)
        if source_row is None:
            continue
        start_us = int(getattr(source_row, "target_start_us", 0))
        end_us = start_us + TINY_CAPTION_DENSITY_WINDOW_US
        members: list[TinyCaptionClassification] = []
        for other in residuals[index:]:
            other_row = by_caption_id.get(other.caption_id)
            if other_row is None:
                continue
            other_start_us = int(getattr(other_row, "target_start_us", 0))
            if start_us <= other_start_us < end_us:
                members.append(other)
        if len(members) < MIN_RESIDUAL_TINY_CAPTIONS_IN_WINDOW:
            continue
        key = tuple(member.caption_id for member in members)
        if key in emitted:
            continue
        emitted.add(key)
        window_id = f"tiny_residual_density_{len(windows) + 1:06d}"
        windows.append(
            {
                "density_window_id": window_id,
                "start_us": start_us,
                "end_us": end_us,
                "caption_ids": [member.caption_id for member in members],
                "caption_texts": [member.caption_text for member in members],
                "residual_tiny_caption_count": len(members),
                "classification": "local_residual_tiny_density",
                "severity": "fatal",
                "classification_reason": "local window contains multiple residual tiny captions",
                "risk_tags": ["local_density", "residual_tiny_captions"],
            }
        )
    return windows


def _is_tiny_caption_text(text: str) -> bool:
    normalized = normalize_text(text)
    return 0 < len(normalized) <= TINY_CAPTION_MAX_CHARS or _is_english_abbreviation(text) or _is_numeric_abbreviation(text)


def _caption_segment_id(row: Any) -> str:
    containing = str(getattr(row, "containing_video_segment_id", "") or "")
    if containing:
        return containing
    segment_ids = list(getattr(row, "timeline_segment_ids", []) or [])
    return str(segment_ids[0]) if segment_ids else ""


def _is_english_abbreviation(text: str) -> bool:
    stripped = str(text or "").strip()
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9&.\-]{1,5}", stripped)) and any(char.isalpha() for char in stripped)


def _is_numeric_abbreviation(text: str) -> bool:
    stripped = str(text or "").strip()
    return bool(re.fullmatch(r"\d[\dA-Za-z%.\-]{0,5}", stripped))


def _is_half_start_fragment(text: str) -> bool:
    return any(text.startswith(prefix) and len(text) <= len(prefix) + 1 and text.endswith(tuple(HALF_START_TAILS)) for prefix in PRONOUN_STARTS)


def _looks_like_asr_residual(text: str) -> bool:
    if len(text) < 2:
        return False
    if len(set(text)) == 1 and len(text) <= TINY_CAPTION_MAX_CHARS:
        return True
    return bool(re.fullmatch(r"(.+)\1", text)) and len(text) <= TINY_CAPTION_MAX_CHARS
