from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aroll_v21.ir.models import FinalTimelineSegment

from tests.test_aroll_v21_real_writeback_backend import bind_report_to_result, preflight_source_templates, run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


def mapped_report(result, *, source_start: int, source_end: int, target_start: int = 0, target_end: int = 0):
    report = run_report_from_result(result)
    final_target_end = target_end or (target_start + (source_end - source_start))
    final = FinalTimelineSegment(
        segment_id="v21_seg_map",
        source_material_id="",
        source_segment_id=None,
        source_start_us=source_start,
        source_end_us=source_end,
        target_start_us=target_start,
        target_end_us=final_target_end,
        word_ids=["w001"],
        text="测试",
        decision_ids=[],
    )
    caption = replace(
        report.captions[0],
        timeline_segment_ids=["v21_seg_map"],
        target_start_us=target_start,
        target_end_us=final_target_end,
        spoken_source_start_us=source_start,
        spoken_source_end_us=source_end,
        containing_video_segment_id="v21_seg_map",
    )
    return bind_report_to_result(
        replace(report, final_timeline=[final], captions=[caption], resolved_template_map={}, source_binding_report={}),
        result,
    )


class ArollV21WritebackV20SourceTimeMappingTests(unittest.TestCase):
    def test_source_timeline_time_maps_to_material_time_when_old_segment_has_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            result.source_segments[0]["source_timerange"] = {"start": 2_000_000, "duration": 1_000_000}
            result.source_segments[0]["target_timerange"] = {"start": 5_000_000, "duration": 1_000_000}
            result.draft_data["tracks"][0]["segments"][0] = result.source_segments[0]
            report = mapped_report(result, source_start=5_100_000, source_end=5_400_000, target_end=300_000)

            writeback_result = fake_real_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            written = json.loads(draft_content.read_text("utf-8"))
            video_track = next(track for track in written["tracks"] if track["id"] == "video_track")
            self.assertEqual(video_track["segments"][0]["source_timerange"]["start"], 2_100_000)
            self.assertEqual(video_track["segments"][0]["source_timerange"]["duration"], 300_000)

    def test_speed_one_point_two_uses_material_duration_ratio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            result.source_segments[0]["speed"] = 1.2
            result.source_segments[0]["source_timerange"] = {"start": 2_000_000, "duration": 1_200_000}
            result.source_segments[0]["target_timerange"] = {"start": 5_000_000, "duration": 1_000_000}
            result.draft_data["tracks"][0]["segments"][0] = result.source_segments[0]
            report = mapped_report(result, source_start=5_100_000, source_end=5_400_000, target_end=300_000)

            writeback_result = fake_real_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            written = json.loads(draft_content.read_text("utf-8"))
            video_track = next(track for track in written["tracks"] if track["id"] == "video_track")
            self.assertEqual(video_track["segments"][0]["source_timerange"]["start"], 2_120_000)
            self.assertEqual(video_track["segments"][0]["source_timerange"]["duration"], 360_000)

    def test_reverse_or_curve_speed_blocks(self) -> None:
        for key, value in (("reverse", True), ("curve_speed", {"points": [1.0, 1.2]})):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                draft_dir, _draft_content, _template = create_disposable_draft(root)
                result = fake_real_draft_result(root=root)
                result.source_segments[0][key] = value
                result.draft_data["tracks"][0]["segments"][0] = result.source_segments[0]
                report = mapped_report(result, source_start=100_000, source_end=300_000, target_end=200_000)

                preflight = preflight_source_templates(
                    draft_dir=draft_dir,
                    real_draft_result=result,
                    run_report=report,
                )

                self.assertFalse(preflight.success)
                self.assertEqual(preflight.blockers[0].code, "V21_WRITEBACK_UNSUPPORTED_SPEED_MAPPING")


if __name__ == "__main__":
    unittest.main()
