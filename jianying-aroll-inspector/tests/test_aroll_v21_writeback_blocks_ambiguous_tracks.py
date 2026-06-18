from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from aroll_v21.ir.models import FinalTimelineSegment

from tests.test_aroll_v21_real_writeback_backend import bind_report_to_result, preflight_source_templates, run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


class ArollV21WritebackAmbiguousTrackTests(unittest.TestCase):
    def test_multiple_equal_subtitle_track_candidates_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            material = dict(result.text_materials[0])
            material["id"] = "caption_template_002"
            segment = dict(result.text_segments[0])
            segment["id"] = "caption_segment_002"
            segment["material_id"] = "caption_template_002"
            segment["track_id"] = "text_track_2"
            result.text_materials.append(material)
            result.text_segments.append(segment)
            result.draft_data["materials"]["texts"].append(material)
            result.draft_data["tracks"].append({"id": "text_track_2", "type": "text", "segments": [segment]})
            report = run_report_from_result(fake_real_draft_result(root=root))
            material_write_plan = dict(report.material_write_plan)
            template_report = dict(material_write_plan["template_report"])
            template_report["candidate_material_ids"] = ["caption_template_001", "caption_template_002"]
            material_write_plan["template_report"] = template_report
            report = replace(report, material_write_plan=material_write_plan)

            writeback_result = fake_real_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertFalse(writeback_result.success)
            self.assertEqual(writeback_result.blockers[0].code, "V21_WRITEBACK_SUBTITLE_TRACK_NOT_UNIQUE")

    def test_multiple_current_video_track_candidates_block_at_dynamic_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            second_source = dict(result.source_segments[0])
            second_source["id"] = "clip_2"
            second_source["track_id"] = "video_track_2"
            second_source["material_id"] = "main_video_b"
            result.source_segments.append(second_source)
            result.source_materials.append({"source_material_id": "main_video_b", "type": "video", "duration_us": 1000000})
            result.draft_data["materials"]["videos"].append({"id": "main_video_b", "type": "video", "duration": 1000000})
            result.draft_data["tracks"].append({"id": "video_track_2", "type": "video", "segments": [second_source]})
            report = run_report_from_result(fake_real_draft_result(root=root))
            extra = FinalTimelineSegment(
                segment_id="v21_seg_extra",
                source_material_id="",
                source_segment_id=None,
                source_start_us=0,
                source_end_us=100000,
                target_start_us=400000,
                target_end_us=500000,
                word_ids=["w001"],
                text="测试",
                decision_ids=[],
            )
            report = replace(report, final_timeline=[*report.final_timeline, extra], resolved_template_map={}, source_binding_report={})

            preflight = preflight_source_templates(
                draft_dir=draft_dir,
                real_draft_result=result,
                run_report=report,
            )

            self.assertFalse(preflight.success)
            self.assertEqual(preflight.blockers[0].code, "V21_DYNAMIC_BINDING_PRIMARY_VIDEO_AMBIGUOUS")


if __name__ == "__main__":
    unittest.main()
