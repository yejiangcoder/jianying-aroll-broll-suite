from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aroll_subtitle_style_integrity_gate import audit_subtitle_style_integrity


class SubtitleStyleTransformGateTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
