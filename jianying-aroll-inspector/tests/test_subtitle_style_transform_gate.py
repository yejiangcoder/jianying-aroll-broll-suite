from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aroll_shared_edit_utils import clone_text_material, material_text_rows
from aroll_subtitle_style_integrity_gate import audit_subtitle_style_integrity


class SubtitleStyleTransformGateTest(unittest.TestCase):
    def test_clone_text_material_preserves_content_json_style_payload(self) -> None:
        content = json.dumps(
            {
                "styles": [{"range": [0, 2], "font": {"size": 36}, "fill": {"color": "#ffffff"}}],
                "text": "旧字幕",
            },
            ensure_ascii=False,
        )
        material = {
            "id": "m1",
            "text": "旧字幕",
            "recognize_text": "旧字幕",
            "content": content,
            "base_content": content,
            "nested": {"content": "must stay untouched"},
        }

        cloned = clone_text_material(material, "m2", "新字幕")

        self.assertEqual(cloned["id"], "m2")
        self.assertEqual(cloned["text"], "新字幕")
        self.assertEqual(cloned["recognize_text"], "新字幕")
        content_payload = json.loads(cloned["content"])
        base_payload = json.loads(cloned["base_content"])
        self.assertEqual(content_payload["text"], "新字幕")
        self.assertEqual(base_payload["text"], "新字幕")
        self.assertTrue(content_payload["styles"])
        self.assertEqual(content_payload["styles"], base_payload["styles"])
        self.assertEqual(cloned["nested"]["content"], "must stay untouched")

    def test_style_outlier_transform_test(self) -> None:
        source_material = {"id": "m1", "font_size": 36, "clip": {"transform": {"scale": {"x": 1.0, "y": 1.0}, "position": {"x": 0, "y": -0.72}}}}
        source_segment = {"id": "s1", "type": "text", "material_id": "m1", "target_timerange": {"start": 0, "duration": 1000}}
        final_material = {"id": "m2", "font_size": 36, "clip": {"transform": {"scale": {"x": 4.0, "y": 4.0}, "position": {"x": 0, "y": 0.0}}}}
        final_segment = {"id": "s2", "type": "text", "material_id": "m2", "target_timerange": {"start": 0, "duration": 1000}}
        report = audit_subtitle_style_integrity(
            [{"material": source_material, "segment": source_segment}],
            [final_segment],
            [final_material],
        )
        self.assertFalse(report["style_integrity_gate_passed"])
        self.assertGreater(report["transform_outlier_count"], 0)

    def test_template_fingerprint_gate_added(self) -> None:
        source_material = {"id": "m1", "font_size": 36, "template": "caption"}
        source_segment = {"id": "s1", "type": "text", "material_id": "m1", "target_timerange": {"start": 0, "duration": 1000}}
        final_material = {"id": "m2", "font_size": 36, "template": "title"}
        final_segment = {"id": "s2", "type": "text", "material_id": "m2", "target_timerange": {"start": 0, "duration": 1000}}
        report = audit_subtitle_style_integrity(
            [{"material": source_material, "segment": source_segment}],
            [final_segment],
            [final_material],
        )
        self.assertFalse(report["style_integrity_gate_passed"])
        self.assertGreater(report["template_fingerprint_mismatch_count"], 0)

    def test_huge_title_style_used_as_subtitle_fails_even_when_source_contains_it(self) -> None:
        source_material = {"id": "title_m", "font_size": 220, "clip": {"transform": {"scale": {"x": 4.0, "y": 4.0}, "position": {"x": 0, "y": 0}}}}
        source_segment = {"id": "title_s", "type": "text", "material_id": "title_m", "target_timerange": {"start": 0, "duration": 1000}}
        final_material = {"id": "m2", "font_size": 220, "clip": {"transform": {"scale": {"x": 4.0, "y": 4.0}, "position": {"x": 0, "y": 0}}}}
        final_segment = {"id": "s2", "type": "text", "material_id": "m2", "target_timerange": {"start": 0, "duration": 1000}}

        report = audit_subtitle_style_integrity(
            [{"material": source_material, "segment": source_segment}],
            [final_segment],
            [final_material],
        )

        self.assertFalse(report["style_integrity_gate_passed"])
        self.assertGreater(report["style_safety_violation_count"], 0)
        self.assertIn("FONT_SIZE_EXCEEDS_SAFE_LIMIT", report["outliers"][0]["reasons"])

    def test_normal_subtitle_style_passes(self) -> None:
        source_material = {"id": "m1", "font_size": 36, "template": "caption", "clip": {"transform": {"scale": {"x": 1.0, "y": 1.0}, "position": {"x": 0, "y": -0.72}}}}
        source_segment = {"id": "s1", "type": "text", "material_id": "m1", "target_timerange": {"start": 0, "duration": 1000}}
        final_material = {"id": "m2", "font_size": 36, "template": "caption", "clip": {"transform": {"scale": {"x": 1.0, "y": 1.0}, "position": {"x": 0, "y": -0.72}}}}
        final_segment = {"id": "s2", "type": "text", "material_id": "m2", "target_timerange": {"start": 0, "duration": 1000}}

        report = audit_subtitle_style_integrity(
            [{"material": source_material, "segment": source_segment}],
            [final_segment],
            [final_material],
        )

        self.assertTrue(report["style_integrity_gate_passed"])
        self.assertEqual(report["subtitle_style_outlier_count"], 0)

    def test_plain_string_content_fails_style_gate(self) -> None:
        source_content = json.dumps({"styles": [{"range": [0, 2], "font": {"size": 36}}], "text": "source"}, ensure_ascii=False)
        source_material = {"id": "m1", "font_size": 36, "template": "caption", "content": source_content}
        source_segment = {"id": "s1", "type": "text", "material_id": "m1", "target_timerange": {"start": 0, "duration": 1000}}
        final_material = {"id": "m2", "font_size": 36, "template": "caption", "content": "plain subtitle text"}
        final_segment = {"id": "s2", "type": "text", "material_id": "m2", "target_timerange": {"start": 0, "duration": 1000}}

        report = audit_subtitle_style_integrity(
            [{"material": source_material, "segment": source_segment}],
            [final_segment],
            [final_material],
        )

        self.assertFalse(report["style_integrity_gate_passed"])
        self.assertEqual(report["text_content_schema_violation_count"], 1)
        self.assertIn("TEXT_CONTENT_NOT_JSON", report["outliers"][0]["reasons"])

    def test_content_missing_styles_fails_style_gate(self) -> None:
        source_content = json.dumps({"styles": [{"range": [0, 2], "font": {"size": 36}}], "text": "source"}, ensure_ascii=False)
        final_content = json.dumps({"text": "final"}, ensure_ascii=False)
        source_material = {"id": "m1", "font_size": 36, "template": "caption", "content": source_content}
        source_segment = {"id": "s1", "type": "text", "material_id": "m1", "target_timerange": {"start": 0, "duration": 1000}}
        final_material = {"id": "m2", "font_size": 36, "template": "caption", "content": final_content}
        final_segment = {"id": "s2", "type": "text", "material_id": "m2", "target_timerange": {"start": 0, "duration": 1000}}

        report = audit_subtitle_style_integrity(
            [{"material": source_material, "segment": source_segment}],
            [final_segment],
            [final_material],
        )

        self.assertFalse(report["style_integrity_gate_passed"])
        self.assertIn("TEXT_CONTENT_MISSING_STYLES", report["outliers"][0]["reasons"])

    def test_content_schema_mismatch_fails_style_gate(self) -> None:
        source_content = json.dumps({"styles": [{"range": [0, 2], "font": {"size": 36}}], "text": "source"}, ensure_ascii=False)
        final_content = json.dumps(["final"], ensure_ascii=False)
        source_material = {"id": "m1", "font_size": 36, "template": "caption", "content": source_content}
        source_segment = {"id": "s1", "type": "text", "material_id": "m1", "target_timerange": {"start": 0, "duration": 1000}}
        final_material = {"id": "m2", "font_size": 36, "template": "caption", "content": final_content}
        final_segment = {"id": "s2", "type": "text", "material_id": "m2", "target_timerange": {"start": 0, "duration": 1000}}

        report = audit_subtitle_style_integrity(
            [{"material": source_material, "segment": source_segment}],
            [final_segment],
            [final_material],
        )

        self.assertFalse(report["style_integrity_gate_passed"])
        self.assertIn("TEXT_CONTENT_SCHEMA_MISMATCH", report["outliers"][0]["reasons"])

    def test_content_text_and_style_ranges_do_not_cause_template_mismatch(self) -> None:
        source_content = json.dumps(
            {"styles": [{"range": [0, 2], "font": {"size": 36}, "fill": {"color": "#fff"}}], "text": "source"},
            ensure_ascii=False,
        )
        final_content = json.dumps(
            {"styles": [{"range": [0, 9], "font": {"size": 36}, "fill": {"color": "#fff"}}], "text": "different subtitle"},
            ensure_ascii=False,
        )
        source_material = {"id": "m1", "font_size": 36, "template": "caption", "content": source_content}
        source_segment = {"id": "s1", "type": "text", "material_id": "m1", "target_timerange": {"start": 0, "duration": 1000}}
        final_material = {"id": "m2", "font_size": 36, "template": "caption", "content": final_content}
        final_segment = {"id": "s2", "type": "text", "material_id": "m2", "target_timerange": {"start": 0, "duration": 1000}}

        report = audit_subtitle_style_integrity(
            [{"material": source_material, "segment": source_segment}],
            [final_segment],
            [final_material],
        )

        self.assertTrue(report["style_integrity_gate_passed"], report)
        self.assertEqual(report["template_fingerprint_mismatch_count"], 0)
        self.assertEqual(report["text_content_schema_violation_count"], 0)

    def test_content_style_change_still_causes_template_mismatch(self) -> None:
        source_content = json.dumps(
            {"styles": [{"range": [0, 2], "font": {"size": 36}, "fill": {"color": "#fff"}}], "text": "source"},
            ensure_ascii=False,
        )
        final_content = json.dumps(
            {"styles": [{"range": [0, 9], "font": {"size": 64}, "fill": {"color": "#fff"}}], "text": "different subtitle"},
            ensure_ascii=False,
        )
        source_material = {"id": "m1", "font_size": 36, "template": "caption", "content": source_content}
        source_segment = {"id": "s1", "type": "text", "material_id": "m1", "target_timerange": {"start": 0, "duration": 1000}}
        final_material = {"id": "m2", "font_size": 36, "template": "caption", "content": final_content}
        final_segment = {"id": "s2", "type": "text", "material_id": "m2", "target_timerange": {"start": 0, "duration": 1000}}

        report = audit_subtitle_style_integrity(
            [{"material": source_material, "segment": source_segment}],
            [final_segment],
            [final_material],
        )

        self.assertFalse(report["style_integrity_gate_passed"])
        self.assertGreater(report["template_fingerprint_mismatch_count"], 0)

    def test_missing_content_when_source_has_content_fails_style_gate(self) -> None:
        source_content = json.dumps({"styles": [{"range": [0, 2], "font": {"size": 36}}], "text": "source"}, ensure_ascii=False)
        source_material = {"id": "m1", "font_size": 36, "template": "caption", "content": source_content}
        source_segment = {"id": "s1", "type": "text", "material_id": "m1", "target_timerange": {"start": 0, "duration": 1000}}
        final_material = {"id": "m2", "font_size": 36, "template": "caption"}
        final_segment = {"id": "s2", "type": "text", "material_id": "m2", "target_timerange": {"start": 0, "duration": 1000}}

        report = audit_subtitle_style_integrity(
            [{"material": source_material, "segment": source_segment}],
            [final_segment],
            [final_material],
        )

        self.assertFalse(report["style_integrity_gate_passed"])
        self.assertEqual(report["text_content_schema_violation_count"], 1)
        self.assertIn("TEXT_CONTENT_SCHEMA_MISMATCH", report["outliers"][0]["reasons"])

    def test_missing_base_content_when_source_has_base_content_fails_style_gate(self) -> None:
        source_content = json.dumps({"styles": [{"range": [0, 2], "font": {"size": 36}}], "text": "source"}, ensure_ascii=False)
        source_material = {"id": "m1", "font_size": 36, "template": "caption", "base_content": source_content}
        source_segment = {"id": "s1", "type": "text", "material_id": "m1", "target_timerange": {"start": 0, "duration": 1000}}
        final_material = {"id": "m2", "font_size": 36, "template": "caption", "content": source_content}
        final_segment = {"id": "s2", "type": "text", "material_id": "m2", "target_timerange": {"start": 0, "duration": 1000}}

        report = audit_subtitle_style_integrity(
            [{"material": source_material, "segment": source_segment}],
            [final_segment],
            [final_material],
        )

        self.assertFalse(report["style_integrity_gate_passed"])
        self.assertIn("TEXT_CONTENT_SCHEMA_MISMATCH", report["outliers"][0]["reasons"])

    def test_one_abnormal_final_subtitle_segment_fails_gate(self) -> None:
        source_material = {"id": "m1", "font_size": 36, "template": "caption"}
        source_segment = {"id": "s1", "type": "text", "material_id": "m1", "target_timerange": {"start": 0, "duration": 1000}}
        final_materials = [
            {"id": "m2", "font_size": 36, "template": "caption"},
            {"id": "m3", "font_size": 36, "template": "caption"},
        ]
        final_segments = [
            {"id": "s2", "type": "text", "material_id": "m2", "target_timerange": {"start": 0, "duration": 1000}},
            {"id": "s3", "type": "text", "material_id": "m3", "font_size": 160, "target_timerange": {"start": 1000, "duration": 1000}},
        ]

        report = audit_subtitle_style_integrity(
            [{"material": source_material, "segment": source_segment}],
            final_segments,
            final_materials,
        )

        self.assertFalse(report["style_integrity_gate_passed"])
        self.assertEqual(report["subtitle_style_outlier_count"], 1)

    def test_style_gate_checks_final_subtitle_output_objects(self) -> None:
        source_material = {"id": "m1", "font_size": 36, "template": "caption"}
        source_segment = {"id": "s1", "type": "text", "material_id": "m1", "target_timerange": {"start": 0, "duration": 1000}}
        final_material = {"id": "m2", "font_size": 36, "template": "caption", "box": {"width": 0.9, "height": 0.7}}
        final_segment = {"id": "s2", "type": "text", "material_id": "m2", "target_timerange": {"start": 0, "duration": 1000}}

        report = audit_subtitle_style_integrity(
            [{"material": source_material, "segment": source_segment}],
            [final_segment],
            [final_material],
        )

        self.assertFalse(report["style_integrity_gate_passed"])
        self.assertIn("SCREEN_OCCUPANCY_EXCEEDS_SAFE_LIMIT", report["outliers"][0]["reasons"])

    def test_material_text_rows_prefers_safe_caption_style_over_unsafe_source_uid(self) -> None:
        data = {"materials": {"texts": []}}
        source_subtitles = [
            {
                "subtitle_uid": "title_uid",
                "text_material_id": "title_m",
                "material": {"id": "title_m", "font_size": 220, "text": "title"},
                "segment": {"id": "title_s", "type": "text", "material_id": "title_m", "clip": {"transform": {"scale": {"x": 4.0, "y": 4.0}}}},
            },
            {
                "subtitle_uid": "caption_uid",
                "text_material_id": "caption_m",
                "material": {"id": "caption_m", "font_size": 36, "text": "caption"},
                "segment": {"id": "caption_s", "type": "text", "material_id": "caption_m", "clip": {"transform": {"scale": {"x": 1.0, "y": 1.0}}}},
            },
        ]
        display_plan = [
            {
                "fragment_id": "f1",
                "fragment_text": "generated subtitle",
                "target_start_us": 0,
                "target_duration_us": 1000,
                "source_subtitle_uids": ["title_uid"],
            }
        ]

        final_segments, _rows = material_text_rows(data, {}, source_subtitles, display_plan)

        self.assertEqual(data["materials"]["texts"][0]["font_size"], 36)
        self.assertEqual(final_segments[0]["clip"]["transform"]["scale"]["x"], 1.0)


if __name__ == "__main__":
    unittest.main()
