from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), "utf-8")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_jy_draftc(explicit: Path | None = None) -> Path:
    candidates = []
    if explicit:
        candidates.append(explicit)
    for name in ("JY_DRAFTC_EXE", "JY_DRAFTC"):
        value = os.environ.get(name)
        if value:
            candidates.append(Path(value))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if explicit:
        raise FileNotFoundError(f"jy-draftc 不存在：{explicit}")
    raise RuntimeError("未绑定 jy-draftc。请设置 JY_DRAFTC_EXE 或 JY_DRAFTC，或显式传入 --jy-draftc。")


def decrypt(jy_draftc: Path, encrypted: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(jy_draftc), "-d", str(encrypted), str(output)],
        cwd=str(jy_draftc.parent),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout)


def encrypt(jy_draftc: Path, plain: Path, encrypted: Path) -> None:
    result = subprocess.run(
        [str(jy_draftc), "-e", str(plain), str(encrypted)],
        cwd=str(jy_draftc.parent),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout)


def active_timeline_id(draft_dir: Path) -> str:
    layout = read_json(draft_dir / "timeline_layout.json")
    timeline_id = str(layout.get("activeTimeline") or "")
    if timeline_id:
        return timeline_id

    project_ids = project_timeline_ids(draft_dir)
    timeline_dirs = {
        path.name
        for path in (draft_dir / "Timelines").iterdir()
        if path.is_dir() and (path / "draft_content.json").exists()
    }
    candidates = sorted(project_ids & timeline_dirs)
    if len(candidates) == 1:
        return candidates[0]
    raise RuntimeError(
        "timeline_layout.json 缺少 activeTimeline，且无法从当前草稿唯一推断 active timeline："
        f"project_ids={sorted(project_ids)}, timeline_dirs={sorted(timeline_dirs)}"
    )


def active_timeline_name(draft_dir: Path, timeline_id: str) -> str:
    layout = read_json(draft_dir / "timeline_layout.json")
    for dock in layout.get("dockItems", []):
        ids = [str(row) for row in dock.get("timelineIds", [])]
        names = [str(row) for row in dock.get("timelineNames", [])]
        for idx, row_id in enumerate(ids):
            if row_id == timeline_id:
                return names[idx] if idx < len(names) else "activeTimeline"
    return "activeTimeline"


def layout_timeline_ids(draft_dir: Path) -> list[str]:
    layout_path = draft_dir / "timeline_layout.json"
    if not layout_path.exists():
        return []
    data = read_json(layout_path)
    ids: list[str] = []
    for dock in data.get("dockItems", []):
        ids.extend(str(timeline_id) for timeline_id in dock.get("timelineIds", []) if timeline_id)
    return ids


def project_timeline_ids(draft_dir: Path) -> set[str]:
    project_path = draft_dir / "Timelines" / "project.json"
    if not project_path.exists():
        return set()
    data = read_json(project_path)
    return {str(row.get("id") or "") for row in data.get("timelines", []) if row.get("id")}


def assert_timeline_content_id(data: dict[str, Any], expected_timeline_id: str, source: Path) -> None:
    actual = str(data.get("id") or "")
    if actual != expected_timeline_id:
        raise RuntimeError(
            "草稿时间线 ID 不一致，停止写入："
            f"source={source}, expected={expected_timeline_id}, actual={actual}"
        )


def assert_layout_has_no_duplicate_timeline_ids(draft_dir: Path) -> None:
    ids = layout_timeline_ids(draft_dir)
    duplicates = sorted({timeline_id for timeline_id in ids if ids.count(timeline_id) > 1})
    if duplicates:
        raise RuntimeError(f"timeline_layout.json 里存在重复时间线窗口，停止写入：{duplicates}")


def assert_all_project_timeline_files_match_folder_ids(
    draft_dir: Path,
    jy_draftc: Path,
    out_dir: Path,
) -> None:
    project_ids = project_timeline_ids(draft_dir)
    if not project_ids:
        raise RuntimeError("Timelines/project.json 没有可用时间线 ID，停止写入")
    timelines_dir = draft_dir / "Timelines"
    for timeline_id in sorted(project_ids):
        content_path = timelines_dir / timeline_id / "draft_content.json"
        if not content_path.exists():
            raise RuntimeError(f"项目索引中的时间线缺少 draft_content.json：{timeline_id}")
        plain = out_dir / f"audit_{timeline_id}.dec.json"
        decrypt(jy_draftc, content_path, plain)
        data = read_json(plain)
        assert_timeline_content_id(data, timeline_id, content_path)


def decrypt_root_id(draft_dir: Path, jy_draftc: Path, out_dir: Path) -> str:
    root_path = draft_dir / "draft_content.json"
    if not root_path.exists():
        return ""
    plain = out_dir / "audit_root.dec.json"
    decrypt(jy_draftc, root_path, plain)
    data = read_json(plain)
    return str(data.get("id") or "")


def collect_draft_write_hashes(draft_dir: Path) -> dict[str, str]:
    paths = [
        draft_dir / "draft_content.json",
        draft_dir / "template-2.tmp",
        draft_dir / "key_value.json",
        draft_dir / "timeline_layout.json",
        draft_dir / "Timelines" / "project.json",
    ]
    timelines_dir = draft_dir / "Timelines"
    for timeline_id in sorted(project_timeline_ids(draft_dir)):
        paths.extend(
            [
                timelines_dir / timeline_id / "draft_content.json",
                timelines_dir / timeline_id / "template-2.tmp",
            ]
        )
    return {str(path): sha256(path) for path in paths if path.exists()}


def changed_hash_paths(before: dict[str, str], after: dict[str, str]) -> set[str]:
    keys = set(before) | set(after)
    return {key for key in keys if before.get(key) != after.get(key)}


@dataclass(frozen=True)
class DraftRuntimeBinding:
    draft_dir: Path
    jy_draftc: Path
    timeline_id: str
    timeline_name: str
    timeline_dir: Path
    timeline_content: Path
    timeline_template: Path
    root_content: Path
    root_template: Path

    @classmethod
    def bind(cls, draft_dir: Path, jy_draftc: Path | None, out_dir: Path) -> "DraftRuntimeBinding":
        resolved = resolve_jy_draftc(jy_draftc)
        assert_layout_has_no_duplicate_timeline_ids(draft_dir)
        timeline_id = active_timeline_id(draft_dir)
        timeline_dir = draft_dir / "Timelines" / timeline_id
        timeline_content = timeline_dir / "draft_content.json"
        if not timeline_content.exists():
            raise FileNotFoundError(f"active timeline 缺少 draft_content.json：{timeline_content}")
        root_id = decrypt_root_id(draft_dir, resolved, out_dir)
        if root_id and root_id != timeline_id:
            raise RuntimeError(
                "root draft_content.json 与 active timeline 不一致，停止写入："
                f"root_id={root_id}, active_timeline_id={timeline_id}"
            )
        assert_all_project_timeline_files_match_folder_ids(draft_dir, resolved, out_dir)
        return cls(
            draft_dir=draft_dir,
            jy_draftc=resolved,
            timeline_id=timeline_id,
            timeline_name=active_timeline_name(draft_dir, timeline_id),
            timeline_dir=timeline_dir,
            timeline_content=timeline_content,
            timeline_template=timeline_dir / "template-2.tmp",
            root_content=draft_dir / "draft_content.json",
            root_template=draft_dir / "template-2.tmp",
        )

    @property
    def mirrors_root(self) -> bool:
        return self.root_content.exists()

    def decrypt_timeline(self, plain_path: Path) -> dict[str, Any]:
        decrypt(self.jy_draftc, self.timeline_content, plain_path)
        data = read_json(plain_path)
        assert_timeline_content_id(data, self.timeline_id, self.timeline_content)
        return data

    def target_write_paths(self) -> list[Path]:
        paths = [self.timeline_content, self.timeline_template]
        if self.mirrors_root:
            paths.extend([self.root_content, self.root_template])
        return paths

    def write_encrypted_transaction(
        self,
        encrypted_text: str,
        key_value_writer,
        out_dir: Path,
        post_write_validator=None,
    ) -> dict[str, Any]:
        backups_dir = out_dir / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        before = collect_draft_write_hashes(self.draft_dir)
        targets = self.target_write_paths()
        key_value = self.draft_dir / "key_value.json"
        backup_map: dict[Path, Path] = {}
        existed_before = {path: path.exists() for path in [*targets, key_value]}
        for path in [*targets, key_value]:
            if path.exists():
                backup = backups_dir / (str(len(backup_map)).zfill(2) + "_" + path.name)
                shutil.copy2(path, backup)
                backup_map[path] = backup
        try:
            for target in targets:
                target.write_text(encrypted_text, "utf-8")
            key_value_writer()
            after = collect_draft_write_hashes(self.draft_dir)
            allowed = {str(path) for path in targets}
            allowed.add(str(key_value))
            changed = changed_hash_paths(before, after)
            unexpected = sorted(changed - allowed)
            if unexpected:
                raise RuntimeError(f"写入范围越界：{unexpected}")
            result = {
                "only_specified_draft_written": True,
                "changed_paths": sorted(changed),
                "allowed_changed_paths": sorted(allowed),
                "backup_dir": str(backups_dir),
            }
            if post_write_validator:
                result.update(post_write_validator())
            return result
        except Exception as exc:
            for path, backup in backup_map.items():
                shutil.copy2(backup, path)
            for path, existed in existed_before.items():
                if not existed and path.exists():
                    path.unlink()
            restored = collect_draft_write_hashes(self.draft_dir)
            unrestored = sorted(changed_hash_paths(before, restored))
            if unrestored:
                raise RuntimeError(
                    "写入失败且事务回滚校验失败："
                    f"unrestored_paths={unrestored}; original_error={exc}"
                ) from exc
            raise
