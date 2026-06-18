from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from draft_runtime_binding import DraftRuntimeBinding, sha256
from direct_draft_broll_writer import (
    DEFAULT_JY_DRAFTC,
    DEFAULT_RUNTIME,
    broll_static_list_ids,
    broll_table_ai_ids,
    image_id_sort_key,
    inspect_written_ai,
    load_visual_slot_plan,
    normalized_image_files,
    post_write_actual_image_audit,
    unnormalized_png_files,
    validate_broll_image_contract,
    validate_no_slot_overlaps,
    validate_slot_confidence,
    validate_slot_plan_ids,
    write_report,
)


def path_exists_errors(paths: dict[str, Path]) -> list[str]:
    return [f"{label.upper()}_MISSING={path}" for label, path in paths.items() if not path.exists()]


def fail_report(out_dir: Path, report: dict[str, Any], hard_errors: list[str]) -> int:
    report["hard_errors"] = hard_errors
    report["status"] = "ok" if not hard_errors else "failed"
    report_path = out_dir / "pipeline_contract_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(f"status={report['status']}")
    print(f"report={report_path}")
    if hard_errors:
        print("hard_errors=" + ",".join(hard_errors))
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Check visual_slot_plan image writeback contract against the active draft.")
    parser.add_argument("--draft-dir", type=Path, required=True)
    parser.add_argument("--broll", type=Path, required=True)
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--visual-slot-plan", type=Path, required=True)
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    args = parser.parse_args()

    out_dir = args.runtime / f"pipeline_check_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    hard_errors = path_exists_errors(
        {
            "draft_dir": args.draft_dir,
            "broll": args.broll,
            "image_dir": args.image_dir,
            "visual_slot_plan": args.visual_slot_plan,
        }
    )

    report: dict[str, Any] = {
        "draft_dir": str(args.draft_dir),
        "broll": str(args.broll),
        "image_dir": str(args.image_dir),
        "visual_slot_plan": str(args.visual_slot_plan),
    }
    if hard_errors:
        return fail_report(out_dir, report, hard_errors)

    try:
        binding = DraftRuntimeBinding.bind(args.draft_dir, args.jy_draftc, out_dir)
        data = binding.decrypt_timeline(out_dir / "draft_content.dec.json")
        report.update(
            {
                "timeline_id": binding.timeline_id,
                "timeline_name": binding.timeline_name,
                "jy_draftc": str(binding.jy_draftc),
            }
        )
    except Exception as exc:
        hard_errors.append(f"DRAFT_RUNTIME_BINDING_FAILED={exc}")
        return fail_report(out_dir, report, hard_errors)

    table_ids = broll_table_ai_ids(args.broll)
    static_list_ids = broll_static_list_ids(args.broll)
    image_files = normalized_image_files(args.image_dir)
    image_ids = list(image_files.keys())
    invalid_images = [path.name for path in unnormalized_png_files(args.image_dir)]
    report.update(
        {
            "broll_table_ai_ids": table_ids,
            "broll_static_list_ids": static_list_ids,
            "normalized_ai_image_count": len(image_ids),
            "normalized_ai_image_ids": image_ids,
            "unnormalized_png_files": invalid_images,
        }
    )

    slots = []
    try:
        image_ids, image_files = validate_broll_image_contract(args.broll, args.image_dir)
        slots = load_visual_slot_plan(args.visual_slot_plan, args.image_dir, image_files)
        validate_slot_plan_ids(slots, image_ids)
        validate_no_slot_overlaps(slots)
        validate_slot_confidence(slots)
        write_report(out_dir, slots)
    except Exception as exc:
        hard_errors.append(f"INPUT_CONTRACT_FAILED={exc}")

    if slots:
        audit = post_write_actual_image_audit(data, slots, args.image_dir)
        root_mirror_consistent = True
        if binding.mirrors_root:
            root_mirror_consistent = sha256(binding.root_content) == sha256(binding.timeline_content)
        audit["root_timeline_mirror_consistent"] = root_mirror_consistent
        if not root_mirror_consistent:
            audit["hard_errors"].append("ROOT_TIMELINE_MIRROR_INCONSISTENT")
            audit["post_write_actual_image_audit_gate_passed"] = False
        report["post_write_actual_image_audit"] = audit
        if not audit["post_write_actual_image_audit_gate_passed"]:
            hard_errors.extend(audit["hard_errors"])
    else:
        report["written_ai"] = inspect_written_ai(data, args.image_dir)

    report.update(
        {
            "visual_slot_count": len(slots),
            "visual_slot_image_ids": [slot["image_id"] for slot in sorted(slots, key=lambda row: image_id_sort_key(row["image_id"]))],
            "post_write_actual_image_audit_gate_passed": bool(
                report.get("post_write_actual_image_audit", {}).get("post_write_actual_image_audit_gate_passed")
            ),
        }
    )

    print(f"broll_images={len(image_ids)} visual_slots={len(slots)}")
    if "post_write_actual_image_audit" in report:
        written = report["post_write_actual_image_audit"]["written_image_segment_count"]
        print(f"written_image_segments={written}")
    return fail_report(out_dir, report, hard_errors)


if __name__ == "__main__":
    raise SystemExit(main())
