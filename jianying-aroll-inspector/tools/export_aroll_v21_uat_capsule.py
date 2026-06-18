from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


FORBIDDEN_FILENAMES = {"draft_content.json", "template-2.tmp"}
FORBIDDEN_SUFFIXES = {
    ".aac",
    ".avi",
    ".bmp",
    ".jpeg",
    ".jpg",
    ".log",
    ".m4a",
    ".mov",
    ".mp3",
    ".mp4",
    ".png",
    ".tmp",
    ".wav",
    ".webm",
}
DEFAULT_MAX_JSON_BYTES = 3_000_000
V21_ARTIFACT_NAMES = (
    "source_graph.json",
    "edit_units.json",
    "repeat_clusters.json",
    "decision_plan.json",
    "semantic_request_payloads.json",
    "final_timeline.json",
    "final_edl.json",
    "captions.json",
    "canonical_caption_template.json",
    "material_write_plan.json",
    "validator_report.json",
    "postwrite_report.json",
    "blocker_report.json",
    "decision_trace.json",
)


def assert_safe_capsule_source(path: Path, *, max_json_bytes: int = DEFAULT_MAX_JSON_BYTES) -> None:
    name = path.name.lower()
    if name in FORBIDDEN_FILENAMES:
        raise ValueError(f"FORBIDDEN_V21_CAPSULE_SOURCE:{path}")
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        raise ValueError(f"FORBIDDEN_V21_CAPSULE_SOURCE:{path}")
    if path.suffix.lower() != ".json":
        raise ValueError(f"V21_CAPSULE_SOURCE_MUST_BE_JSON:{path}")
    size = path.stat().st_size
    if size > max_json_bytes:
        raise ValueError(f"V21_CAPSULE_SOURCE_TOO_LARGE:{path}:{size}>{max_json_bytes}")


def read_json(path: Path, *, max_json_bytes: int = DEFAULT_MAX_JSON_BYTES) -> Any:
    assert_safe_capsule_source(path, max_json_bytes=max_json_bytes)
    return json.loads(path.read_text("utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def export_capsule(
    *,
    run_dir: Path,
    case_id: str,
    out_root: Path,
    max_json_bytes: int = DEFAULT_MAX_JSON_BYTES,
    description: str = "",
) -> Path:
    run_dir = run_dir.resolve()
    out_dir = out_root / case_id
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    missing: list[str] = []
    for name in V21_ARTIFACT_NAMES:
        source = run_dir / name
        if not source.exists():
            missing.append(name)
            continue
        payload = read_json(source, max_json_bytes=max_json_bytes)
        write_json(out_dir / name, payload)
        artifacts[name.removesuffix(".json")] = name
    manifest = {
        "schema_version": 1,
        "case_id": case_id,
        "description": description,
        "source": {
            "kind": "sanitized_aroll_v21_uat_capsule",
            "exporter": "tools/export_aroll_v21_uat_capsule.py",
        },
        "artifacts": artifacts,
        "missing_artifacts": missing,
        "forbidden_payloads_excluded": sorted(FORBIDDEN_FILENAMES),
        "media_excluded": True,
        "runtime_large_json_excluded": True,
    }
    write_json(out_dir / "manifest.json", manifest)
    return out_dir / "manifest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a sanitized V21 production-parity capsule from a V21 run dir.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--out-root", type=Path, default=Path("fixtures/uat_capsules"))
    parser.add_argument("--description", default="")
    parser.add_argument("--max-json-bytes", type=int, default=DEFAULT_MAX_JSON_BYTES)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = export_capsule(
        run_dir=args.run_dir,
        case_id=args.case_id,
        out_root=args.out_root,
        max_json_bytes=args.max_json_bytes,
        description=args.description,
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
