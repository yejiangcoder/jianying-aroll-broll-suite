from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_aroll_v21_real_writeback_backend import run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


ROOT = Path(__file__).resolve().parents[1]


class ArollV21WritebackSubtitleTrackClassificationTests(unittest.TestCase):
    def test_unknown_caption_like_segment_on_subtitle_bound_track_is_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            unknown_material = {"id": "unknown_text_material", "type": "text", "text": "unknown"}
            unknown_segment = {
                "id": "unknown_text_segment",
                "type": "text",
                "material_id": "unknown_text_material",
                "target_timerange": {"start": 500_000, "duration": 500_000},
            }
            result.draft_data["materials"]["texts"].append(unknown_material)
            text_track = next(track for track in result.draft_data["tracks"] if track["id"] == "text_track")
            text_track["segments"].append(unknown_segment)
            result.text_segments.append(unknown_segment | {"track_id": "text_track", "track_type": "text"})
            result.text_materials.append(unknown_material)
            report = run_report_from_result(fake_real_draft_result(root=root))

            writeback_result = fake_real_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            self.assertEqual(writeback_result.report["old_subtitle_segment_count"], 2)
            self.assertEqual(writeback_result.report["post_write_old_subtitle_residue_count"], 0)
            self.assertTrue(writeback_result.report["post_write_actual_text_residue_gate_passed"])
            written = json.loads(draft_content.read_text("utf-8"))
            text_track = next(track for track in written["tracks"] if track["id"] == "text_track")
            self.assertNotIn("unknown_text_segment", {segment["id"] for segment in text_track["segments"]})

    def test_writeback_source_does_not_import_forbidden_paths(self) -> None:
        text = (ROOT / "src" / "aroll_v21" / "writeback" / "real_draft_writeback.py").read_text("utf-8")
        for token in (
            "material_text_rows",
            "aroll_phase4e_full_aroll",
            "aroll_downstream_repair_pipeline",
            "aroll_repair_applier",
            "run_downstream_repair_pipeline",
            "apply_repair_proposals",
        ):
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
