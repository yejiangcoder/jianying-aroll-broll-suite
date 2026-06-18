from __future__ import annotations

import unittest

from aroll_final_repeat_gate import build_final_repeat_gate_report
from aroll_hidden_audio_repeat_gate import build_hidden_audio_repeat_report
from aroll_v21.compiler import FinalTimelineCompiler
from aroll_v21.ingest import DraftIngest
from aroll_v21.ir import DecisionPlan
from aroll_v21.render import SubtitleRenderer


def _graph_for_texts(texts: list[str]):
    word_rows = []
    subtitles = []
    cursor = 0
    for index, text in enumerate(texts, start=1):
        duration = max(320_000, len(text) * 50_000)
        word_id = f"w_{index:03d}"
        subtitle_uid = f"s_{index:03d}"
        word_rows.append(
            {
                "word_id": word_id,
                "word_text": text,
                "source_start_us": cursor,
                "source_end_us": cursor + duration,
                "source_material_id": "main",
                "source_segment_id": "clip",
                "subtitle_uid": subtitle_uid,
                "subtitle_index": index,
            }
        )
        subtitles.append({"subtitle_uid": subtitle_uid, "subtitle_index": index, "text": text, "word_ids": [word_id]})
        cursor += duration + 40_000
    return DraftIngest().build_source_graph(
        word_timeline=word_rows,
        subtitles=subtitles,
        source_segments=[{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": cursor + 1_000_000}],
    )


def _caption_rows(captions):
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


def _word_rows(graph, final_timeline):
    final_word_ids = {word_id for segment in final_timeline for word_id in segment.word_ids}
    return [
        {
            "word_id": word.word_id,
            "word_text": word.text,
            "start_us": word.source_start_us,
            "end_us": word.source_end_us,
            "subtitle_uid": word.subtitle_uid,
            "subtitle_index": word.subtitle_index,
        }
        for word in graph.words
        if word.word_id in final_word_ids
    ]


class ArollV21FinalPreUatPrefixDropTests(unittest.TestCase):
    def test_final_sweep_comment_sample_keeps_only_completed_right_segment(self) -> None:
        graph = _graph_for_texts(["评论区也全是哇", "评论区也全是哇塞"])
        plan = DecisionPlan(decisions=[])

        final_timeline, blockers = FinalTimelineCompiler().compile(graph, plan)
        captions = SubtitleRenderer().render(final_timeline, graph)

        self.assertEqual(blockers, [])
        self.assertEqual([segment.text for segment in final_timeline], ["评论区也全是哇塞"])
        self.assertEqual([caption.text for caption in captions], ["评论区也全是哇塞"])
        self.assertEqual(final_timeline[0].target_start_us, 0)
        repeat_report = build_final_repeat_gate_report({"issues": []}, _caption_rows(captions))
        hidden_report = build_hidden_audio_repeat_report({"issues": []}, _caption_rows(captions), _word_rows(graph, final_timeline))
        self.assertTrue(repeat_report["final_repeat_gate_passed"])
        self.assertTrue(hidden_report["hidden_audio_repeat_gate_passed"])

    def test_final_sweep_table_sample_keeps_only_completed_right_segment(self) -> None:
        graph = _graph_for_texts(["重新上", "重新上桌"])
        plan = DecisionPlan(decisions=[])

        final_timeline, blockers = FinalTimelineCompiler().compile(graph, plan)
        captions = SubtitleRenderer().render(final_timeline, graph)

        self.assertEqual(blockers, [])
        self.assertEqual([segment.text for segment in final_timeline], ["重新上桌"])
        self.assertEqual([caption.text for caption in captions], ["重新上桌"])
        self.assertEqual(len([row for row in plan.decision_trace if row.get("stage") == "final_timeline_pre_emit"]), 1)


if __name__ == "__main__":
    unittest.main()
