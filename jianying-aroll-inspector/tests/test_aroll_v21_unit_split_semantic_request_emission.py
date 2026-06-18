from __future__ import annotations

import json
import unittest

from aroll_v21 import ArollEngine
from tests.test_aroll_v21_intra_edit_unit_repeat_split import _material_rows


def unit_split_human_review_input():
    from aroll_v21 import ArollRunInput

    text_materials, text_segments = _material_rows()
    return ArollRunInput(
        source_segments=[{"id": "clip_1", "material_id": "main_video", "source_start_us": 0, "source_end_us": 1_000_000}],
        word_timeline=[
            {"word_id": "w1", "word_text": "然后然后", "start_us": 0, "end_us": 500_000, "subtitle_uid": "s1", "subtitle_index": 1},
            {"word_id": "w2", "word_text": "他开始解释", "start_us": 500_000, "end_us": 1_000_000, "subtitle_uid": "s1", "subtitle_index": 1},
        ],
        subtitles=[{"subtitle_uid": "s1", "subtitle_index": 1, "text": "然后然后他开始解释", "word_ids": ["w1", "w2"]}],
        text_materials=text_materials,
        text_segments=text_segments,
    )


class ArollV21UnitSplitSemanticRequestEmissionTests(unittest.TestCase):
    def test_unit_split_requires_human_review_emits_semantic_request_payload(self) -> None:
        report = ArollEngine().run(unit_split_human_review_input())

        codes = [blocker.code for blocker in report.blocker_report.blockers]
        self.assertIn("UNIT_SPLIT_REQUIRES_HUMAN_REVIEW", codes)
        self.assertNotIn("INTERNAL_SEMANTIC_REQUEST_MISSING_FOR_UNIT_SPLIT", codes)
        payloads = report.decision_plan.semantic_request_payloads
        self.assertTrue(payloads)
        payload = payloads[0]
        blocker_cluster_ids = {
            blocker.context["cluster_id"]
            for blocker in report.blocker_report.blockers
            if blocker.code == "UNIT_SPLIT_REQUIRES_HUMAN_REVIEW"
        }
        self.assertIn(payload["cluster_id"], blocker_cluster_ids)
        self.assertEqual(payload["type"], "unit_split_requires_human_review")
        self.assertEqual(payload["repeat_type"], "unit_split")
        self.assertEqual(payload["reason"], "UNIT_SPLIT_REQUIRES_HUMAN_REVIEW")
        self.assertIn("apply_suggested_split", payload["allowed_decisions"])
        self.assertEqual(payload["suggested_for_rough_cut"], "apply_suggested_split")
        self.assertIn("split_summary", payload)
        for required in ("source_start_us", "source_end_us", "target_start_us", "target_end_us", "word_ids"):
            self.assertIn(required, payload)
        payload_text = json.dumps(payload, ensure_ascii=False)
        for forbidden in (
            "edl",
            "final_edl",
            "draft_content",
            "material_id",
        ):
            self.assertNotIn(forbidden, payload_text)


if __name__ == "__main__":
    unittest.main()
