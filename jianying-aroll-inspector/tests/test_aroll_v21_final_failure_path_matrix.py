from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aroll_v21 import ArollEngine, ArollRunInput
from aroll_v21.compiler import RoughCutQualityNormalizer
from aroll_v21.decision import SemanticDecisionPlanner, SemanticDecisionsJsonPlanner
from aroll_v21.evidence import CandidateEvidenceBuilder
from aroll_v21.ir import CandidateEvidence, EditUnit, RepeatCluster
from aroll_v21.ir import DecisionPlan
from tests.test_aroll_v21_final_semantic_contract import _semantic_graph
from tests.test_aroll_v21_final_writeback_contract import _run_write_operator
from tests.test_aroll_v21_rough_cut_quality_normalizer import make_segment, make_source_graph, make_word
from tests.test_aroll_v21_sacrificial_write_override import create_disposable_draft, fake_real_draft_result, fake_real_writeback


class MismatchedWriter:
    def build_write_plan(self, _source_graph, _captions):
        return {
            "materials": [{}],
            "segments": [],
            "canonical_caption_template_id": "tmpl",
            "no_writer_fallback": True,
            "writer_fallback_count": 0,
        }, []


class ArollV21FinalFailurePathMatrixTests(unittest.TestCase):
    def test_semantic_and_roughcut_failure_paths_fail_closed(self) -> None:
        graph = _semantic_graph()
        clusters = CandidateEvidenceBuilder().build(graph)

        with self.subTest("semantic request missing"):
            blockers = ArollEngine()._semantic_request_consistency_blockers(
                DecisionPlan(decisions=[]),
                {
                    "final_repeat_validator": {
                        "blocking_issues": [{"type": "adjacent_modifier_semantic_redundancy", "text": "甲的乙的项"}]
                    },
                    "hidden_audio_repeat_validator": {"blocking_issues": []},
                },
            )
            self.assertEqual(blockers[0].code, "INTERNAL_SEMANTIC_REQUEST_MISSING_FOR_FATAL_REPEAT")

        with self.subTest("illegal semantic decision"):
            unit = clusters[0].variants[0]
            semantic_review_clusters = [
                RepeatCluster(
                    cluster_id="repeat_002000",
                    variants=[unit],
                    repeat_type="modifier_redundancy",
                    evidence=[
                        CandidateEvidence(
                            evidence_id="e_invalid",
                            evidence_type="modifier_redundancy",
                            unit_ids=[unit.unit_id],
                            word_ids=list(unit.word_ids),
                            text=unit.text,
                            normalized_text=unit.normalized_text,
                            reason="missing binding requires semantic review",
                            confidence=0.72,
                            requires_semantic_decision=True,
                            metadata={"candidate": {"type": "single_variant_modifier_redundancy", "severity": "fatal"}},
                        )
                    ],
                    local_recommendation="semantic_review",
                )
            ]
            plan = SemanticDecisionPlanner(
                deepseek_planner=SemanticDecisionsJsonPlanner(
                    [{"cluster_id": "repeat_002000", "decision": "not_allowed", "requires_human_review": False}]
                )
            ).plan(semantic_review_clusters)
            self.assertTrue(plan.blocked)
            self.assertEqual(plan.blockers[0].code, "SEMANTIC_DECISION_SCHEMA_INVALID")

        with self.subTest("drop redundant modifier binding missing"):
            unit = EditUnit(
                unit_id="u1",
                word_ids=["w1", "w2"],
                text="A的B的HEAD",
                normalized_text="A的B的HEAD",
                source_start_us=0,
                source_end_us=1_000_000,
                subtitle_uids=["s1"],
                source_material_ids=["main"],
                kind="phrase",
                cut_policy="word_boundary",
            )
            cluster = RepeatCluster(
                cluster_id="repeat_bad",
                variants=[unit],
                repeat_type="modifier_redundancy",
                evidence=[
                    CandidateEvidence(
                        evidence_id="e1",
                        evidence_type="modifier_redundancy",
                        unit_ids=["u1"],
                        word_ids=["w1", "w2"],
                        text=unit.text,
                        normalized_text=unit.normalized_text,
                        reason="bad binding",
                        confidence=0.9,
                        requires_semantic_decision=True,
                        metadata={"candidate": {"type": "single_variant_modifier_redundancy"}},
                    )
                ],
                local_recommendation=None,
            )
            row = SemanticDecisionsJsonPlanner(
                [{"cluster_id": "repeat_bad", "decision": "drop_redundant_modifier"}]
            ).decide([cluster])[0]
            self.assertEqual(row["_blocker_code"], "MODIFIER_REDUNDANCY_WORD_BINDING_MISSING")

        with self.subTest("residual micro unmergeable"):
            words = [
                make_word("w1", "A", 0, 200_000, "s1", 1),
                make_word("w2", "B", 2_000_000, 2_200_000, "s2", 2),
            ]
            segments = [
                make_segment("seg1", "A", 0, 200_000, ["w1"]),
                make_segment("seg2", "B", 2_000_000, 2_200_000, ["w2"]),
            ]
            normalized, blockers = RoughCutQualityNormalizer().normalize(segments, make_source_graph(words, source_end_us=2_500_000), DecisionPlan(decisions=[]))
            self.assertEqual([segment.text for segment in normalized], ["A", "B"])
            self.assertEqual(blockers[0].code, "ROUGH_CUT_RESIDUAL_MICRO_SEGMENT_UNMERGEABLE")

    def test_writeback_and_writer_failure_paths_do_not_fake_success(self) -> None:
        with self.subTest("material caption segment mismatch"):
            result = fake_real_draft_result()
            report = ArollEngine(writer=MismatchedWriter()).run(
                ArollRunInput(
                    mode="write",
                    draft_data=result.draft_data,
                    word_timeline=result.word_timeline,
                    subtitles=result.subtitles,
                    source_segments=result.source_segments,
                    source_materials=result.source_materials,
                    text_materials=result.text_materials,
                    text_segments=result.text_segments,
                    postwrite_mode="simulated",
                )
            )
            self.assertEqual(report.status, "blocked")
            self.assertFalse(report.blocker_report.summary["write_allowed"])

        def failing_encrypt(_jy_draftc: Path, _plain: Path, _encrypted_out: Path) -> None:
            raise RuntimeError("encrypt failed")

        with self.subTest("unknown caption-like cleaned"), tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_disposable_draft(root)
            result = fake_real_draft_result(root=root)
            material = {"id": "unknown_text_material", "type": "text", "text": "unknown"}
            segment = {"id": "unknown_text_segment", "type": "text", "material_id": "unknown_text_material"}
            result.draft_data["materials"]["texts"].append(material)
            next(track for track in result.draft_data["tracks"] if track["id"] == "text_track")["segments"].append(segment)
            result.text_segments.append(segment | {"track_id": "text_track", "track_type": "text"})
            summary = _run_write_operator(root, result, writeback_factory=lambda *a, **k: fake_real_writeback(jy_draftc=k.get("jy_draftc")))
            self.assertEqual(summary["status"], "ok")
            self.assertIsNone(summary["fatal_blocker"])
            self.assertTrue(summary["commit_performed"])
            self.assertTrue(summary["writeback_success"])

        for name, writeback_factory, expected in (
            (
                "encrypt failure",
                lambda *a, **k: fake_real_writeback(jy_draftc=k.get("jy_draftc"), encrypt_func=failing_encrypt),
                "V21_WRITEBACK_ENCRYPT_FAILED",
            ),
            (
                "target write failure",
                lambda *a, **k: fake_real_writeback(jy_draftc=k.get("jy_draftc")),
                "V21_WRITEBACK_TARGET_WRITE_FAILED",
            ),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                create_disposable_draft(root)
                result = fake_real_draft_result(root=root)
                if name == "target write failure":
                    with patch("aroll_v21.writeback.real_draft_writeback.shutil.copyfile", side_effect=OSError("target write failed")):
                        summary = _run_write_operator(root, result, writeback_factory=writeback_factory)
                else:
                    summary = _run_write_operator(root, result, writeback_factory=writeback_factory)
                self.assertEqual(summary["fatal_blocker"], expected)
                self.assertFalse(summary["commit_performed"])
                self.assertFalse(summary["writeback_success"])


if __name__ == "__main__":
    unittest.main()
