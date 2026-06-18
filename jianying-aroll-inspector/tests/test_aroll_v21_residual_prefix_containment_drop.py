from __future__ import annotations

import unittest
from pathlib import Path

from aroll_final_repeat_gate import build_final_repeat_gate_report
from aroll_hidden_audio_repeat_gate import build_hidden_audio_repeat_report
from aroll_v21.compiler import RoughCutQualityNormalizer
from aroll_v21.compiler.rough_cut_quality_normalizer import SOURCE_GAP_MERGE_LIMIT_US
from aroll_v21.ir import CaptionRenderUnit, DecisionPlan
from aroll_v21.render import SubtitleRenderer
from aroll_v21.validate.rough_cut_quality import build_rough_cut_quality_metrics
from tests.test_aroll_v21_rough_cut_quality_normalizer import make_segment, make_source_graph, make_word


ROOT = Path(__file__).resolve().parents[1]


def _caption_rows(captions: list[CaptionRenderUnit]) -> list[dict]:
    return [
        {
            "fragment_id": caption.caption_id,
            "fragment_text": caption.text,
            "text": caption.text,
            "word_ids": caption.word_ids,
            "target_start_us": caption.target_start_us,
            "target_duration_us": caption.target_end_us - caption.target_start_us,
        }
        for caption in captions
    ]


class ArollV21ResidualPrefixContainmentDropTests(unittest.TestCase):
    def test_residual_prefix_of_next_segment_is_dropped_before_unmergeable_blocker(self) -> None:
        words = [
            make_word("w1", "A", 0, 280_000, "s1", 1),
            make_word("w2", "Axxx", 2_040_000, 2_740_000, "s2", 2),
        ]
        graph = make_source_graph(words, source_end_us=3_000_000)
        segments = [
            make_segment("seg1", "A", 0, 280_000, ["w1"]),
            make_segment("seg2", "Axxx", 2_040_000, 2_740_000, ["w2"]),
        ]
        plan = DecisionPlan(decisions=[])

        final_timeline, blockers = RoughCutQualityNormalizer().normalize(segments, graph, plan)
        captions = SubtitleRenderer().render(final_timeline, graph)
        material_write_plan = {"materials": [{} for _ in captions], "segments": [{} for _ in captions]}
        metrics = build_rough_cut_quality_metrics(
            final_timeline=final_timeline,
            captions=captions,
            material_write_plan=material_write_plan,
        )
        caption_rows = _caption_rows(captions)

        self.assertEqual(blockers, [])
        self.assertEqual([segment.text for segment in final_timeline], ["Axxx"])
        self.assertEqual([caption.text for caption in captions], ["Axxx"])
        self.assertEqual(final_timeline[0].word_ids, ["w2"])
        self.assertEqual(final_timeline[0].target_start_us, 0)
        self.assertEqual(metrics["segments_lt_300ms"], 0)
        self.assertEqual(metrics["one_char_captions"], 0)
        self.assertEqual(metrics["final_timeline_count"], metrics["caption_count"])
        self.assertEqual(metrics["caption_count"], metrics["material_count"])
        self.assertEqual(metrics["material_count"], metrics["segment_count"])
        self.assertTrue(build_final_repeat_gate_report({"issues": []}, caption_rows)["final_repeat_gate_passed"])
        self.assertTrue(build_hidden_audio_repeat_report({"issues": []}, caption_rows, [])["hidden_audio_repeat_gate_passed"])

        trace = [row for row in plan.decision_trace if row.get("route") == "residual_prefix_containment_drop"]
        self.assertEqual(len(trace), 1)
        self.assertEqual(trace[0]["dropped_segment_id"], "seg1")
        self.assertEqual(trace[0]["dropped_text"], "A")
        self.assertEqual(trace[0]["next_segment_id"], "seg2")
        self.assertEqual(trace[0]["next_text"], "Axxx")
        self.assertEqual(trace[0]["reason"], "residual_text_is_prefix_of_next_text")

    def test_rough_cut_hard_gate_and_gap_limit_are_unchanged(self) -> None:
        metrics = build_rough_cut_quality_metrics(
            final_timeline=[make_segment("seg1", "A", 0, 280_000, ["w1"])],
            captions=[
                CaptionRenderUnit(
                    caption_id="cap_000001",
                    timeline_segment_ids=["seg1"],
                    word_ids=["w1"],
                    text="A",
                    target_start_us=0,
                    target_end_us=280_000,
                    source_subtitle_uids=["s1"],
                    style_template_id="tmpl",
                )
            ],
            material_write_plan={"materials": [{}], "segments": [{}]},
        )

        self.assertEqual(SOURCE_GAP_MERGE_LIMIT_US, 1_500_000)
        self.assertEqual(metrics["segments_lt_300ms"], 1)
        self.assertEqual(metrics["one_char_captions"], 1)
        self.assertFalse(metrics["rough_cut_quality_gate_passed"])

    def test_normalizer_file_does_not_import_legacy_repair_paths(self) -> None:
        text = (ROOT / "src" / "aroll_v21" / "compiler" / "rough_cut_quality_normalizer.py").read_text("utf-8")
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
