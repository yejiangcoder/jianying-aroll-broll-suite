from __future__ import annotations

import json
import unittest

from aroll_v21.compiler import FinalTimelineCompiler
from aroll_v21.decision import SemanticDecisionPlanner, SemanticDecisionsJsonPlanner
from aroll_v21.evidence import CandidateEvidenceBuilder
from aroll_v21.ingest import DraftIngest
from aroll_v21.render import SubtitleRenderer


def _graph_for_text(text: str):
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
                "source_end_us": cursor + 90_000,
                "source_material_id": "main",
                "source_segment_id": "clip",
                "subtitle_uid": "s_001",
                "subtitle_index": 1,
            }
        )
        cursor += 90_000
    return DraftIngest().build_source_graph(
        word_timeline=words,
        subtitles=[{"subtitle_uid": "s_001", "subtitle_index": 1, "text": text, "word_ids": word_ids}],
        source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": cursor + 1_000_000}],
    )


class ArollV21SingleVariantModifierRedundancyTests(unittest.TestCase):
    def test_safe_single_variant_modifier_redundancy_generates_split_without_payload(self) -> None:
        source_graph = _graph_for_text("快乐的开心的孩子")
        clusters = CandidateEvidenceBuilder().build(source_graph)
        plan = SemanticDecisionPlanner().plan(clusters)

        self.assertEqual(plan.semantic_request_payloads, [])
        self.assertEqual(len(plan.split_decisions), 1)
        split = plan.split_decisions[0]
        self.assertEqual(split.drop_word_ids, ["w_000001", "w_000002", "w_000003"])
        self.assertEqual(split.keep_word_ids, ["w_000004", "w_000005", "w_000006", "w_000007", "w_000008"])
        payload_text = json.dumps([split.metadata], ensure_ascii=False)
        self.assertNotIn("source_start_us", payload_text)
        self.assertNotIn("source_end_us", payload_text)
        self.assertNotIn("target_start_us", payload_text)
        self.assertNotIn("target_end_us", payload_text)

    def test_drop_redundant_modifier_updates_word_ids_and_caption_text(self) -> None:
        source_graph = _graph_for_text("快乐的开心的孩子")
        clusters = CandidateEvidenceBuilder().build(source_graph)
        plan = SemanticDecisionPlanner(
            deepseek_planner=SemanticDecisionsJsonPlanner(
                [
                    {
                        "cluster_id": "repeat_002000",
                        "decision": "drop_redundant_modifier",
                        "reason": "remove redundant left modifier before same head",
                        "confidence": 0.8,
                        "requires_human_review": False,
                    }
                ]
            )
        ).plan(clusters)

        final_timeline, blockers = FinalTimelineCompiler().compile(source_graph, plan)
        captions = SubtitleRenderer().render(final_timeline, source_graph)

        self.assertEqual(blockers, [])
        self.assertEqual(plan.semantic_unresolved_count, 0)
        self.assertEqual([segment.text for segment in final_timeline], ["开心的孩子"])
        self.assertEqual([caption.text for caption in captions], ["开心的孩子"])
        self.assertEqual(final_timeline[0].word_ids, ["w_000004", "w_000005", "w_000006", "w_000007", "w_000008"])
        self.assertEqual(final_timeline[0].target_start_us, 0)
        self.assertGreater(final_timeline[0].target_end_us, final_timeline[0].target_start_us)


if __name__ == "__main__":
    unittest.main()
