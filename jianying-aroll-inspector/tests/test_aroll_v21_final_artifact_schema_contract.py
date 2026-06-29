from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aroll_v21.operator import ArollV21OperatorConfig, run_operator
from tests.test_aroll_v21_final_backend_integration_contract import read_json
from tests.test_aroll_v21_full_chain_internal_self_check import ExternalWordTimelineAdapter
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


class ArollV21FinalArtifactSchemaContractTests(unittest.TestCase):
    def test_run_validator_writeback_and_core_artifact_schema_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir, _draft_content, _template = create_disposable_draft(root)
            result = fake_real_draft_result(root=root)

            with patch(
                "aroll_v21.operator.RealDraftIngestAdapter",
                lambda *a, **k: ExternalWordTimelineAdapter(result=result),
            ), patch("aroll_v21.operator.RealDraftWriteback", lambda *a, **k: fake_real_writeback(jy_draftc=k.get("jy_draftc"))):
                run_operator(
                    ArollV21OperatorConfig(
                        mode="write",
                        run_dir=root / "run",
                        draft_dir=draft_dir,
                        jy_draftc=root / "jy-draftc.exe",
                        commit=True,
                        allow_sacrificial_write_without_postwrite_decrypt=True,
                    )
                )

            run_dir = root / "run"
            run_summary = read_json(run_dir / "run_summary.json")
            validator_report = read_json(run_dir / "validator_report.json")
            final_timeline_quality_guard = read_json(run_dir / "final_timeline_quality_guard_report.json")
            blocker_report = read_json(run_dir / "blocker_report.json")
            writeback_report = read_json(run_dir / "writeback_report.json")
            material_write_plan = read_json(run_dir / "material_write_plan.json")
            final_timeline = read_json(run_dir / "final_timeline.json")
            captions = read_json(run_dir / "captions.json")
            semantic_requests = read_json(run_dir / "semantic_request_payloads.json")
            semantic_decisions = read_json(run_dir / "semantic_decisions.json")

            self.assertTrue(
                {
                    "READY_FOR_DISPOSABLE_WRITE_PRE_AUDIT",
                    "write_allowed",
                    "semantic_unresolved_count",
                    "validator_write_allowed",
                    "validator_report_ok",
                    "writer_fallback_count",
                    "fatal_blocker",
                    "ready_for_user_manual_qc",
                    "commit_performed",
                }
                <= set(run_summary)
            )
            self.assertTrue(
                {
                    "rough_cut_quality_validator",
                    "final_repeat_validator",
                    "hidden_audio_repeat_validator",
                    "safe_cut_validator",
                    "subtitle_style_validator",
                    "subtitle_coverage_validator",
                    "postwrite_material_validator",
                    "final_timeline_quality_guard_report",
                }
                <= set(validator_report)
            )
            self.assertTrue(
                {
                    "gate_passed",
                    "write_gate_passed",
                    "blocking_candidate_count",
                    "blocker_codes",
                    "repair_intent_report",
                }
                <= set(final_timeline_quality_guard)
            )
            self.assertIn("final_timeline_quality_guard_gate", validator_report["quality_gate_report"])
            self.assertIn("final_timeline_quality_guard_gate_passed", run_summary)
            self.assertIn("final_timeline_repair_intent_count", run_summary)
            self.assertTrue({"blocked", "blockers", "summary"} <= set(blocker_report))
            self.assertTrue(
                {
                    "writeback_success",
                    "commit_performed",
                    "encrypt_success",
                    "target_writes",
                    "selected_text_track_id",
                    "selected_video_track_id",
                    "non_subtitle_text_tracks_preserved",
                    "non_subtitle_text_segments_preserved",
                    "non_subtitle_text_materials_preserved",
                    "canonical_caption_segment_count",
                    "visible_caption_track_count",
                    "old_subtitle_residue_track_count",
                    "rough_cut_quality",
                }
                <= set(writeback_report)
            )
            self.assertTrue({"materials", "segments", "writer_fallback_count", "template_report"} <= set(material_write_plan))
            self.assertIsInstance(final_timeline, list)
            self.assertIsInstance(captions, list)
            self.assertIsInstance(semantic_requests, list)
            self.assertIsInstance(semantic_decisions, list)
            if final_timeline:
                self.assertTrue({"segment_id", "target_start_us", "target_end_us", "word_ids", "text"} <= set(final_timeline[0]))
            if captions:
                self.assertTrue({"caption_id", "timeline_segment_ids", "word_ids", "text"} <= set(captions[0]))


if __name__ == "__main__":
    unittest.main()
