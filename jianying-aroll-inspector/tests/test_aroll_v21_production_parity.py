from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21 import ArollEngine, ArollRunInput
from aroll_v21.ir import dataclass_to_dict
from tools.export_aroll_v21_uat_capsule import assert_safe_capsule_source, export_capsule


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: str):
    return json.loads((ROOT / path).read_text("utf-8"))


def material_rows() -> tuple[list[dict], list[dict]]:
    normal = load_json("fixtures/real_materials/normal_caption_template.json")
    giant = load_json("fixtures/real_materials/giant_title_material.json")
    callout = load_json("fixtures/real_materials/callout_text_material.json")
    return [normal["material"], giant["material"], callout["material"]], [normal["segment"], giant["segment"], callout["segment"]]


def run_fixture(name: str):
    payload = load_json(f"fixtures/real_timelines/{name}.json")
    text_materials, text_segments = material_rows()
    return ArollEngine().run(
        ArollRunInput(
            source_segments=payload["source_segments"],
            word_timeline=payload["word_timeline"],
            subtitles=payload["subtitles"],
            text_materials=text_materials,
            text_segments=text_segments,
        )
    )


class ArollV21ProductionParityTests(unittest.TestCase):
    def test_multi_clip_gap_preserves_clip_boundaries_and_rebases_target(self) -> None:
        report = run_fixture("multi_clip_gap")
        self.assertEqual(report.status, "ok", dataclass_to_dict(report.blocker_report))
        self.assertEqual(len(report.final_timeline), 2)
        self.assertEqual(report.final_timeline[0].source_start_us, 100_000)
        self.assertEqual(report.final_timeline[1].source_start_us, 2_700_000)
        self.assertEqual(report.final_timeline[1].target_start_us, report.final_timeline[0].target_end_us)
        self.assertTrue(report.validator_report["safe_cut_validator"]["safe_cut_boundary_gate_passed"])

    def test_multi_char_word_alignment_is_kept_as_whole_word(self) -> None:
        report = run_fixture("multi_char_word_alignment")
        self.assertEqual(report.status, "ok", dataclass_to_dict(report.blocker_report))
        words = [word_id for segment in report.final_timeline for word_id in segment.word_ids]
        self.assertIn("w001", words)
        self.assertTrue(report.validator_report["safe_cut_validator"]["safe_cut_boundary_gate_passed"])

    def test_cjk_prefix_stub_is_resolved_by_unit_decision_not_downstream_repair(self) -> None:
        report = run_fixture("cjk_short_overlap")
        self.assertEqual(report.status, "ok", dataclass_to_dict(report.blocker_report))
        text = "".join(caption.text for caption in report.captions)
        self.assertEqual(text, "最后只能像一个小丑")
        self.assertEqual([segment.word_ids for segment in report.final_timeline], [["w002"]])
        self.assertTrue(report.validator_report["final_repeat_validator"]["final_repeat_gate_passed"])

    def test_hidden_audio_adjacent_repeat_fixture_compiles_to_single_take(self) -> None:
        report = run_fixture("hidden_audio_repeat")
        self.assertEqual(report.status, "ok", dataclass_to_dict(report.blocker_report))
        text = "".join(caption.text for caption in report.captions)
        self.assertEqual(text, "你跪在地上叫大佬")
        self.assertTrue(report.validator_report["hidden_audio_repeat_validator"]["hidden_audio_repeat_gate_passed"])

    def test_v21_capsule_export_copies_only_allowed_json_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            run_dir.mkdir()
            for name in (
                "source_graph.json",
                "edit_units.json",
                "repeat_clusters.json",
                "decision_plan.json",
                "semantic_request_payloads.json",
                "final_timeline.json",
                "final_edl.json",
                "captions.json",
                "canonical_caption_template.json",
                "material_write_plan.json",
                "validator_report.json",
                "postwrite_report.json",
                "blocker_report.json",
                "decision_trace.json",
            ):
                (run_dir / name).write_text("{}", "utf-8")
            manifest = export_capsule(run_dir=run_dir, case_id="case_a", out_root=root / "capsules")
            manifest_payload = json.loads(manifest.read_text("utf-8"))
            self.assertEqual(manifest_payload["case_id"], "case_a")
            self.assertTrue((manifest.parent / "source_graph.json").exists())
            self.assertEqual(manifest_payload["missing_artifacts"], [])
            self.assertIn("final_edl", manifest_payload["artifacts"])
            self.assertIn("canonical_caption_template", manifest_payload["artifacts"])
            forbidden = run_dir / "draft_content.json"
            forbidden.write_text("{}", "utf-8")
            with self.assertRaises(ValueError):
                assert_safe_capsule_source(forbidden)


if __name__ == "__main__":
    unittest.main()
