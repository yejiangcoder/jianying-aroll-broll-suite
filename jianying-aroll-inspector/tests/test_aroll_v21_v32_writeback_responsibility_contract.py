from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from typing import Any

import aroll_v21.writeback.real_draft_writeback as real_writeback_module
from aroll_v21.ir.models import FinalTimelineSegment
from aroll_v21.operator import ArollV21OperatorConfig, run_operator
from aroll_v21.writeback.real_draft_writeback import RealDraftWriteback
from aroll_v21.writeback.dynamic_source_binding_preflight import DynamicSourceBindingPreflight
from tests.test_aroll_v21_prewrite_report_emitted_on_source_template_failure import FakeEngineReturningReport
from tests.test_aroll_v21_real_writeback_backend import run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import (
    FakeAdapter,
    create_disposable_draft,
    fake_real_draft_result,
)


class ArollV21V32WritebackResponsibilityContractTests(unittest.TestCase):
    def test_real_draft_writeback_does_not_import_dynamic_source_binder(self) -> None:
        source = Path(real_writeback_module.__file__).read_text("utf-8")

        self.assertNotIn("DynamicSourceBinder", source)
        self.assertNotIn("DynamicSourceBindingPreflight", source)

    def test_operator_runs_dynamic_binding_preflight_before_write(self) -> None:
        calls: list[dict] = []
        original = DynamicSourceBindingPreflight.preflight

        def recording_preflight(self, *args, **kwargs):
            calls.append(kwargs)
            return original(self, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            with patch("aroll_v21.operator.RealDraftIngestAdapter", lambda *a, **k: FakeAdapter(result=fake_real_draft_result(root=root))), patch.object(
                DynamicSourceBindingPreflight,
                "preflight",
                recording_preflight,
            ):
                summary = run_operator(
                    ArollV21OperatorConfig(
                        mode="write",
                        run_dir=root / "run",
                        draft_dir=draft_dir,
                        commit=True,
                    )
                )

        self.assertTrue(calls)
        self.assertEqual(summary["write_status"], "blocked_actual_decrypt_unavailable")
        self.assertFalse(summary["commit_performed"])

    def test_write_mode_does_not_commit_when_binding_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            ready_report = run_report_from_result(fake_real_draft_result(root=root / "logical"))
            current_result = fake_real_draft_result(root=root)
            current_result.draft_data["materials"]["videos"][0]["duration"] = 200_000
            current_result.source_materials[0]["duration_us"] = 200_000
            current_result.source_segments[0]["source_timerange"] = {"start": 0, "duration": 200_000}
            current_result.source_segments[0]["target_timerange"] = {"start": 0, "duration": 200_000}
            current_result.draft_data["tracks"][0]["segments"][0] = current_result.source_segments[0]

            with patch("aroll_v21.operator.RealDraftIngestAdapter", lambda *a, **k: FakeAdapter(result=current_result)), patch(
                "aroll_v21.operator.ArollEngine",
                lambda *a, **k: FakeEngineReturningReport(report=ready_report),
            ):
                summary = run_operator(
                    ArollV21OperatorConfig(
                        mode="write",
                        run_dir=root / "run",
                        draft_dir=draft_dir,
                        commit=True,
                        allow_sacrificial_write_without_postwrite_decrypt=True,
                    )
                )

        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["fatal_blocker"], "V21_DYNAMIC_BINDING_MISSING")
        self.assertFalse(summary["commit_performed"])
        self.assertFalse(summary["WRITE_SUCCESS"])

    def test_write_mode_does_not_commit_when_binding_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            ready_report = run_report_from_result(fake_real_draft_result(root=root / "logical"))
            current_result = fake_real_draft_result(root=root)
            second = dict(current_result.source_segments[0], id="clip_b", material_id="main_video_b", track_id="video_track_b")
            current_result.source_segments.append(second)
            current_result.source_materials.append({"source_material_id": "main_video_b", "type": "video", "duration_us": 1_000_000})
            current_result.draft_data["materials"]["videos"].append({"id": "main_video_b", "type": "video", "duration": 1_000_000})
            current_result.draft_data["tracks"].append({"id": "video_track_b", "type": "video", "segments": [second]})

            with patch("aroll_v21.operator.RealDraftIngestAdapter", lambda *a, **k: FakeAdapter(result=current_result)), patch(
                "aroll_v21.operator.ArollEngine",
                lambda *a, **k: FakeEngineReturningReport(report=ready_report),
            ):
                summary = run_operator(
                    ArollV21OperatorConfig(
                        mode="write",
                        run_dir=root / "run",
                        draft_dir=draft_dir,
                        commit=True,
                        allow_sacrificial_write_without_postwrite_decrypt=True,
                    )
                )

        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["fatal_blocker"], "V21_DYNAMIC_BINDING_PRIMARY_VIDEO_AMBIGUOUS")
        self.assertFalse(summary["commit_performed"])
        self.assertFalse(summary["WRITE_SUCCESS"])

    def test_ready_pre_audit_requires_speed_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            result.source_segments[0]["source_timerange"] = {"start": 0, "duration": 1_200_000}
            result.source_segments[0]["target_timerange"] = {"start": 0, "duration": 1_000_000}
            result.source_segments[0]["speed"] = 1.0
            result.draft_data["tracks"][0]["segments"][0] = result.source_segments[0]

            with patch("aroll_v21.operator.RealDraftIngestAdapter", lambda *a, **k: FakeAdapter(result=result)):
                summary = run_operator(ArollV21OperatorConfig(mode="dry-run", run_dir=root / "run", draft_dir=draft_dir))

        self.assertEqual(summary["status"], "blocked")
        self.assertFalse(summary["READY_FOR_DISPOSABLE_WRITE_PRE_AUDIT"])
        self.assertEqual(summary["fatal_blocker"], "V21_WRITEBACK_UNSUPPORTED_SPEED_MAPPING")

    def test_ready_pre_audit_requires_effect_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            result.draft_data["tracks"].append(
                {
                    "id": "effect_track",
                    "type": "effect",
                    "segments": [{"id": "fx1", "target_timerange": {"start": 200_000, "duration": 50_000}}],
                }
            )

            with patch("aroll_v21.operator.RealDraftIngestAdapter", lambda *a, **k: FakeAdapter(result=result)):
                summary = run_operator(ArollV21OperatorConfig(mode="dry-run", run_dir=root / "run", draft_dir=draft_dir))

        self.assertEqual(summary["status"], "blocked")
        self.assertFalse(summary["READY_FOR_DISPOSABLE_WRITE_PRE_AUDIT"])
        self.assertEqual(summary["fatal_blocker"], "V21_WRITEBACK_UNSUPPORTED_COMPLEX_EFFECT_TRACK")

    def test_ready_for_user_manual_qc_only_after_successful_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            with patch("aroll_v21.operator.RealDraftIngestAdapter", lambda *a, **k: FakeAdapter(result=fake_real_draft_result(root=root))):
                summary = run_operator(
                    ArollV21OperatorConfig(
                        mode="write",
                        run_dir=root / "run",
                        draft_dir=draft_dir,
                        commit=True,
                    )
                )
            run_summary = json.loads((root / "run" / "run_summary.json").read_text("utf-8"))

        self.assertEqual(summary["status"], "blocked")
        self.assertFalse(summary["commit_performed"])
        self.assertFalse(run_summary["ready_for_user_manual_qc"])

    def test_video_segment_from_template_preserves_extra_material_refs(self) -> None:
        template = {
            "id": "template_video_segment",
            "material_id": "video_1",
            "extra_material_refs": ["speed_1", "effect_1"],
            "source_timerange": {"start": 0, "duration": 1_200_000},
            "target_timerange": {"start": 0, "duration": 1_000_000},
        }
        final_segment = FinalTimelineSegment(
            "seg_1",
            "",
            None,
            100_000,
            500_000,
            0,
            400_000,
            ["w1"],
            "测试",
            [],
            clip_source_start_us=100_000,
            clip_source_end_us=500_000,
        )
        draft_data = {"materials": {"speeds": [{"id": "speed_1", "speed": 1.2}]}}

        row = RealDraftWriteback()._video_segment_from_template(template, final_segment, 1, draft_data)

        self.assertEqual(row["extra_material_refs"], ["speed_1", "effect_1"])
        self.assertEqual(row["source_timerange"]["start"], 120_000)
        self.assertEqual(row["source_timerange"]["duration"], 480_000)

    def test_real_draft_writeback_uses_bound_or_draft_data_speed_not_empty_resolver(self) -> None:
        template = {
            "id": "template_video_segment",
            "material_id": "video_1",
            "extra_material_refs": ["speed_1"],
            "source_timerange": {"start": 0, "duration": 1_200_000},
            "target_timerange": {"start": 0, "duration": 1_000_000},
        }
        final_segment = FinalTimelineSegment(
            "seg_1",
            "",
            None,
            100_000,
            500_000,
            0,
            400_000,
            ["w1"],
            "测试",
            [],
            clip_source_start_us=100_000,
            clip_source_end_us=500_000,
        )
        draft_data = {"materials": {"speeds": [{"id": "speed_1", "speed": 1.2}]}}

        row = RealDraftWriteback()._video_segment_from_template(template, final_segment, 1, draft_data)

        self.assertEqual(row["source_timerange"]["start"], 120_000)

    def _effective_speed(self, source_timerange: dict[str, Any], target_timerange: dict[str, Any]) -> float:
        source_duration = int(source_timerange.get("duration") or 0)
        target_duration = int(target_timerange.get("duration") or 0)
        self.assertGreater(target_duration, 0)
        return source_duration / target_duration

    def test_effective_speed_invariant_12x_no_handle_drift(self) -> None:
        template = {
            "id": "template_video_segment",
            "material_id": "video_1",
            "source_timerange": {"start": 0, "duration": 1_200_000},
            "target_timerange": {"start": 0, "duration": 1_000_000},
        }
        final_segment = FinalTimelineSegment(
            "seg_1",
            "",
            None,
            100_000,
            500_000,
            200_000,
            600_000,
            ["w1"],
            "测试",
            [],
            spoken_source_start_us=100_000,
            spoken_source_end_us=500_000,
            clip_source_start_us=80_000,
            clip_source_end_us=620_000,
        )
        draft_data = {}
        row = RealDraftWriteback()._video_segment_from_template(template, final_segment, 1, draft_data)
        self.assertEqual(row["source_timerange"]["start"], 120_000)
        self.assertEqual(row["source_timerange"]["duration"], 480_000)
        self.assertAlmostEqual(
            self._effective_speed(row["source_timerange"], row["target_timerange"]),
            1.2,
            delta=0.01,
        )

    def test_220ms_handle_does_not_change_written_effective_speed(self) -> None:
        template = {
            "id": "template_video_segment",
            "material_id": "video_1",
            "source_timerange": {"start": 0, "duration": 1_200_000},
            "target_timerange": {"start": 0, "duration": 1_000_000},
        }
        final_segment = FinalTimelineSegment(
            "seg_2",
            "",
            None,
            300_000,
            700_000,
            0,
            400_000,
            ["w1"],
            "测试",
            [],
            spoken_source_start_us=300_000,
            spoken_source_end_us=700_000,
            clip_source_start_us=80_000,
            clip_source_end_us=920_000,
            lead_handle_us=220_000,
            tail_handle_us=220_000,
        )
        draft_data = {}
        row = RealDraftWriteback()._video_segment_from_template(template, final_segment, 2, draft_data)
        self.assertEqual(row["source_timerange"]["start"], 360_000)
        self.assertEqual(row["source_timerange"]["duration"], 480_000)
        self.assertAlmostEqual(
            self._effective_speed(row["source_timerange"], row["target_timerange"]),
            1.2,
            delta=0.01,
        )

    def test_writeback_rejects_or_reports_13x_15x_17x_speed_drift(self) -> None:
        rows = [
            {"source_timerange": {"start": 0, "duration": 1_300_000}, "target_timerange": {"start": 0, "duration": 1_000_000}},
            {"source_timerange": {"start": 0, "duration": 1_500_000}, "target_timerange": {"start": 0, "duration": 1_000_000}},
            {"source_timerange": {"start": 0, "duration": 1_700_000}, "target_timerange": {"start": 0, "duration": 1_000_000}},
        ]
        report = RealDraftWriteback()._effective_speed_report(rows)
        self.assertEqual(report["effective_speed_min"], 1.3)
        self.assertEqual(report["effective_speed_max"], 1.7)
        self.assertEqual(report["effective_speed_drift_count"], 3)


if __name__ == "__main__":
    unittest.main()
