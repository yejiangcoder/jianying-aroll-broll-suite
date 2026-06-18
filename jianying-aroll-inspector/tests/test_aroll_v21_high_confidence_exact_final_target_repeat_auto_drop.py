from __future__ import annotations

import unittest

from aroll_v21 import ArollEngine, ArollRunInput
from aroll_v21.decision.final_target_repeat_resolver import FinalTargetRepeatResolver
from aroll_v21.ir import DecisionPlan
from tests.test_aroll_v21_captions_after_prefix_drop import _template_rows
from tests.test_aroll_v21_final_target_repeat_resolver import segment


class ArollV21HighConfidenceExactFinalTargetRepeatAutoDropTests(unittest.TestCase):
    def test_exact_high_repeat_auto_drops_without_semantic_request(self) -> None:
        plan = DecisionPlan(decisions=[])
        final_timeline, blockers = FinalTargetRepeatResolver().resolve(
            [segment(1, "把输掉的"), segment(2, "中间过渡"), segment(3, "把输掉的")],
            plan,
        )

        self.assertEqual(blockers, [])
        self.assertEqual([segment.text for segment in final_timeline], ["中间过渡", "把输掉的"])
        self.assertEqual(plan.semantic_request_payloads, [])
        self.assertEqual(plan.semantic_unresolved_count, 0)
        traces = [row for row in plan.decision_trace if row.get("decision") == "auto_drop_high_confidence_exact_repeat"]
        self.assertTrue(traces)
        self.assertEqual(traces[0]["text"], "把输掉的")

    def test_full_chain_exact_high_repeat_passes_final_repeat_gates_and_aligns_outputs(self) -> None:
        materials, text_segments = _template_rows()
        report = ArollEngine().run(
            ArollRunInput(
                source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 2_000_000}],
                word_timeline=[
                    {
                        "word_id": "w_001",
                        "word_text": "把输掉的",
                        "source_start_us": 0,
                        "source_end_us": 400_000,
                        "source_material_id": "main",
                        "source_segment_id": "clip",
                        "subtitle_uid": "s_001",
                        "subtitle_index": 1,
                    },
                    {
                        "word_id": "w_002",
                        "word_text": "中间过渡",
                        "source_start_us": 500_000,
                        "source_end_us": 900_000,
                        "source_material_id": "main",
                        "source_segment_id": "clip",
                        "subtitle_uid": "s_002",
                        "subtitle_index": 2,
                    },
                    {
                        "word_id": "w_003",
                        "word_text": "把输掉的",
                        "source_start_us": 1_000_000,
                        "source_end_us": 1_400_000,
                        "source_material_id": "main",
                        "source_segment_id": "clip",
                        "subtitle_uid": "s_003",
                        "subtitle_index": 3,
                    },
                ],
                subtitles=[
                    {"subtitle_uid": "s_001", "subtitle_index": 1, "text": "把输掉的", "word_ids": ["w_001"], "text_material_id": "template_text"},
                    {"subtitle_uid": "s_002", "subtitle_index": 2, "text": "中间过渡", "word_ids": ["w_002"], "text_material_id": "template_text"},
                    {"subtitle_uid": "s_003", "subtitle_index": 3, "text": "把输掉的", "word_ids": ["w_003"], "text_material_id": "template_text"},
                ],
                text_materials=materials,
                text_segments=text_segments,
                postwrite_mode="simulated",
            )
        )

        self.assertEqual(report.status, "ok", [blocker.code for blocker in report.blocker_report.blockers])
        self.assertEqual([caption.text for caption in report.captions], ["中间过渡", "把输掉的"])
        self.assertEqual(report.decision_plan.semantic_request_payloads, [])
        self.assertTrue(report.validator_report["final_repeat_validator"]["final_repeat_gate_passed"])
        self.assertTrue(report.validator_report["hidden_audio_repeat_validator"]["hidden_audio_repeat_gate_passed"])
        rough = report.validator_report["rough_cut_quality_validator"]
        self.assertEqual(rough["segments_lt_300ms"], 0)
        self.assertEqual(rough["one_char_captions"], 0)
        self.assertEqual(len(report.final_timeline), len(report.captions))
        self.assertEqual(len(report.captions), len(report.material_write_plan["materials"]))
        self.assertEqual(len(report.captions), len(report.material_write_plan["segments"]))


if __name__ == "__main__":
    unittest.main()
