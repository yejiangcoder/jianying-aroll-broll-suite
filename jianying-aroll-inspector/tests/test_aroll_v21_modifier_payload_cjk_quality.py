from __future__ import annotations

import json
import unittest

from aroll_v21 import ArollEngine
from tests.test_aroll_v21_semantic_unconfigured_dryrun_policy import semantic_run_input


class ArollV21ModifierPayloadCjkQualityTests(unittest.TestCase):
    def test_noun_scope_emphasis_adverb_no_longer_creates_bad_modifier_payload(self) -> None:
        report = ArollEngine().run(semantic_run_input(text="自信的人真的能拿到结果"))

        payload_text = json.dumps(report.decision_plan.semantic_request_payloads, ensure_ascii=False)
        self.assertEqual(report.decision_plan.semantic_request_payloads, [])
        self.assertNotIn('"right_modifier": "人真"', payload_text)
        self.assertNotIn('"head_text"', payload_text)

    def test_same_head_modifier_payload_keeps_raw_phrase_and_does_not_trust_segmentation(self) -> None:
        report = ArollEngine().run(semantic_run_input(text="随意的肆意的踩踏"))

        payload_text = json.dumps(report.decision_plan.semantic_request_payloads, ensure_ascii=False)
        self.assertTrue(report.decision_plan.semantic_request_payloads)
        self.assertIn('"raw_phrase"', payload_text)
        self.assertIn('"segmentation_confidence": "untrusted"', payload_text)
        self.assertTrue(report.decision_plan.requires_human_review)


if __name__ == "__main__":
    unittest.main()
