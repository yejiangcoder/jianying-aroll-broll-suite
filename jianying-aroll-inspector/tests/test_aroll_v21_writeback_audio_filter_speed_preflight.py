from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_aroll_v21_real_writeback_backend import preflight_source_templates, run_report_from_result
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


class ArollV21WritebackAudioFilterSpeedPreflightTests(unittest.TestCase):
    def test_audio_and_global_filter_tracks_are_reported_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            result.draft_data["tracks"].append({"id": "audio_track", "type": "audio", "segments": [{"id": "a1"}]})
            result.draft_data["tracks"].append(
                {"id": "filter_track", "type": "filter", "segments": [{"id": "f1", "target_timerange": {"start": 0, "duration": 1_000_000}}]}
            )
            report = run_report_from_result(result)

            writeback_result = fake_real_writeback().commit(
                draft_dir=draft_dir,
                run_dir=root / "run",
                real_draft_result=result,
                run_report=report,
                sacrificial_write_override_used=True,
            )

            self.assertTrue(writeback_result.success)
            self.assertTrue(writeback_result.report["audio_preflight"]["independent_audio_track_detected"])
            self.assertTrue(writeback_result.report["audio_preflight"]["has_complex_audio"])
            self.assertTrue(writeback_result.report["filter_preflight"]["filter_track_detected"])
            self.assertTrue(writeback_result.report["filter_preflight"]["global_filter_effect_remapped"])

    def test_source_target_ratio_unsafe_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            result.source_segments[0]["source_timerange"] = {"start": 0, "duration": 2_000_000}
            result.source_segments[0]["target_timerange"] = {"start": 0, "duration": 1_000_000}
            result.source_segments[0]["speed"] = 1.0
            result.draft_data["tracks"][0]["segments"][0] = result.source_segments[0]
            report = run_report_from_result(result)

            preflight = preflight_source_templates(
                draft_dir=draft_dir,
                real_draft_result=result,
                run_report=report,
            )

            self.assertFalse(preflight.success)
            self.assertEqual(preflight.blockers[0].code, "V21_WRITEBACK_UNSUPPORTED_SPEED_MAPPING")


if __name__ == "__main__":
    unittest.main()
