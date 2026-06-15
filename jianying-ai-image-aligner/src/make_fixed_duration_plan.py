from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

from runtime_paths import get_runs_dir

DEFAULT_INPUT = get_runs_dir() / "ui_plan_20260610_050145" / "alignment_report.csv"
DEFAULT_OUTPUT_ROOT = get_runs_dir()


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def as_float(row: dict[str, str], key: str) -> float:
    value = (row.get(key) or "0").strip()
    return float(value) if value else 0.0


def build_fixed_rows(rows: list[dict[str, str]], duration_sec: float, gap_sec: float, clip_to_next: bool) -> list[dict[str, str]]:
    rows = sorted(rows, key=lambda row: (as_float(row, "start_sec"), row.get("image_id", "")))
    fixed: list[dict[str, str]] = []
    for index, row in enumerate(rows):
        item = dict(row)
        start = as_float(item, "start_sec")
        end = start + duration_sec
        if clip_to_next and index + 1 < len(rows):
            next_start = as_float(rows[index + 1], "start_sec")
            if end > next_start:
                end = max(start + 0.001, next_start - gap_sec)
        item["start_sec"] = f"{start:.3f}"
        item["end_sec"] = f"{end:.3f}"
        item["duration_sec"] = f"{max(0.001, end - start):.3f}"
        method = item.get("match_method") or ""
        if "fixed_1.3s" not in method:
            item["match_method"] = f"{method}+fixed_1.3s".strip("+")
        fixed.append(item)
    return fixed


def write_report(out_dir: Path, rows: list[dict[str, str]]) -> Path:
    out = out_dir / "alignment_report_1p3s.csv"
    fieldnames = [
        "image_id",
        "image_path",
        "start_sec",
        "end_sec",
        "duration_sec",
        "matched_subtitle",
        "broll_text",
        "match_method",
        "confidence",
    ]
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert an AI image alignment report to fixed-duration UI construction plan.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--duration-sec", type=float, default=1.3)
    parser.add_argument("--gap-sec", type=float, default=0.033)
    parser.add_argument("--clip-to-next", action="store_true")
    args = parser.parse_args()

    rows = read_rows(args.input)
    fixed = build_fixed_rows(rows, args.duration_sec, args.gap_sec, args.clip_to_next)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = args.output_root / f"ui_plan_1p3s_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = write_report(out_dir, fixed)
    manifest = out_dir / "alignment_manifest_1p3s.json"
    manifest.write_text(
        json.dumps(
            {
                "source_report": str(args.input),
                "report": str(report),
                "count": len(fixed),
                "duration_sec": args.duration_sec,
                "gap_sec": args.gap_sec,
                "clip_to_next": args.clip_to_next,
                "items": fixed,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    short_count = sum(1 for row in fixed if float(row["duration_sec"]) < args.duration_sec)
    print("OK_FIXED_PLAN")
    print(f"items: {len(fixed)}")
    print(f"shortened_for_same_track: {short_count}")
    print(f"report: {report}")
    print(f"manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
