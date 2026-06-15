from __future__ import annotations

import argparse
import json
from pathlib import Path

from align_ai_images import discover_timelines, find_draft_by_project_name, resolve_timeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover Jianying project timelines and readable subtitle attachments.")
    parser.add_argument("--draft-root", type=Path, default=Path(r"D:\JianyingPro Drafts"))
    parser.add_argument("--project-name", default="")
    parser.add_argument("--draft-dir", type=Path, default=None)
    parser.add_argument("--timeline-name", default="")
    args = parser.parse_args()

    draft = args.draft_dir if args.draft_dir else find_draft_by_project_name(args.draft_root, args.project_name)
    timelines = discover_timelines(draft)
    selected = resolve_timeline(draft, args.timeline_name) if args.timeline_name else resolve_timeline(draft, None)
    payload = {
        "draft_dir": str(draft),
        "project_name": draft.name,
        "timeline_name_requested": args.timeline_name,
        "selected_timeline": {
            "index": selected.index,
            "id": selected.id,
            "name": selected.name,
            "is_active": selected.is_active,
            "path": str(selected.path),
            "script_path": str(selected.script_path),
            "script_exists": selected.script_exists,
            "script_sentence_count": selected.script_sentence_count,
            "script_translate_segment_count": selected.script_translate_segment_count,
        }
        if selected
        else None,
        "timelines": [
            {
                "index": row.index,
                "id": row.id,
                "name": row.name,
                "is_active": row.is_active,
                "path": str(row.path),
                "script_path": str(row.script_path),
                "script_exists": row.script_exists,
                "script_sentence_count": row.script_sentence_count,
                "script_translate_segment_count": row.script_translate_segment_count,
            }
            for row in timelines
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
