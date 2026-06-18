from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from draft_runtime_binding import DraftRuntimeBinding


DEFAULT_STATE_PATH = Path(
    os.environ.get("VIDEO_PIPELINE_CURRENT_DRAFT_STATE")
    or os.environ.get("AUTO_CLIP_CURRENT_DRAFT_STATE")
    or (Path.home() / ".auto_clip_runtime" / "video_pipeline" / "current_draft.json")
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind the current QC-passed draft for downstream video pipeline stages.")
    parser.add_argument("--draft-dir", type=Path, required=True)
    parser.add_argument("--jy-draftc", type=Path, default=None)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--stage", default="aroll_qc_passed")
    parser.add_argument("--source", default="manual_qc")
    args = parser.parse_args()

    if not args.draft_dir.exists():
        raise FileNotFoundError(f"draft_dir 不存在：{args.draft_dir}")

    out_dir = args.state_path.parent / "binding_checks" / time.strftime("bind_current_draft_%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    binding = DraftRuntimeBinding.bind(args.draft_dir, args.jy_draftc, out_dir)
    state: dict[str, Any] = {
        "version": "video_pipeline_current_draft_v1",
        "draft_dir": str(args.draft_dir),
        "draft_name": args.draft_dir.name,
        "stage": args.stage,
        "aroll_qc_passed": args.stage in {"aroll_qc_passed", "broll_design_qc_passed", "ai_image_qc_passed"},
        "bound_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": args.source,
        "timeline_id": binding.timeline_id,
        "timeline_name": binding.timeline_name,
        "jy_draftc": str(binding.jy_draftc),
    }
    args.state_path.parent.mkdir(parents=True, exist_ok=True)
    args.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")

    print(f"CURRENT_DRAFT_STATE={args.state_path}")
    print(f"BOUND_DRAFT_DIR={args.draft_dir}")
    print(f"AROLL_QC_PASSED={state['aroll_qc_passed']}")
    print(f"TIMELINE_ID={binding.timeline_id}")
    print(f"TIMELINE_NAME={binding.timeline_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
