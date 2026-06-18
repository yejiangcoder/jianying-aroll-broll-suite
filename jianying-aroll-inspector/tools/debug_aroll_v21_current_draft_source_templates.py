from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from aroll_v21.writeback.dynamic_source_binder import CurrentDraftInventory, DynamicSourceBinder


def _read_json(path: Path) -> tuple[Any | None, str]:
    try:
        return json.loads(path.read_text("utf-8")), ""
    except Exception as exc:
        return None, str(exc)


def _active_timeline_id(draft_dir: Path) -> str:
    layout_path = draft_dir / "timeline_layout.json"
    payload, _error = _read_json(layout_path)
    if isinstance(payload, dict):
        timeline_id = str(payload.get("activeTimeline") or "").strip()
        if timeline_id:
            return timeline_id
    timelines_dir = draft_dir / "Timelines"
    candidates = [path for path in timelines_dir.iterdir() if path.is_dir()] if timelines_dir.exists() else []
    return candidates[0].name if len(candidates) == 1 else ""


def inspect_draft_source_templates(draft_dir: Path) -> dict[str, Any]:
    draft_dir = Path(draft_dir)
    timeline_id = _active_timeline_id(draft_dir)
    timeline_dir = draft_dir / "Timelines" / timeline_id if timeline_id else Path("")
    draft_content_path = timeline_dir / "draft_content.json" if timeline_id else Path("")
    report: dict[str, Any] = {
        "draft_dir": str(draft_dir),
        "active_timeline_id": timeline_id,
        "timeline_dir": str(timeline_dir) if timeline_id else "",
        "draft_content_path": str(draft_content_path) if timeline_id else "",
        "draft_content_exists": bool(timeline_id and draft_content_path.exists()),
        "draft_content_parse_ok": False,
        "draft_content_error": "",
    }
    if not timeline_id or not draft_content_path.exists():
        report["draft_content_error"] = "active timeline draft_content.json not found"
        return report
    payload, error = _read_json(draft_content_path)
    if not isinstance(payload, dict):
        report["draft_content_error"] = error or "draft_content root is not an object"
        return report
    binder = DynamicSourceBinder(
        CurrentDraftInventory(
            draft_dir=str(draft_dir),
            active_timeline_id=timeline_id,
            timeline_dir=str(timeline_dir),
            draft_content_path=str(draft_content_path),
            draft_data=payload,
        )
    )
    report.update(binder.candidate_index_report())
    report["draft_content_parse_ok"] = True
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect V21 current draft source template candidates without writing the draft.")
    parser.add_argument("--draft-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect_draft_source_templates(args.draft_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
