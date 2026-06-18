from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


TEXT_KEYS = ("text", "word_text", "word", "token")
START_KEYS = ("source_start_us", "start_us")
END_KEYS = ("source_end_us", "end_us")
SUBTITLE_ROW_TYPES = {"subtitle", "subtitles", "sentence", "sentences", "caption", "captions"}


def _payload_rows(payload: Any) -> list[Any] | None:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("word_timeline"), list):
        return payload["word_timeline"]
    return None


def _row_text(row: dict[str, Any]) -> str:
    for key in TEXT_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _row_start(row: dict[str, Any]) -> int | None:
    for key in START_KEYS:
        if row.get(key) is not None:
            return int(row.get(key) or 0)
    return None


def _row_end(row: dict[str, Any]) -> int | None:
    for key in END_KEYS:
        if row.get(key) is not None:
            return int(row.get(key) or 0)
    return None


def normalize_word_timeline_payload(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = _payload_rows(payload)
    report: dict[str, Any] = {
        "ok": False,
        "input_row_count": 0,
        "normalized_word_count": 0,
        "errors": [],
    }
    if rows is None:
        report["errors"].append({"code": "WORD_TIMELINE_ROOT_SCHEMA_INVALID", "message": "payload must be a list or object with word_timeline list"})
        return [], report
    report["input_row_count"] = len(rows)
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            report["errors"].append({"code": "WORD_TIMELINE_ROW_INVALID", "row_index": index})
            continue
        row_type = str(row.get("type") or row.get("kind") or "").strip().lower()
        if row_type in SUBTITLE_ROW_TYPES or row.get("subtitle_text") is not None or row.get("sentence_text") is not None:
            report["errors"].append({"code": "SUBTITLE_AS_WORD_TIMELINE_FORBIDDEN", "row_index": index})
            continue
        text = _row_text(row)
        start = _row_start(row)
        end = _row_end(row)
        missing = []
        if not text:
            missing.append("text")
        if start is None:
            missing.append("source_start_us")
        if end is None:
            missing.append("source_end_us")
        if missing:
            report["errors"].append({"code": "WORD_TIMELINE_REQUIRED_FIELD_MISSING", "row_index": index, "missing_fields": missing})
            continue
        if end <= start:
            report["errors"].append({"code": "WORD_TIMELINE_TIME_INVALID", "row_index": index, "source_start_us": start, "source_end_us": end})
            continue
        normalized.append(
            {
                "word_id": str(row.get("word_id") or row.get("id") or f"external_word_{index:06d}"),
                "text": text,
                "source_start_us": start,
                "source_end_us": end,
                "source_material_id": str(row.get("source_material_id") or ""),
                "source_segment_id": str(row.get("source_segment_id") or "") or None,
                "subtitle_uid": str(row.get("subtitle_uid") or "") or None,
                "subtitle_index": row.get("subtitle_index"),
                "confidence": row.get("confidence"),
            }
        )
    report["normalized_word_count"] = len(normalized)
    report["ok"] = not report["errors"]
    return normalized, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and normalize A-Roll V21 external word_timeline.json.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--normalized-output", type=Path)
    parser.add_argument("--report-output", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text("utf-8"))
    normalized, report = normalize_word_timeline_payload(payload)
    if args.normalized_output:
        args.normalized_output.parent.mkdir(parents=True, exist_ok=True)
        args.normalized_output.write_text(json.dumps({"word_timeline": normalized}, ensure_ascii=False, indent=2), "utf-8")
    if args.report_output:
        args.report_output.parent.mkdir(parents=True, exist_ok=True)
        args.report_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
