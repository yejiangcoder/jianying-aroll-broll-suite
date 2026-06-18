from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from aroll_v21.operator import ArollV21OperatorConfig, run_operator
from aroll_v21.writeback import WritebackResult

from tests.test_aroll_v21_full_chain_internal_self_check import ExternalWordTimelineAdapter
from tests.test_aroll_v21_sacrificial_write_override import (
    create_disposable_draft,
    fake_real_draft_result,
    fake_real_writeback,
)


def failing_encrypt(_jy_draftc: Path, _plain: Path, _encrypted_out: Path) -> None:
    raise RuntimeError("fake encrypt failure")


def writeback_with_failing_encrypt(*args, **kwargs):
    return fake_real_writeback(jy_draftc=kwargs.get("jy_draftc"), encrypt_func=failing_encrypt)


class ShouldNotRunWriteback:
    called = False

    def __init__(self, *args, **kwargs) -> None:
        type(self).called = True

    def commit(self, **_kwargs) -> WritebackResult:
        type(self).called = True
        raise AssertionError("writeback should not execute when gates fail")


def run_write_with_result(root: Path, result, *, writeback_factory, **config_overrides):
    with patch(
        "aroll_v21.operator.RealDraftIngestAdapter",
        lambda *a, **k: ExternalWordTimelineAdapter(result=result),
    ), patch("aroll_v21.operator.RealDraftWriteback", writeback_factory):
        return run_operator(
            ArollV21OperatorConfig(
                mode="write",
                run_dir=root / "run",
                draft_dir=root / "draft",
                jy_draftc=root / "jy-draftc.exe",
                commit=True,
                allow_sacrificial_write_without_postwrite_decrypt=True,
                **config_overrides,
            )
        )


class ArollV21BackendContractFailureInjectionTests(unittest.TestCase):
    def test_fake_encrypt_failure_blocks_without_fake_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            summary = run_write_with_result(root, result, writeback_factory=writeback_with_failing_encrypt)
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["write_status"], "blocked_writeback_failed")
            self.assertFalse(summary["commit_performed"])
            self.assertFalse(summary["writeback_success"])
            self.assertFalse(summary["ready_for_user_manual_qc"])
            self.assertFalse(summary["WRITE_SUCCESS"])
            self.assertIn("V21_WRITEBACK_ENCRYPT_FAILED", summary["blocker_codes"])

    def test_target_write_failure_blocks_without_fake_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            with patch(
                "aroll_v21.writeback.real_draft_writeback.shutil.copyfile",
                side_effect=PermissionError("fake target write failure"),
            ):
                summary = run_write_with_result(root, result, writeback_factory=lambda *a, **k: fake_real_writeback())
            self.assertEqual(summary["status"], "blocked")
            self.assertFalse(summary["commit_performed"])
            self.assertFalse(summary["writeback_success"])
            self.assertFalse(summary["WRITE_SUCCESS"])
            self.assertIn("V21_WRITEBACK_TARGET_WRITE_FAILED", summary["blocker_codes"])

    def test_missing_timeline_metadata_blocks_without_fake_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_disposable_draft(root)
            result = replace(fake_real_draft_result(root=root), metadata={})
            summary = run_write_with_result(root, result, writeback_factory=lambda *a, **k: fake_real_writeback())
            self.assertEqual(summary["status"], "blocked")
            self.assertFalse(summary["commit_performed"])
            self.assertFalse(summary["writeback_success"])
            self.assertIn("V21_WRITEBACK_TIMELINE_METADATA_MISSING", summary["blocker_codes"])

    def test_selected_text_track_missing_blocks_without_fake_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            result.draft_data["tracks"] = [track for track in result.draft_data["tracks"] if track["id"] != "text_track"]
            summary = run_write_with_result(root, result, writeback_factory=lambda *a, **k: fake_real_writeback())
            self.assertEqual(summary["status"], "blocked")
            self.assertFalse(summary["commit_performed"])
            self.assertFalse(summary["writeback_success"])
            self.assertIn("V21_WRITEBACK_SUBTITLE_TRACK_NOT_FOUND", summary["blocker_codes"])

    def test_selected_video_track_missing_blocks_without_fake_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            result.draft_data["tracks"] = [track for track in result.draft_data["tracks"] if track["id"] != "video_track"]
            summary = run_write_with_result(root, result, writeback_factory=lambda *a, **k: fake_real_writeback())
            self.assertEqual(summary["status"], "blocked")
            self.assertFalse(summary["commit_performed"])
            self.assertFalse(summary["writeback_success"])
            self.assertIn("V21_WRITEBACK_MAIN_VIDEO_TRACK_NOT_FOUND", summary["blocker_codes"])

    def test_gate_failure_does_not_execute_writeback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_disposable_draft(root)
            result = fake_real_draft_result(root=root, malformed=True)
            ShouldNotRunWriteback.called = False
            summary = run_write_with_result(root, result, writeback_factory=ShouldNotRunWriteback)
            self.assertEqual(summary["status"], "blocked")
            self.assertFalse(summary["commit_performed"])
            self.assertFalse(ShouldNotRunWriteback.called)

    def test_no_commit_with_sacrificial_override_blocks_before_writeback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            ShouldNotRunWriteback.called = False
            with patch(
                "aroll_v21.operator.RealDraftIngestAdapter",
                lambda *a, **k: ExternalWordTimelineAdapter(result=result),
            ), patch("aroll_v21.operator.RealDraftWriteback", ShouldNotRunWriteback):
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
            self.assertFalse(ShouldNotRunWriteback.called)

    def test_postwrite_verification_failure_blocks_actual_commit_before_writeback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            bad_postwrite = root / "bad_postwrite_materials.json"
            bad_postwrite.write_text(json.dumps([{"id": "bad", "content": "plain text"}], ensure_ascii=False), "utf-8")
            ShouldNotRunWriteback.called = False
            with patch(
                "aroll_v21.operator.RealDraftIngestAdapter",
                lambda *a, **k: ExternalWordTimelineAdapter(result=result),
            ), patch("aroll_v21.operator.RealDraftWriteback", ShouldNotRunWriteback):
                summary = run_operator(
                    ArollV21OperatorConfig(
                        mode="write",
                        run_dir=root / "run",
                        draft_dir=root / "draft",
                        postwrite_materials_json=bad_postwrite,
                        commit=True,
                    )
                )
            self.assertEqual(summary["status"], "blocked")
            self.assertEqual(summary["write_status"], "blocked_by_postwrite_verification")
            self.assertFalse(summary["commit_performed"])
            self.assertFalse(ShouldNotRunWriteback.called)


if __name__ == "__main__":
    unittest.main()
