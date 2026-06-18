from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aroll_v21.ingest.real_draft_adapter import RealDraftIngestResult
from aroll_v21.operator import ArollV21OperatorConfig, run_operator
from aroll_v21.writeback import RealDraftWriteback


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: str):
    return json.loads((ROOT / path).read_text("utf-8"))


def fake_encrypt(_jy_draftc: Path, plain: Path, encrypted_out: Path) -> None:
    encrypted_out.write_bytes(plain.read_bytes())


def fake_integrity_ok(*_args, **_kwargs) -> None:
    return None


def fake_root_mirror_not_required(_draft_dir: Path, _jy_draftc: Path, _run_dir: Path, _timeline_id: str) -> bool:
    return False


def fake_real_writeback(**kwargs) -> RealDraftWriteback:
    return RealDraftWriteback(
        jy_draftc=kwargs.get("jy_draftc"),
        encrypt_func=kwargs.get("encrypt_func") or fake_encrypt,
        root_mirror_func=kwargs.get("root_mirror_func") or fake_root_mirror_not_required,
        timeline_content_check_func=kwargs.get("timeline_content_check_func") or fake_integrity_ok,
        layout_check_func=kwargs.get("layout_check_func") or fake_integrity_ok,
        project_folder_check_func=kwargs.get("project_folder_check_func") or fake_integrity_ok,
    )


def create_disposable_draft(root: Path) -> tuple[Path, Path, Path]:
    draft_dir = root / "draft"
    timeline_dir = draft_dir / "Timelines" / "timeline_001"
    timeline_dir.mkdir(parents=True)
    draft_content = timeline_dir / "draft_content.json"
    template = timeline_dir / "template-2.tmp"
    draft_content.write_text("old encrypted draft_content", "utf-8")
    template.write_text("old encrypted template", "utf-8")
    return draft_dir, draft_content, template


def fake_real_draft_result(*, root: Path | None = None, malformed: bool = False) -> RealDraftIngestResult:
    material = load_json(
        "fixtures/real_materials/malformed_content_json.json"
        if malformed
        else "fixtures/real_materials/normal_caption_template.json"
    )
    source_segment = {
        "id": "clip",
        "type": "video",
        "material_id": "main_video_a",
        "source_timerange": {"start": 0, "duration": 1000000},
        "target_timerange": {"start": 0, "duration": 1000000},
        "source_start_us": 0,
        "source_end_us": 1000000,
        "target_start_us": 0,
        "target_end_us": 1000000,
        "track_id": "video_track",
        "track_type": "video",
    }
    text_segment = dict(material["segment"])
    text_segment.setdefault("track_id", "text_track")
    text_segment.setdefault("track_type", "text")
    draft_data = {
        "duration": 1000000,
        "materials": {
            "texts": [material["material"]],
            "videos": [{"id": "main_video_a", "duration": 1000000}],
        },
        "tracks": [
            {"id": "video_track", "type": "video", "segments": [source_segment]},
            {"id": "text_track", "type": "text", "segments": [text_segment]},
        ],
    }
    metadata = {"adapter": "fake"}
    if root is not None:
        draft_dir = root / "draft"
        timeline_dir = draft_dir / "Timelines" / "timeline_001"
        metadata.update(
            {
                "timeline_id": "timeline_001",
                "timeline_dir": str(timeline_dir),
                "draft_content_path": str(timeline_dir / "draft_content.json"),
                "template_path": str(timeline_dir / "template-2.tmp"),
            }
        )
    return RealDraftIngestResult(
        draft_data=draft_data,
        source_segments=[source_segment],
        source_materials=[{"source_material_id": "main_video_a", "type": "video", "duration_us": 1000000}],
        word_timeline=[
            {
                "word_id": "w001",
                "word_text": "测试",
                "start_us": 100000,
                "end_us": 400000,
                "subtitle_index": 1,
                "subtitle_uid": "s001",
            }
        ],
        subtitles=[{"subtitle_uid": "s001", "subtitle_index": 1, "text": "测试", "word_ids": ["w001"]}],
        text_materials=[material["material"]],
        text_segments=[text_segment],
        metadata=metadata,
    )


class FakeAdapter:
    def __init__(self, *args, result: RealDraftIngestResult | None = None, **kwargs) -> None:
        self.result = result or fake_real_draft_result()

    def load(self, *args, **kwargs) -> RealDraftIngestResult:
        return self.result


def fake_writeback_factory(*args, **kwargs):
    return fake_real_writeback(jy_draftc=kwargs.get("jy_draftc"))


class ArollV21SacrificialWriteOverrideTests(unittest.TestCase):
    def test_without_override_actual_decrypt_unavailable_still_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_disposable_draft(root)
            with patch("aroll_v21.operator.RealDraftIngestAdapter", lambda *a, **k: FakeAdapter(result=fake_real_draft_result(root=root))):
                summary = run_operator(
                    ArollV21OperatorConfig(
                        mode="write",
                        run_dir=root / "run",
                        draft_dir=root / "draft",
                        commit=True,
                    )
                )
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["write_status"], "blocked_actual_decrypt_unavailable")
            self.assertFalse(summary["commit_performed"])
            self.assertEqual(summary["postwrite_mode"], "unavailable")
            self.assertFalse(summary["postwrite_decrypt_ok"])

    def test_override_commits_only_decrypt_unavailable_as_sacrificial_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"JY_INSTALL_DIR": "C:/jy"}):
            root = Path(tmp)
            draft_dir, draft_content, template = create_disposable_draft(root)
            jy_draftc = root / "jy-draftc.exe"
            old_draft_content = draft_content.read_text("utf-8")
            old_template = template.read_text("utf-8")
            with patch(
                "aroll_v21.operator.RealDraftIngestAdapter",
                lambda *a, **k: FakeAdapter(result=fake_real_draft_result(root=root)),
            ), patch("aroll_v21.operator.RealDraftWriteback", fake_writeback_factory):
                summary = run_operator(
                    ArollV21OperatorConfig(
                        mode="write",
                        run_dir=root / "run",
                        draft_dir=draft_dir,
                        jy_draftc=jy_draftc,
                        commit=True,
                        allow_sacrificial_write_without_postwrite_decrypt=True,
                    )
                )

            self.assertEqual(summary["status"], "ok")
            self.assertEqual(summary["write_status"], "committed_sacrificial_without_postwrite_decrypt")
            self.assertTrue(summary["commit_performed"])
            self.assertEqual(summary["postwrite_mode"], "skipped_for_sacrificial_draft")
            self.assertFalse(summary["postwrite_decrypt_ok"])
            self.assertTrue(summary["postwrite_decrypt_skipped_for_sacrificial_draft"])
            self.assertEqual(summary["postwrite_decrypt_skip_reason"], "ACTUAL_POSTWRITE_DECRYPT_UNAVAILABLE")
            self.assertTrue(summary["ready_for_user_manual_qc"])
            self.assertTrue(summary["only_specified_draft_written"])
            self.assertEqual(summary["draft_dir"], str(root / "draft"))
            self.assertEqual(summary["jy_draftc_path"], str(jy_draftc))
            self.assertEqual(summary["jy_install_dir"], "C:/jy")
            self.assertTrue(summary["writeback_success"])
            self.assertTrue(summary["WRITE_SUCCESS"])
            self.assertTrue(summary["ENCRYPT_SUCCESS"])
            self.assertNotEqual(draft_content.read_text("utf-8"), old_draft_content)
            self.assertNotEqual(template.read_text("utf-8"), old_template)

            postwrite = json.loads((root / "run" / "postwrite_report.json").read_text("utf-8"))
            self.assertTrue(postwrite["sacrificial_write_override_used"])
            expected_draft_content = root / "draft" / "Timelines" / "timeline_001" / "draft_content.json"
            self.assertEqual(postwrite["draft_content_path"], str(expected_draft_content))
            writeback_report = json.loads((root / "run" / "writeback_report.json").read_text("utf-8"))
            self.assertTrue(writeback_report["writeback_success"])
            self.assertTrue(writeback_report["target_writes"][str(draft_content)])
            self.assertTrue(writeback_report["target_writes"][str(template)])

    def test_override_requires_explicit_draft_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_json = root / "input.json"
            result = fake_real_draft_result()
            input_json.write_text(
                json.dumps(
                    {
                        "source_segments": result.source_segments,
                        "source_materials": result.source_materials,
                        "word_timeline": result.word_timeline,
                        "subtitles": result.subtitles,
                        "text_materials": result.text_materials,
                        "text_segments": result.text_segments,
                    },
                    ensure_ascii=False,
                ),
                "utf-8",
            )
            summary = run_operator(
                ArollV21OperatorConfig(
                    mode="write",
                    run_dir=root / "run",
                    input_json=input_json,
                    commit=True,
                    allow_sacrificial_write_without_postwrite_decrypt=True,
                )
            )
            self.assertEqual(summary["status"], "blocked")
            self.assertIn("SACRIFICIAL_WRITE_REQUIRES_EXPLICIT_DRAFT_DIR", summary["blocker_codes"])

    def test_override_requires_commit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_disposable_draft(root)
            with patch("aroll_v21.operator.RealDraftIngestAdapter", lambda *a, **k: FakeAdapter(result=fake_real_draft_result(root=root))):
                summary = run_operator(
                    ArollV21OperatorConfig(
                        mode="write",
                        run_dir=root / "run",
                        draft_dir=root / "draft",
                        allow_sacrificial_write_without_postwrite_decrypt=True,
                    )
                )
            self.assertEqual(summary["status"], "blocked")
            self.assertIn("SACRIFICIAL_WRITE_REQUIRES_COMMIT_FLAG", summary["blocker_codes"])


if __name__ == "__main__":
    unittest.main()
