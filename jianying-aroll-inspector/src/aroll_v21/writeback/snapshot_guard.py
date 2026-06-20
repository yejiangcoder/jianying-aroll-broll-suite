from __future__ import annotations

from typing import Any


def configure_writeback_dependencies(dependencies: dict[str, Any]) -> None:
    globals().update(dependencies)


def _snapshot_targets(self, targets: list[Path], run_dir: Path) -> list[dict[str, Any]]:
    snapshot_dir = run_dir / "writeback_target_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshots: list[dict[str, Any]] = []
    for index, target in enumerate(targets, start=1):
        target_path = Path(target)
        existed = target_path.exists()
        snapshot_path = snapshot_dir / f"target_{index:02d}.bak"
        if existed:
            shutil.copyfile(target_path, snapshot_path)
        snapshots.append(
            {
                "target": target_path,
                "existed": existed,
                "snapshot": snapshot_path if existed else None,
            }
        )
    return snapshots


def _restore_target_snapshots(self, snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    restored: dict[str, bool] = {}
    for row in snapshots:
        target = Path(row["target"])
        try:
            if bool(row.get("existed")):
                snapshot = Path(row["snapshot"])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(snapshot, target)
                restored[str(target)] = target.exists() and target.stat().st_size == snapshot.stat().st_size
            else:
                if target.exists():
                    target.unlink()
                restored[str(target)] = not target.exists()
        except Exception as exc:
            restored[str(target)] = False
            errors.append({"target": str(target), "error": str(exc)})
    return {
        "rollback_performed": True,
        "rollback_success": bool(restored) and all(restored.values()) and not errors,
        "rollback_target_results": restored,
        "rollback_errors": errors,
    }
