from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput
from aroll_v21.writeback.dynamic_source_binding_preflight import DynamicSourceBindingPreflight
from tests.test_aroll_v21_sacrificial_write_override import (
    create_disposable_draft,
    fake_encrypt,
    fake_real_draft_result,
    fake_real_writeback,
    fake_root_mirror_not_required,
)


def bind_report_to_result(report, result):
    if report.status != "ok":
        return report
    preflight = DynamicSourceBindingPreflight(root_mirror_func=fake_root_mirror_not_required).preflight(
        draft_dir=Path(str((result.metadata or {}).get("draft_dir") or "")),
        real_draft_result=result,
        run_report=report,
        run_dir=Path(str((result.metadata or {}).get("draft_dir") or "")) / "run",
    )
    if not preflight.success:
        return report
    return replace(
        report,
        resolved_template_map=dict(preflight.report.get("resolved_template_map") or {}),
        source_binding_report=dict(preflight.report),
    )


def preflight_source_templates(*, draft_dir, real_draft_result, run_report, run_dir=None):
    return DynamicSourceBindingPreflight(root_mirror_func=fake_root_mirror_not_required).preflight(
        draft_dir=draft_dir,
        real_draft_result=real_draft_result,
        run_report=run_report,
        run_dir=Path(run_dir) if run_dir is not None else Path(draft_dir) / "run",
    )


def run_report_from_result(result) :
    report = ArollEngine().run(
        ArollRunInput(
            mode="write",
            draft_data=result.draft_data,
            word_timeline=result.word_timeline,
            subtitles=result.subtitles,
            source_segments=result.source_segments,
            source_materials=result.source_materials,
            text_materials=result.text_materials,
            text_segments=result.text_segments,
            postwrite_mode="simulated",
        )
    )
    return bind_report_to_result(report, result)


class ArollV21RealWritebackBackendTests(unittest.TestCase):
    def test_real_writeback_writes_materials_segments_video_track_and_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)
            self.assertEqual(report.status, "ok")

            writeback = fake_real_writeback(jy_draftc=root / "jy-draftc.exe", encrypt_func=fake_encrypt)
            writeback_result = writeback.commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            self.assertTrue(writeback_result.report["writeback_success"])
            self.assertEqual(writeback_result.report["source_mapping_mode"], "dynamic_source_binding")
            self.assertEqual(writeback_result.report["selected_text_track_id"], "text_track")
            self.assertEqual(writeback_result.report["selected_video_track_id"], "video_track")
            self.assertIn("timeline_integrity_checks", writeback_result.report)
            self.assertIn("video_preflight", writeback_result.report)
            self.assertIn("audio_preflight", writeback_result.report)
            self.assertIn("filter_preflight", writeback_result.report)
            self.assertTrue(writeback_result.report["target_writes"][str(draft_content)])
            self.assertTrue(writeback_result.report["target_writes"][str(template)])
            written = json.loads(draft_content.read_text("utf-8"))
            self.assertEqual(written["duration"], max(segment.target_end_us for segment in report.final_timeline))
            self.assertEqual(len(written["materials"]["texts"]), len(report.material_write_plan["materials"]))
            text_track = next(track for track in written["tracks"] if track["type"] == "text")
            video_track = next(track for track in written["tracks"] if track["type"] == "video")
            self.assertEqual(len(text_track["segments"]), len(report.material_write_plan["segments"]))
            self.assertEqual(len(video_track["segments"]), len(report.final_timeline))
            self.assertEqual(
                video_track["segments"][0]["source_timerange"]["start"],
                report.final_timeline[0].spoken_source_start_us if report.final_timeline[0].spoken_source_start_us is not None else report.final_timeline[0].source_start_us,
            )
            self.assertIn("rough_cut_quality", writeback_result.report)
            self.assertTrue((root / "run" / "draft_content.v21.modified.dec.json").exists())
            self.assertTrue((root / "run" / "draft_content.v21.modified.enc.json").exists())

    def test_missing_timeline_metadata_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = replace(fake_real_draft_result(root=root), metadata={})
            report = run_report_from_result(fake_real_draft_result(root=root))

            writeback_result = fake_real_writeback(encrypt_func=fake_encrypt).commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertFalse(writeback_result.success)
            self.assertEqual(writeback_result.blockers[0].code, "V21_WRITEBACK_TIMELINE_METADATA_MISSING")


if __name__ == "__main__":
    unittest.main()
