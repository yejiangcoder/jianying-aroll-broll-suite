from __future__ import annotations

import unittest

from aroll_final_repeat_gate import build_final_repeat_gate_report
from aroll_hidden_audio_repeat_gate import build_hidden_audio_repeat_report
from aroll_v21.compiler import FinalTimelineCompiler
from aroll_v21.ingest import DraftIngest
from aroll_v21.ir import DecisionPlan
from tests.test_aroll_v21_rough_cut_quality_normalizer import make_segment
from aroll_v21.render import SubtitleRenderer


def _input_for_duplicate_segments():
    words = []
    subtitles = []
    source_segments = [{"id": "clip", "material_id": "main", "source_start_us": 0, "source_end_us": 2_000_000}]
    cursor = 0
    for subtitle_index, text in enumerate(["兄弟健个身", "兄弟健个身"], start=1):
        word_ids = []
        start = cursor
        for char in text:
            word_id = f"w_{len(words) + 1:06d}"
            word_ids.append(word_id)
            words.append(
                {
                    "word_id": word_id,
                    "word_text": char,
                    "source_start_us": cursor,
                    "source_end_us": cursor + 100_000,
                    "source_material_id": "main",
                    "source_segment_id": "clip",
                    "subtitle_uid": f"s_{subtitle_index:03d}",
                    "subtitle_index": subtitle_index,
                }
            )
            cursor += 100_000
        subtitles.append(
            {
                "subtitle_uid": f"s_{subtitle_index:03d}",
                "subtitle_index": subtitle_index,
                "text": text,
                "word_ids": word_ids,
                "source_start_us": start,
                "source_end_us": cursor,
            }
        )
        cursor += 100_000
    return words, subtitles, source_segments


class ArollV21AdjacentExactDuplicateCleanupTests(unittest.TestCase):
    def test_post_normalizer_adjacent_exact_duplicate_keeps_one_segment(self) -> None:
        words, subtitles, source_segments = _input_for_duplicate_segments()
        source_graph = DraftIngest().build_source_graph(word_timeline=words, subtitles=subtitles, source_segments=source_segments)
        decision_plan = DecisionPlan(decisions=[])
        compiler = FinalTimelineCompiler()
        segments = [
            make_segment("seg1", "兄弟健个身", 0, 500_000, ["w_000001", "w_000002", "w_000003", "w_000004", "w_000005"]),
            make_segment("seg2", "兄弟健个身", 600_000, 1_100_000, ["w_000006", "w_000007", "w_000008", "w_000009", "w_000010"]),
        ]

        final_timeline, blockers = compiler._post_normalizer_adjacent_exact_duplicate_cleanup(segments, decision_plan)
        captions = SubtitleRenderer().render(final_timeline, source_graph)

        self.assertEqual(blockers, [])
        self.assertEqual([segment.text for segment in final_timeline], ["兄弟健个身"])
        self.assertEqual([caption.text for caption in captions], ["兄弟健个身"])
        self.assertEqual(final_timeline[0].target_start_us, 0)
        self.assertGreater(final_timeline[0].target_end_us, final_timeline[0].target_start_us)
        self.assertTrue(any(row.get("route") == "adjacent_exact_duplicate_cleanup" for row in decision_plan.decision_trace))

        caption_rows = [
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
        final_repeat = build_final_repeat_gate_report({"issues": []}, caption_rows)
        hidden_repeat = build_hidden_audio_repeat_report({"issues": []}, caption_rows, [])
        self.assertTrue(final_repeat["final_repeat_gate_passed"])
        self.assertTrue(hidden_repeat["hidden_audio_repeat_gate_passed"])


if __name__ == "__main__":
    unittest.main()
