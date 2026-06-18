from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput
from aroll_v21.ir import CandidateEvidence, RepeatCluster


ROOT = Path(__file__).resolve().parents[1]


class DropMiddleEvidenceBuilder:
    def build(self, source_graph):
        middle = source_graph.edit_units[1]
        right = source_graph.edit_units[2]
        evidence = CandidateEvidence(
            evidence_id="drop_middle_evidence",
            evidence_type="exact_repeat",
            unit_ids=[middle.unit_id, right.unit_id],
            word_ids=[*middle.word_ids, *right.word_ids],
            text=f"{middle.text} {right.text}",
            normalized_text=f"{middle.normalized_text}{right.normalized_text}",
            reason="fixture drops middle before pre-emit prefix normalization",
            confidence=1.0,
            requires_semantic_decision=False,
        )
        return [
            RepeatCluster(
                cluster_id="repeat_drop_middle",
                variants=[middle, right],
                repeat_type="exact_repeat",
                evidence=[evidence],
                local_recommendation="keep_right_drop_left",
            )
        ]


def _round9_input(left: str, right: str) -> ArollRunInput:
    fixture = json.loads((ROOT / "fixtures" / "real_materials" / "normal_caption_template.json").read_text("utf-8"))
    materials = []
    segments = []
    for index, material_id in enumerate(["text_left", "text_middle", "text_right"]):
        material = copy.deepcopy(fixture["material"])
        segment = copy.deepcopy(fixture["segment"])
        material["id"] = material_id
        segment["id"] = f"{material_id}_segment"
        segment["material_id"] = material_id
        segment["target_timerange"] = {"start": index * 600_000, "duration": 500_000}
        materials.append(material)
        segments.append(segment)
    return ArollRunInput(
        source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 2_000_000}],
        word_timeline=[
            {"word_id": "w_left", "word_text": left, "source_start_us": 0, "source_end_us": 500_000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s_left", "subtitle_index": 1},
            {"word_id": "w_middle", "word_text": "中间", "source_start_us": 540_000, "source_end_us": 580_000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s_middle", "subtitle_index": 2},
            {"word_id": "w_right", "word_text": right, "source_start_us": 620_000, "source_end_us": 1_200_000, "source_material_id": "main", "source_segment_id": "clip", "subtitle_uid": "s_right", "subtitle_index": 3},
        ],
        subtitles=[
            {"subtitle_uid": "s_left", "subtitle_index": 1, "text": left, "word_ids": ["w_left"], "text_material_id": "text_left"},
            {"subtitle_uid": "s_middle", "subtitle_index": 2, "text": "中间", "word_ids": ["w_middle"], "text_material_id": "text_middle"},
            {"subtitle_uid": "s_right", "subtitle_index": 3, "text": right, "word_ids": ["w_right"], "text_material_id": "text_right"},
        ],
        text_materials=materials,
        text_segments=segments,
        postwrite_mode="simulated",
    )


class ArollV21BoundaryPrefixContainmentE2ERound9Tests(unittest.TestCase):
    def test_round9_comment_sample_is_removed_after_final_adjacency_changes(self) -> None:
        report = ArollEngine(evidence_builder=DropMiddleEvidenceBuilder()).run(_round9_input("评论区也全是哇", "评论区也全是哇塞"))

        self.assertEqual(report.status, "ok", [blocker.code for blocker in report.blocker_report.blockers])
        self.assertEqual([segment.text for segment in report.final_timeline], ["评论区也全是哇塞"])
        self.assertEqual([caption.text for caption in report.captions], ["评论区也全是哇塞"])
        self.assertTrue(report.validator_report["final_repeat_validator"]["final_repeat_gate_passed"])
        self.assertTrue(report.validator_report["hidden_audio_repeat_validator"]["hidden_audio_repeat_gate_passed"])
        self.assertTrue(any(row.get("stage") == "final_timeline_pre_emit" for row in report.decision_trace))

    def test_round9_reopen_sample_is_removed_after_final_adjacency_changes(self) -> None:
        report = ArollEngine(evidence_builder=DropMiddleEvidenceBuilder()).run(_round9_input("重新上", "重新上桌"))

        self.assertEqual(report.status, "ok", [blocker.code for blocker in report.blocker_report.blockers])
        self.assertEqual([segment.text for segment in report.final_timeline], ["重新上桌"])
        self.assertEqual([caption.text for caption in report.captions], ["重新上桌"])


if __name__ == "__main__":
    unittest.main()
