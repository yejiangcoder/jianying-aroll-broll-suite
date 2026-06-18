from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aroll_v21.ir.models import Blocker


PHYSICAL_ID_FIELDS = {
    "source_segment_id",
    "source_material_id",
    "material_id",
    "source_template_id",
    "template_segment_id",
    "template_material_id",
    "draft_segment_id",
    "draft_material_id",
    "track_id",
    "timeline_id",
}


@dataclass(frozen=True)
class ExternalWordTimelineResult:
    words: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[Blocker] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _read_payload(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


class ExternalWordTimelineAdapter:
    def load(self, path: Path) -> ExternalWordTimelineResult:
        path = Path(path)
        metadata = {"provider": "external", "word_timeline_json": str(path)}
        if not path.exists() or not path.is_file():
            return ExternalWordTimelineResult(
                blockers=[
                    Blocker(
                        "EXTERNAL_WORD_TIMELINE_FILE_MISSING",
                        "external word_timeline.json file is missing",
                        "ingest",
                        context={"path": str(path)},
                    )
                ],
                metadata=metadata,
            )
        try:
            payload = _read_payload(path)
        except Exception as exc:
            return ExternalWordTimelineResult(
                blockers=[
                    Blocker(
                        "EXTERNAL_WORD_TIMELINE_READ_FAILED",
                        "external word_timeline.json could not be parsed",
                        "ingest",
                        context={"path": str(path), "error": str(exc)},
                    )
                ],
                metadata=metadata,
            )
        rows = payload.get("word_timeline") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return ExternalWordTimelineResult(
                blockers=[
                    Blocker(
                        "EXTERNAL_WORD_TIMELINE_SCHEMA_INVALID",
                        "external word timeline must be a list or an object with word_timeline list",
                        "ingest",
                        context={"path": str(path)},
                    )
                ],
                metadata=metadata,
            )
        words: list[dict[str, Any]] = []
        blockers: list[Blocker] = []
        stripped_physical_id_count = 0
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                blockers.append(
                    Blocker(
                        "EXTERNAL_WORD_TIMELINE_ROW_INVALID",
                        "external word timeline row must be an object",
                        "ingest",
                        context={"row_index": index},
                    )
                )
                continue
            text = str(row.get("text") or row.get("word_text") or row.get("word") or row.get("token") or "")
            missing = []
            if not text:
                missing.append("text")
            if row.get("source_start_us") is None:
                missing.append("source_start_us")
            if row.get("source_end_us") is None:
                missing.append("source_end_us")
            if missing:
                blockers.append(
                    Blocker(
                        "EXTERNAL_WORD_TIMELINE_REQUIRED_FIELD_MISSING",
                        "external word timeline row is missing required word-level fields",
                        "ingest",
                        context={"row_index": index, "missing_fields": missing},
                    )
                )
                continue
            start = int(row.get("source_start_us") or 0)
            end = int(row.get("source_end_us") or 0)
            if end <= start:
                blockers.append(
                    Blocker(
                        "EXTERNAL_WORD_TIMELINE_TIME_INVALID",
                        "external word timeline row has invalid source time range",
                        "ingest",
                        context={"row_index": index, "source_start_us": start, "source_end_us": end},
                    )
                )
                continue
            debug_hints = {
                f"legacy_{key}": str(row.get(key) or "")
                for key in sorted(PHYSICAL_ID_FIELDS)
                if str(row.get(key) or "")
            }
            stripped_physical_id_count += len(debug_hints)
            words.append(
                {
                    "word_id": str(row.get("word_id") or row.get("id") or f"external_word_{index:06d}"),
                    "word_text": text,
                    "start_us": start,
                    "end_us": end,
                    "subtitle_uid": str(row.get("subtitle_uid") or "") or None,
                    "subtitle_index": int(row.get("subtitle_index")) if row.get("subtitle_index") is not None else None,
                    "confidence": float(row.get("confidence")) if row.get("confidence") is not None else None,
                    "is_cuttable_left": bool(row.get("is_cuttable_left", True)),
                    "is_cuttable_right": bool(row.get("is_cuttable_right", True)),
                    "debug_hints": debug_hints,
                }
            )
        metadata["word_count"] = len(words)
        metadata["stripped_physical_id_count"] = stripped_physical_id_count
        metadata["clean_word_timeline"] = True
        return ExternalWordTimelineResult(words=words, blockers=blockers, metadata=metadata)
