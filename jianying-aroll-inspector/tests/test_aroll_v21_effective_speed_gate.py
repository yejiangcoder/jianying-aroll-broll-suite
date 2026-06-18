from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aroll_v21.ir import CaptionRenderUnit
from aroll_v21.quality.effective_speed_gate import build_effective_speed_gate
from aroll_v21.writeback.real_draft_writeback import RealDraftWriteback
from aroll_v21.writeback.dynamic_source_binding_preflight import DynamicSourceBindingPreflight
from aroll_v21.writeback.video_write_plan_projector import project_video_segment_from_template, timerange_duration, timerange_start
from tests.test_aroll_v21_real_writeback_backend import run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import (
    create_disposable_draft,
    fake_real_draft_result,
    fake_root_mirror_not_required,
)


def _make_12x_result(root: Path):
    result = fake_real_draft_result(root=root)
    segment = result.source_segments[0]
    segment["source_timerange"] = {"start": 0, "duration": 1_200_000}
    segment["target_timerange"] = {"start": 0, "duration": 1_000_000}
    segment["source_end_us"] = 1_200_000
    segment["target_end_us"] = 1_000_000
    result.draft_data["tracks"][0]["segments"][0] = segment
    result.draft_data["materials"]["videos"][0]["duration"] = 1_200_000
    result.source_materials[0]["duration_us"] = 1_200_000
    return result


class ArollV21EffectiveSpeedGateTests(unittest.TestCase):
    def test_effective_speed_gate_fails_closed_when_final_timeline_empty(self) -> None:
        gate = build_effective_speed_gate(
            final_timeline=[],
            resolved_template_map={},
            draft_data={},
        )

        self.assertFalse(gate["gate_passed"])
        self.assertIsNone(gate["effective_speed_min"])
        self.assertIsNone(gate["effective_speed_max"])
        self.assertEqual(gate["segment_reports"], [])
        self.assertEqual(gate["effective_speed_projected_row_count"], 0)
        self.assertIn("V21_EFFECTIVE_SPEED_PROJECTED_ROWS_MISSING", gate["blocker_codes"])

    def test_safe_handle_expands_source_and_target_without_speed_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _make_12x_result(root)
            report = run_report_from_result(result)
            base = report.final_timeline[0]
            segment = replace(
                base,
                source_start_us=300_000,
                source_end_us=600_000,
                spoken_source_start_us=300_000,
                spoken_source_end_us=600_000,
                clip_source_start_us=200_000,
                clip_source_end_us=820_000,
                target_start_us=300_000,
                target_end_us=600_000,
                lead_handle_us=100_000,
                tail_handle_us=220_000,
                debug_hints={
                    "safe_handle_policy_enabled": True,
                    "safe_handle_source_window_start_us": 0,
                    "safe_handle_source_window_end_us": 1_200_000,
                },
            )
            template = report.resolved_template_map[base.segment_id]["current_video_segment_template"]

            projected = project_video_segment_from_template(template, segment, 1, 1.2)
            gate = build_effective_speed_gate(
                final_timeline=[segment],
                resolved_template_map=report.resolved_template_map,
                draft_data=result.draft_data,
            )

            self.assertEqual(timerange_start(projected["target_timerange"]), 200_000)
            self.assertEqual(timerange_duration(projected["target_timerange"]), 620_000)
            self.assertEqual(timerange_duration(projected["source_timerange"]), 744_000)
            self.assertTrue(gate["gate_passed"])
            self.assertEqual(gate["effective_speed_drift_count"], 0)
            self.assertEqual(gate["lead_handle_applied_count"], 1)
            self.assertEqual(gate["tail_handle_applied_count"], 1)
            self.assertAlmostEqual(gate["segment_reports"][0]["effective_speed"], 1.2, delta=0.01)

    def test_safe_handle_does_not_cross_dropped_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _make_12x_result(root)
            report = run_report_from_result(result)
            base = report.final_timeline[0]
            segment = replace(
                base,
                source_start_us=300_000,
                source_end_us=600_000,
                spoken_source_start_us=300_000,
                spoken_source_end_us=600_000,
                clip_source_start_us=200_000,
                clip_source_end_us=820_000,
                target_start_us=300_000,
                target_end_us=600_000,
                lead_handle_us=100_000,
                tail_handle_us=220_000,
                debug_hints={
                    "safe_handle_policy_enabled": True,
                    "safe_handle_source_window_start_us": 0,
                    "safe_handle_source_window_end_us": 1_200_000,
                    "safe_handle_forbidden_source_ranges": [
                        {"start_us": 650_000, "end_us": 720_000, "reason": "crosses_dropped_repeat"}
                    ],
                },
            )

            gate = build_effective_speed_gate(
                final_timeline=[segment],
                resolved_template_map=report.resolved_template_map,
                draft_data=result.draft_data,
            )

            self.assertTrue(gate["gate_passed"])
            self.assertEqual(gate["lead_handle_applied_count"], 1)
            self.assertEqual(gate["tail_handle_applied_count"], 0)
            self.assertEqual(gate["segments_with_no_tail_handle"], 1)
            self.assertEqual(gate["handle_blocked_reasons"], {"tail:crosses_dropped_repeat": 1})

    def test_safe_handle_not_applied_when_target_overlap_would_occur(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _make_12x_result(root)
            report = run_report_from_result(result)
            base = report.final_timeline[0]
            segment = replace(
                base,
                source_start_us=300_000,
                source_end_us=600_000,
                spoken_source_start_us=300_000,
                spoken_source_end_us=600_000,
                clip_source_start_us=200_000,
                clip_source_end_us=820_000,
                target_start_us=300_000,
                target_end_us=600_000,
                lead_handle_us=100_000,
                tail_handle_us=220_000,
                debug_hints={
                    "safe_handle_policy_enabled": True,
                    "safe_handle_source_window_start_us": 0,
                    "safe_handle_source_window_end_us": 1_200_000,
                    "safe_handle_previous_target_end_us": 250_000,
                    "safe_handle_next_target_start_us": 750_000,
                },
            )

            gate = build_effective_speed_gate(
                final_timeline=[segment],
                resolved_template_map=report.resolved_template_map,
                draft_data=result.draft_data,
            )

            self.assertTrue(gate["gate_passed"])
            self.assertEqual(gate["lead_handle_applied_count"], 0)
            self.assertEqual(gate["tail_handle_applied_count"], 0)
            self.assertEqual(gate["handle_blocked_reasons"], {"lead:target_overlap_previous": 1, "tail:target_overlap_next": 1})

    def test_caption_span_remains_spoken_span_when_video_has_handle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _make_12x_result(root)
            report = run_report_from_result(result)
            base = report.final_timeline[0]
            segment = replace(
                base,
                source_start_us=300_000,
                source_end_us=600_000,
                spoken_source_start_us=300_000,
                spoken_source_end_us=600_000,
                clip_source_start_us=200_000,
                clip_source_end_us=820_000,
                target_start_us=300_000,
                target_end_us=600_000,
                debug_hints={
                    "safe_handle_policy_enabled": True,
                    "safe_handle_source_window_start_us": 0,
                    "safe_handle_source_window_end_us": 1_200_000,
                },
            )
            caption = CaptionRenderUnit(
                caption_id="cap_001",
                timeline_segment_ids=[segment.segment_id],
                word_ids=list(segment.word_ids),
                text=segment.text,
                target_start_us=segment.target_start_us,
                target_end_us=segment.target_end_us,
                source_subtitle_uids=["s001"],
                style_template_id="canonical_caption_template",
                spoken_source_start_us=segment.spoken_source_start_us,
                spoken_source_end_us=segment.spoken_source_end_us,
                containing_video_segment_id=segment.segment_id,
            )
            template = report.resolved_template_map[base.segment_id]["current_video_segment_template"]

            projected = project_video_segment_from_template(template, segment, 1, 1.2)

            self.assertLess(timerange_start(projected["target_timerange"]), caption.target_start_us)
            self.assertGreater(
                timerange_start(projected["target_timerange"]) + timerange_duration(projected["target_timerange"]),
                caption.target_end_us,
            )
            self.assertEqual(caption.target_start_us, 300_000)
            self.assertEqual(caption.target_end_us, 600_000)

    def test_writeback_and_speed_gate_share_safe_handle_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _make_12x_result(root)
            report = run_report_from_result(result)
            base = report.final_timeline[0]
            segment = replace(
                base,
                source_start_us=300_000,
                source_end_us=600_000,
                spoken_source_start_us=300_000,
                spoken_source_end_us=600_000,
                clip_source_start_us=200_000,
                clip_source_end_us=820_000,
                target_start_us=300_000,
                target_end_us=600_000,
                debug_hints={
                    "safe_handle_policy_enabled": True,
                    "safe_handle_source_window_start_us": 0,
                    "safe_handle_source_window_end_us": 1_200_000,
                },
            )
            template = report.resolved_template_map[base.segment_id]["current_video_segment_template"]
            projected = project_video_segment_from_template(template, segment, 1, 1.2)
            writeback_row = RealDraftWriteback()._video_segment_from_template(template, segment, 1, result.draft_data)
            gate = build_effective_speed_gate(
                final_timeline=[segment],
                resolved_template_map=report.resolved_template_map,
                draft_data=result.draft_data,
            )

            self.assertEqual(writeback_row["source_timerange"], projected["source_timerange"])
            self.assertEqual(writeback_row["target_timerange"], projected["target_timerange"])
            self.assertEqual(gate["segment_reports"][0]["source_duration_us"], timerange_duration(writeback_row["source_timerange"]))
            self.assertEqual(gate["segment_reports"][0]["target_duration_us"], timerange_duration(writeback_row["target_timerange"]))

    def test_v35_speed_drift_regression_still_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _make_12x_result(root)
            report = run_report_from_result(result)
            base = report.final_timeline[0]
            segment = replace(
                base,
                source_start_us=300_000,
                source_end_us=600_000,
                spoken_source_start_us=300_000,
                spoken_source_end_us=600_000,
                clip_source_start_us=200_000,
                clip_source_end_us=820_000,
                target_start_us=300_000,
                target_end_us=500_000,
                debug_hints={
                    "safe_handle_policy_enabled": True,
                    "safe_handle_source_window_start_us": 0,
                    "safe_handle_source_window_end_us": 1_200_000,
                },
            )

            gate = build_effective_speed_gate(
                final_timeline=[segment],
                resolved_template_map=report.resolved_template_map,
                draft_data=result.draft_data,
            )

            self.assertFalse(gate["gate_passed"])
            self.assertEqual(gate["effective_speed_drift_count"], 1)
            self.assertIn("V21_EFFECTIVE_SPEED_DRIFT", gate["blocker_codes"])

    def test_effective_speed_invariant_12x_no_handle_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _make_12x_result(root)
            report = run_report_from_result(result)
            segment = replace(report.final_timeline[0], clip_source_start_us=0, clip_source_end_us=520_000)
            resolved = report.resolved_template_map

            gate = build_effective_speed_gate(
                final_timeline=[segment],
                resolved_template_map=resolved,
                draft_data=result.draft_data,
            )

            self.assertTrue(gate["gate_passed"])
            self.assertEqual(gate["effective_speed_drift_count"], 0)
            self.assertAlmostEqual(gate["effective_speed_min"], 1.2, delta=0.01)
            self.assertAlmostEqual(gate["effective_speed_max"], 1.2, delta=0.01)

    def test_220ms_handle_does_not_change_written_effective_speed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _make_12x_result(root)
            report = run_report_from_result(result)
            segment = replace(
                report.final_timeline[0],
                spoken_source_start_us=100_000,
                spoken_source_end_us=400_000,
                clip_source_start_us=0,
                clip_source_end_us=620_000,
                lead_handle_us=220_000,
                tail_handle_us=220_000,
            )

            gate = build_effective_speed_gate(
                final_timeline=[segment],
                resolved_template_map=report.resolved_template_map,
                draft_data=result.draft_data,
            )

            self.assertTrue(gate["gate_passed"])
            self.assertAlmostEqual(gate["segment_reports"][0]["effective_speed"], 1.2, delta=0.01)

    def test_writeback_rejects_or_reports_13x_15x_17x_speed_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _make_12x_result(root)
            report = run_report_from_result(result)
            drifted = replace(report.final_timeline[0], target_end_us=report.final_timeline[0].target_start_us + 360_000)

            gate = build_effective_speed_gate(
                final_timeline=[drifted],
                resolved_template_map=report.resolved_template_map,
                draft_data=result.draft_data,
            )

            self.assertFalse(gate["gate_passed"])
            self.assertEqual(gate["effective_speed_drift_count"], 1)
            self.assertIn("V21_EFFECTIVE_SPEED_DRIFT", gate["blocker_codes"])

    def test_ready_requires_effective_speed_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = _make_12x_result(root)
            report = run_report_from_result(result)
            drifted = replace(report.final_timeline[0], target_end_us=report.final_timeline[0].target_start_us + 360_000)
            report = replace(report, final_timeline=[drifted], resolved_template_map={}, source_binding_report={})

            preflight = DynamicSourceBindingPreflight(root_mirror_func=fake_root_mirror_not_required).preflight(
                draft_dir=draft_dir,
                real_draft_result=result,
                run_report=report,
                run_dir=root / "run",
            )

            self.assertFalse(preflight.success)
            self.assertEqual(preflight.blockers[0].code, "V21_EFFECTIVE_SPEED_DRIFT")
            self.assertFalse(preflight.report["effective_speed_gate_passed"])
            self.assertEqual(preflight.report["effective_speed_drift_count"], 1)
            self.assertEqual(preflight.report["effective_speed_projected_row_count"], 1)
            self.assertEqual(preflight.report["effective_speed_projected_row_missing_count"], 0)

    def test_effective_speed_gate_uses_projected_write_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _make_12x_result(root)
            report = run_report_from_result(result)
            segment = report.final_timeline[0]
            binding = report.resolved_template_map[segment.segment_id]
            template = binding["current_video_segment_template"]
            projected = project_video_segment_from_template(template, segment, 1, 1.2)

            gate = build_effective_speed_gate(
                final_timeline=[segment],
                resolved_template_map=report.resolved_template_map,
                draft_data=result.draft_data,
            )

            self.assertEqual(gate["segment_reports"][0]["source_duration_us"], timerange_duration(projected["source_timerange"]))
            self.assertEqual(gate["segment_reports"][0]["target_duration_us"], timerange_duration(projected["target_timerange"]))

    def test_effective_speed_gate_fails_when_projected_rows_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = _make_12x_result(root)
            report = run_report_from_result(result)

            gate = build_effective_speed_gate(
                final_timeline=report.final_timeline,
                resolved_template_map={},
                draft_data=result.draft_data,
            )

            self.assertFalse(gate["gate_passed"])
            self.assertEqual(gate["segment_reports"], [])
            self.assertEqual(gate["effective_speed_projected_row_missing_count"], len(report.final_timeline))
            self.assertIn("V21_EFFECTIVE_SPEED_PROJECTED_ROWS_MISSING", gate["blocker_codes"])


if __name__ == "__main__":
    unittest.main()
