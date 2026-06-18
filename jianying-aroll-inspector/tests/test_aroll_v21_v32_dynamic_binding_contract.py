from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import json

from aroll_v21 import ArollEngine, ArollRunInput
from aroll_v21.ingest.external_word_timeline_adapter import ExternalWordTimelineAdapter
from aroll_v21.ir.models import FinalTimelineSegment
from aroll_v21.writeback.dynamic_source_binder import CurrentDraftInventory, DynamicSourceBinder
from tests.test_aroll_v21_fresh_draft_source_segment_rebind import bind_video_identity
from tests.test_aroll_v21_real_writeback_backend import preflight_source_templates, run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result


class ArollV21V32DynamicBindingContractTests(unittest.TestCase):
    def test_two_draft_same_clean_timeline_binds_different_internal_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_a, _content_a, _template_a = create_disposable_draft(root / "a")
            draft_b, _content_b, _template_b = create_disposable_draft(root / "b")
            clean_report = run_report_from_result(fake_real_draft_result(root=root / "logical"))
            result_a = bind_video_identity(fake_real_draft_result(root=root / "a"), source_segment_id="current_a", source_material_id="mat_a")
            result_b = bind_video_identity(fake_real_draft_result(root=root / "b"), source_segment_id="current_b", source_material_id="mat_b")

            preflight_a = preflight_source_templates(draft_dir=draft_a, real_draft_result=result_a, run_report=clean_report)
            preflight_b = preflight_source_templates(draft_dir=draft_b, real_draft_result=result_b, run_report=clean_report)

            self.assertTrue(preflight_a.success)
            self.assertTrue(preflight_b.success)
            map_a = preflight_a.report["resolved_template_map"]
            map_b = preflight_b.report["resolved_template_map"]
            only_segment = clean_report.final_timeline[0].segment_id
            self.assertEqual(clean_report.final_timeline[0].source_segment_id, None)
            self.assertNotEqual(map_a[only_segment]["current_source_segment_id"], map_b[only_segment]["current_source_segment_id"])

    def test_external_physical_ids_ignored_even_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            external_path = root / "word_timeline.json"
            external_path.write_text(
                json.dumps(
                    [
                        {
                            "word_id": "w_ext",
                            "text": "测试",
                            "source_start_us": 100_000,
                            "source_end_us": 400_000,
                            "subtitle_uid": "s001",
                            "subtitle_index": 1,
                            "source_segment_id": "stale_segment",
                            "source_material_id": "stale_material",
                            "material_id": "stale_material",
                            "track_id": "stale_track",
                        }
                    ],
                    ensure_ascii=False,
                ),
                "utf-8",
            )
            external = ExternalWordTimelineAdapter().load(external_path)
            result = fake_real_draft_result(root=root)

            report = ArollEngine().run(
                ArollRunInput(
                    mode="write",
                    draft_data=result.draft_data,
                    word_timeline=external.words,
                    subtitles=[{"subtitle_uid": "s001", "subtitle_index": 1, "text": "测试", "word_ids": ["w_ext"]}],
                    source_segments=result.source_segments,
                    source_materials=result.source_materials,
                    text_materials=result.text_materials,
                    text_segments=result.text_segments,
                    postwrite_mode="simulated",
                )
            )

        self.assertEqual(external.metadata["stripped_physical_id_count"], 4)
        self.assertTrue(report.final_timeline)
        self.assertEqual(report.source_graph.words[0].source_material_id, "")
        self.assertIsNone(report.source_graph.words[0].source_segment_id)
        self.assertIsNone(report.final_timeline[0].source_segment_id)
        self.assertEqual(report.final_timeline[0].source_material_id, "")

    def test_dynamic_binder_rejects_logical_source_segment_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            report = run_report_from_result(result)
            polluted = replace(report.final_timeline[0], source_segment_id="clip")
            preflight = preflight_source_templates(
                draft_dir=draft_dir,
                real_draft_result=result,
                run_report=replace(report, final_timeline=[polluted], resolved_template_map={}, source_binding_report={}),
            )

            self.assertFalse(preflight.success)
            self.assertEqual(preflight.blockers[0].code, "V21_DYNAMIC_BINDING_FORBIDS_LOGICAL_SOURCE_SEGMENT_ID")

    def test_dynamic_binder_primary_video_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            result.draft_data["tracks"][0]["segments"] = []
            result.draft_data["materials"]["videos"] = []
            result = replace(result, source_segments=[], source_materials=[])
            report = run_report_from_result(fake_real_draft_result(root=root / "logical"))

            preflight = preflight_source_templates(draft_dir=draft_dir, real_draft_result=result, run_report=report)

            self.assertFalse(preflight.success)
            self.assertEqual(preflight.blockers[0].code, "V21_DYNAMIC_BINDING_PRIMARY_VIDEO_MISSING")

    def test_dynamic_binder_primary_video_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            second = dict(result.source_segments[0], id="clip_b", material_id="main_video_b", track_id="video_track_b")
            result.source_segments.append(second)
            result.source_materials.append({"source_material_id": "main_video_b", "type": "video", "duration_us": 1_000_000})
            result.draft_data["materials"]["videos"].append({"id": "main_video_b", "type": "video", "duration": 1_000_000})
            result.draft_data["tracks"].append({"id": "video_track_b", "type": "video", "segments": [second]})
            report = run_report_from_result(fake_real_draft_result(root=root / "logical"))

            preflight = preflight_source_templates(draft_dir=draft_dir, real_draft_result=result, run_report=report)

            self.assertFalse(preflight.success)
            self.assertEqual(preflight.blockers[0].code, "V21_DYNAMIC_BINDING_PRIMARY_VIDEO_AMBIGUOUS")

    def test_dynamic_binder_missing_range_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _content, _template = create_disposable_draft(root)
            result = bind_video_identity(fake_real_draft_result(root=root), source_segment_id="current", source_material_id="mat", duration_us=200_000)
            report = run_report_from_result(fake_real_draft_result(root=root / "logical"))

            preflight = preflight_source_templates(draft_dir=draft_dir, real_draft_result=result, run_report=report)

            self.assertFalse(preflight.success)
            self.assertEqual(preflight.blockers[0].code, "V21_DYNAMIC_BINDING_MISSING")

    def test_dynamic_binder_ambiguous_range_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            second = dict(result.source_segments[0], id="clip_overlap", material_id="main_video_b")
            result.source_segments.append(second)
            result.source_materials.append({"source_material_id": "main_video_b", "type": "video", "duration_us": 1_000_000})
            result.draft_data["materials"]["videos"].append({"id": "main_video_b", "type": "video", "duration": 1_000_000})
            result.draft_data["tracks"][0]["segments"].append(second)
            report = run_report_from_result(fake_real_draft_result(root=root / "logical"))

            preflight = preflight_source_templates(draft_dir=draft_dir, real_draft_result=result, run_report=report)

            self.assertFalse(preflight.success)
            self.assertEqual(preflight.blockers[0].code, "V21_DYNAMIC_BINDING_AMBIGUOUS")

    def test_dynamic_binder_binds_second_video_segment_by_target_timeline_coordinate(self) -> None:
        inventory = CurrentDraftInventory(
            video_segments=[
                {
                    "id": "current_video_seg_1",
                    "track_id": "video_track",
                    "track_type": "video",
                    "material_id": "video_1",
                    "source_timerange": {"start": 0, "duration": 172_280_000},
                    "target_timerange": {"start": 0, "duration": 143_566_666},
                },
                {
                    "id": "current_video_seg_2",
                    "track_id": "video_track",
                    "track_type": "video",
                    "material_id": "video_2",
                    "source_timerange": {"start": 0, "duration": 136_520_000},
                    "target_timerange": {"start": 143_566_666, "duration": 113_766_667},
                },
            ],
            video_materials=[
                {"source_material_id": "video_1", "type": "video", "duration_us": 172_280_000},
                {"source_material_id": "video_2", "type": "video", "duration_us": 136_520_000},
            ],
            draft_data={},
        )
        final_segment = FinalTimelineSegment(
            "seg_after_boundary",
            "",
            None,
            145_000_000,
            146_000_000,
            0,
            1_000_000,
            ["w_after"],
            "后段",
            [],
            clip_source_start_us=145_000_000,
            clip_source_end_us=146_000_000,
        )

        result = DynamicSourceBinder(inventory).bind([final_segment], None)

        self.assertTrue(result.success)
        self.assertEqual(
            result.report["resolved_template_map"]["seg_after_boundary"]["current_source_segment_id"],
            "current_video_seg_2",
        )
        self.assertEqual(
            result.report["resolved_template_map"]["seg_after_boundary"]["template_target_start_us"],
            143_566_666,
        )


if __name__ == "__main__":
    unittest.main()
