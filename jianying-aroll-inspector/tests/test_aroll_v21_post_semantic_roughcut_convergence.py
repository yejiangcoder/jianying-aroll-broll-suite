from __future__ import annotations

import unittest
from pathlib import Path

from aroll_final_repeat_gate import build_final_repeat_gate_report
from aroll_hidden_audio_repeat_gate import build_hidden_audio_repeat_report
from aroll_v21.compiler import FinalTimelineCompiler
from aroll_v21.ingest import DraftIngest
from aroll_v21.ir import DecisionPlan, UnitSplitPlan
from aroll_v21.render import SubtitleRenderer
from aroll_v21.validate.rough_cut_quality import build_rough_cut_quality_metrics


ROOT = Path(__file__).resolve().parents[1]


def _caption_gate_rows(captions) -> list[dict]:
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


class ArollV21PostSemanticRoughcutConvergenceTests(unittest.TestCase):
    def test_unit_split_one_char_residual_converges_before_render(self) -> None:
        graph = DraftIngest().build_source_graph(
            word_timeline=[
                {
                    "word_id": "w_drop",
                    "word_text": "删除内容",
                    "source_start_us": 0,
                    "source_end_us": 400_000,
                    "source_material_id": "main",
                    "source_segment_id": "clip",
                    "subtitle_uid": "s1",
                    "subtitle_index": 1,
                },
                {
                    "word_id": "w_keep",
                    "word_text": "这",
                    "source_start_us": 420_000,
                    "source_end_us": 520_000,
                    "source_material_id": "main",
                    "source_segment_id": "clip",
                    "subtitle_uid": "s1",
                    "subtitle_index": 1,
                },
                {
                    "word_id": "w_next",
                    "word_text": "说明问题",
                    "source_start_us": 560_000,
                    "source_end_us": 1_060_000,
                    "source_material_id": "main",
                    "source_segment_id": "clip",
                    "subtitle_uid": "s2",
                    "subtitle_index": 2,
                },
            ],
            subtitles=[
                {"subtitle_uid": "s1", "subtitle_index": 1, "text": "删除内容这", "word_ids": ["w_drop", "w_keep"]},
                {"subtitle_uid": "s2", "subtitle_index": 2, "text": "说明问题", "word_ids": ["w_next"]},
            ],
            source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 1_500_000}],
        )
        plan = DecisionPlan(
            decisions=[],
            split_decisions=[
                UnitSplitPlan(
                    split_id="split_one_char_keep",
                    cluster_id="cluster_one_char_keep",
                    unit_id="s1",
                    drop_word_ids=["w_drop"],
                    keep_word_ids=["w_keep"],
                    reason="leave the useful demonstrative for the following phrase",
                )
            ],
        )

        final_timeline, blockers = FinalTimelineCompiler().compile(graph, plan)
        captions = SubtitleRenderer().render(final_timeline, graph)
        material_write_plan = {"materials": [{} for _ in captions], "segments": [{} for _ in captions]}
        metrics = build_rough_cut_quality_metrics(
            final_timeline=final_timeline,
            captions=captions,
            material_write_plan=material_write_plan,
        )
        caption_rows = _caption_gate_rows(captions)

        self.assertEqual(blockers, [])
        self.assertEqual([segment.text for segment in final_timeline], ["这说明问题"])
        self.assertIn("split_one_char_keep", final_timeline[0].decision_ids)
        self.assertEqual(metrics["segments_lt_300ms"], 0)
        self.assertEqual(metrics["one_char_captions"], 0)
        self.assertEqual(metrics["final_timeline_count"], metrics["caption_count"])
        self.assertEqual(metrics["caption_count"], metrics["material_count"])
        self.assertEqual(metrics["material_count"], metrics["segment_count"])
        self.assertTrue(build_final_repeat_gate_report({"issues": []}, caption_rows)["final_repeat_gate_passed"])
        self.assertTrue(build_hidden_audio_repeat_report({"issues": []}, caption_rows, [])["hidden_audio_repeat_gate_passed"])

    def test_touched_v21_files_do_not_import_legacy_repair_paths(self) -> None:
        text = "\n".join(
            [
                (ROOT / "src" / "aroll_v21" / "compiler" / "final_timeline_compiler.py").read_text("utf-8"),
                (ROOT / "src" / "aroll_v21" / "compiler" / "rough_cut_quality_normalizer.py").read_text("utf-8"),
            ]
        )
        for token in (
            "aroll_phase4e_full_aroll",
            "aroll_downstream_repair_pipeline",
            "aroll_repair_applier",
            "material_text_rows",
            "run_downstream_repair_pipeline",
            "apply_repair_proposals",
        ):
            self.assertNotIn(token, text)


if __name__ == "__main__":
    unittest.main()
