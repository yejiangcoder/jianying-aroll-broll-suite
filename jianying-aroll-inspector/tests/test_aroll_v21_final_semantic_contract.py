from __future__ import annotations

import json
import unittest
from pathlib import Path

from aroll_v21.compiler import FinalTimelineCompiler, RoughCutQualityNormalizer
from aroll_v21.decision import SemanticDecisionPlanner, SemanticDecisionsJsonPlanner
from aroll_v21.evidence import CandidateEvidenceBuilder
from aroll_v21.ingest import DraftIngest
from aroll_v21.ir import DecisionPlan, UnitSplitPlan
from aroll_v21.render import SubtitleRenderer
from aroll_v21.validate import ReadOnlyValidators
from aroll_v21.writer import CaptionMaterialWriter
from tools.create_aroll_v21_semantic_decisions_template import build_suggested_for_rough_cut
from tests.test_aroll_v21_rough_cut_quality_normalizer import make_segment, make_source_graph, make_word


ROOT = Path(__file__).resolve().parents[1]


def _semantic_graph():
    template = json.loads((ROOT / "fixtures" / "real_materials" / "normal_caption_template.json").read_text("utf-8"))
    text = "甲的乙的项"
    words = []
    word_ids = []
    cursor = 0
    for index, char in enumerate(text, start=1):
        word_id = f"w_{index:06d}"
        word_ids.append(word_id)
        words.append(
            {
                "word_id": word_id,
                "word_text": char,
                "source_start_us": cursor,
                "source_end_us": cursor + 120_000,
                "source_material_id": "main",
                "source_segment_id": "clip",
                "subtitle_uid": "s_001",
                "subtitle_index": 1,
            }
        )
        cursor += 120_000
    return DraftIngest().build_source_graph(
        word_timeline=words,
        subtitles=[{"subtitle_uid": "s_001", "subtitle_index": 1, "text": text, "word_ids": word_ids}],
        source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 2_000_000}],
        text_materials=[template["material"]],
        text_segments=[template["segment"]],
    )


class ArollV21FinalSemanticContractTests(unittest.TestCase):
    def test_modifier_payload_template_and_drop_decision_update_text_word_ids_and_validators(self) -> None:
        graph = _semantic_graph()
        clusters = CandidateEvidenceBuilder().build(graph)
        discovery_plan = SemanticDecisionPlanner().plan(clusters)
        self.assertEqual(discovery_plan.semantic_request_payloads, [])
        self.assertEqual(discovery_plan.split_decisions[0].drop_word_ids, ["w_000001", "w_000002"])

        suggested = build_suggested_for_rough_cut(
            [
                {
                    "cluster_id": "repeat_002000",
                    "repeat_type": "modifier_redundancy",
                    "type": "single_variant_modifier_redundancy",
                    "allowed_decisions": ["drop_redundant_modifier", "requires_human_review"],
                    "suggested_for_rough_cut": "drop_redundant_modifier",
                }
            ]
        )
        self.assertEqual(suggested[0]["decision"], "drop_redundant_modifier")

        plan = SemanticDecisionPlanner(
            deepseek_planner=SemanticDecisionsJsonPlanner(
                [
                    {
                        "cluster_id": "repeat_002000",
                        "decision": "drop_redundant_modifier",
                        "reason": "drop redundant modifier before same head",
                        "confidence": 0.9,
                        "requires_human_review": False,
                    }
                ]
            )
        ).plan(clusters)
        final_timeline, blockers = FinalTimelineCompiler().compile(graph, plan)
        captions = SubtitleRenderer().render(final_timeline, graph)
        material_write_plan, writer_blockers = CaptionMaterialWriter().build_write_plan(graph, captions)
        validator_report = ReadOnlyValidators().run(
            source_graph=graph,
            decision_plan=plan,
            final_timeline=final_timeline,
            captions=captions,
            material_write_plan=material_write_plan,
            postwrite_mode="simulated",
        )

        self.assertEqual(blockers, [])
        self.assertEqual(writer_blockers, [])
        self.assertEqual([segment.text for segment in final_timeline], ["乙的项"])
        self.assertEqual(final_timeline[0].word_ids, ["w_000003", "w_000004", "w_000005"])
        self.assertTrue(validator_report["final_repeat_validator"]["final_repeat_gate_passed"])
        self.assertTrue(validator_report["hidden_audio_repeat_validator"]["hidden_audio_repeat_gate_passed"])
        self.assertEqual(validator_report["rough_cut_quality_validator"]["segments_lt_300ms"], 0)
        self.assertEqual(validator_report["rough_cut_quality_validator"]["one_char_captions"], 0)

    def test_semantic_split_residual_prefix_cleanup_drops_prefix_segment(self) -> None:
        graph = make_source_graph(
            [
                make_word("w_keep", "A", 340_000, 620_000, "s1", 1),
                make_word("w_next", "Axxx", 2_400_000, 3_000_000, "s2", 2),
            ],
            source_end_us=4_000_000,
        )
        plan = DecisionPlan(
            decisions=[],
            split_decisions=[
                UnitSplitPlan(
                    split_id="semantic_split_prefix",
                    cluster_id="repeat_002000",
                    unit_id="s1",
                    drop_word_ids=["w_drop"],
                    keep_word_ids=["w_keep"],
                    reason="semantic split leaves prefix residual",
                    source="semantic_decisions_json",
                )
            ],
        )

        final_timeline, blockers = RoughCutQualityNormalizer().normalize(
            [
                make_segment("seg1", "A", 340_000, 620_000, ["w_keep"]),
                make_segment("seg2", "Axxx", 2_400_000, 3_000_000, ["w_next"]),
            ],
            graph,
            plan,
        )

        self.assertEqual(blockers, [])
        self.assertEqual([segment.text for segment in final_timeline], ["Axxx"])
        self.assertTrue(any(row.get("route") == "residual_prefix_containment_drop" for row in plan.decision_trace))


if __name__ == "__main__":
    unittest.main()
