from __future__ import annotations

import argparse
import json
from pathlib import Path

from .cleanup_runtime import cleanup_runtime
from .draft_reader import read_json
from .draft_writer import append_ai_broll_track
from .plan_builder import build_plans, write_exec_plan_csv, write_semantic_plan_csv


def command_plan(args: argparse.Namespace) -> int:
    semantic, exec_plan, subtitles = build_plans(
        broll_path=args.broll,
        subtitle_path=args.subtitles,
        image_dir=args.image_dir,
        duration_sec=args.duration_sec,
        min_confidence=args.min_confidence,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    semantic_path = args.output_dir / "broll_semantic_plan.csv"
    exec_path = args.output_dir / "broll_exec_plan.csv"
    write_semantic_plan_csv(semantic_path, semantic)
    write_exec_plan_csv(exec_path, exec_plan)
    manifest = {
        "semantic_count": len(semantic),
        "exec_count": len(exec_plan),
        "subtitle_count": len(subtitles),
        "duration_sec": args.duration_sec,
        "semantic_plan": str(semantic_path),
        "exec_plan": str(exec_path),
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"semantic_plan={semantic_path}")
    print(f"exec_plan={exec_path}")
    print(f"items={len(exec_plan)}")
    return 0


def command_write_draft(args: argparse.Namespace) -> int:
    _semantic, exec_plan, _subtitles = build_plans(
        broll_path=args.broll,
        subtitle_path=args.subtitles,
        image_dir=args.image_dir,
        duration_sec=args.duration_sec,
        min_confidence=args.min_confidence,
    )
    draft = read_json(args.draft_json)
    updated = append_ai_broll_track(draft, exec_plan)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"output_json={args.output_json}")
    print(f"items={len(exec_plan)}")
    return 0


def command_clean_runtime(args: argparse.Namespace) -> int:
    deleted, failed = cleanup_runtime(args.runtime_dir, args.max_age_hours)
    print(f"deleted={deleted}")
    print(f"failed={failed}")
    return 0 if failed == 0 else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jianying-aroll-broll-suite")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Build semantic and execution plans.")
    plan.add_argument("--broll", type=Path, required=True)
    plan.add_argument("--subtitles", type=Path, required=True)
    plan.add_argument("--image-dir", type=Path, required=True)
    plan.add_argument("--output-dir", type=Path, required=True)
    plan.add_argument("--duration-sec", type=float, default=1.3)
    plan.add_argument("--min-confidence", type=float, default=0.50)
    plan.set_defaults(func=command_plan)

    write = sub.add_parser("write-draft", help="Append AI_BROLL track to a readable draft JSON.")
    write.add_argument("--draft-json", type=Path, required=True)
    write.add_argument("--output-json", type=Path, required=True)
    write.add_argument("--broll", type=Path, required=True)
    write.add_argument("--subtitles", type=Path, required=True)
    write.add_argument("--image-dir", type=Path, required=True)
    write.add_argument("--duration-sec", type=float, default=1.3)
    write.add_argument("--min-confidence", type=float, default=0.50)
    write.set_defaults(func=command_write_draft)

    clean = sub.add_parser("clean-runtime", help="Delete old runtime files.")
    clean.add_argument("--runtime-dir", type=Path, required=True)
    clean.add_argument("--max-age-hours", type=float, default=24.0)
    clean.set_defaults(func=command_clean_runtime)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
