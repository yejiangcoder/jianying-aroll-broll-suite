from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import jy_bridge
from aroll_inspect import DEFAULT_RUNTIME as INSPECT_DEFAULT_RUNTIME
from aroll_inspect import TOOL_ROOT as INSPECT_TOOL_ROOT
from aroll_inspect import build_report


class EngineeringSafetyGateTest(unittest.TestCase):
    def _base_fake_draft(
        self,
        *,
        speed: float = 1.0,
        speed_ref: bool = False,
        attached_refs: list[str] | None = None,
        extra_materials: dict[str, list[dict[str, object]]] | None = None,
    ) -> dict[str, object]:
        source_duration = int(round(1_000_000 * speed))
        refs: list[str] = []
        materials: dict[str, list[dict[str, object]]] = {
            "videos": [{"id": "video_1", "path": "raw.mp4", "type": "video", "duration": source_duration}],
            "texts": [{"id": "text_1", "content": {"text": "hello"}}],
        }
        if speed_ref:
            refs.append("speed_1")
            materials["speeds"] = [{"id": "speed_1", "speed": speed}]
        refs.extend(attached_refs or [])
        for key, rows in (extra_materials or {}).items():
            materials.setdefault(key, []).extend(rows)
        return {
            "id": "timeline_1",
            "duration": 1_000_000,
            "materials": materials,
            "tracks": [
                {
                    "id": "main_video",
                    "type": "video",
                    "segments": [
                        {
                            "id": "video_seg_1",
                            "material_id": "video_1",
                            "extra_material_refs": refs,
                            "source_timerange": {"start": 0, "duration": source_duration},
                            "target_timerange": {"start": 0, "duration": 1_000_000},
                        }
                    ],
                },
                {
                    "id": "text_track",
                    "type": "text",
                    "segments": [
                        {
                            "id": "text_seg_1",
                            "material_id": "text_1",
                            "target_timerange": {"start": 0, "duration": 1_000_000},
                        }
                    ],
                },
            ],
        }

    def _run_fake_inspect(
        self,
        fake_data: dict[str, object],
        *,
        speed_mapping_report: dict[str, object] | None = None,
    ) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            draft_dir = root / "draft"
            (draft_dir / "Timelines" / "timeline_1").mkdir(parents=True)
            args = SimpleNamespace(
                draft_dir=draft_dir,
                timeline_name="",
                main_video_track_index=-1,
                main_material_path="",
                jy_draftc=Path("draftc"),
                runtime=root / "runs",
                max_allowed_speed=1.25,
            )

            def fake_decrypt(_jy_draftc: Path, _encrypted_path: Path, plain_path: Path) -> None:
                plain_path.write_text(json.dumps(fake_data, ensure_ascii=False), "utf-8")

            timeline_checks = {
                "timeline_content_id_matches_folder": True,
                "project_timeline_files_match_folder_ids": True,
                "timeline_layout_has_no_duplicate_ids": True,
            }
            patches = [
                patch("aroll_inspect.resolve_timeline_id", return_value=("timeline_1", "")),
                patch("aroll_inspect.decrypt", side_effect=fake_decrypt),
                patch("aroll_inspect.run_checks", return_value=(timeline_checks, [])),
            ]
            if speed_mapping_report is not None:
                patches.append(patch("aroll_inspect.run_speed_mapping_checker", return_value=speed_mapping_report))
            with patches[0], patches[1], patches[2]:
                if len(patches) == 4:
                    with patches[3]:
                        _run_dir, report_path, _subtitle_path = build_report(args)
                else:
                    _run_dir, report_path, _subtitle_path = build_report(args)
            return json.loads(report_path.read_text("utf-8"))

    def test_jy_bridge_import_has_lightweight_fallbacks_without_aligner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_root = os.environ.get("JY_ALIGNER_ROOT")
            os.environ["JY_ALIGNER_ROOT"] = str(Path(temp_dir) / "missing_aligner")
            try:
                with tempfile.TemporaryDirectory() as json_dir:
                    path = Path(json_dir) / "sample.json"
                    jy_bridge.write_json(path, {"text": "A B"})
                    self.assertEqual(jy_bridge.read_json(path), {"text": "A B"})
                    self.assertEqual(jy_bridge.norm_text("A B"), "ab")

                jy_bridge._BRIDGE_MODULE = None
                with self.assertRaisesRegex(RuntimeError, "JY_ALIGNER_SRC_NOT_FOUND"):
                    jy_bridge.decrypt(Path("in.json"), Path("out.json"))
            finally:
                if old_root is None:
                    os.environ.pop("JY_ALIGNER_ROOT", None)
                else:
                    os.environ["JY_ALIGNER_ROOT"] = old_root
                jy_bridge._BRIDGE_MODULE = None

    def test_inspect_unknown_attached_ref_is_fatal(self) -> None:
        report = self._run_fake_inspect(self._base_fake_draft(attached_refs=["unknown_attached_ref"]))
        self.assertIn("MAIN_VIDEO_HAS_UNRECOGNIZED_ATTACHED_EFFECT_REFS", report["fatal_reasons"])
        self.assertFalse(report["can_aroll_rewrite"])

    def test_speed_mapping_pass_allows_constant_speed_rewrite(self) -> None:
        report = self._run_fake_inspect(
            self._base_fake_draft(speed=1.2, speed_ref=True),
            speed_mapping_report={"passed": True, "fatal_reasons": [], "tested_segment_count": 1},
        )
        self.assertTrue(report["can_aroll_rewrite"])
        self.assertNotIn("MAIN_VIDEO_SPEED_REQUIRES_MAPPING", report["fatal_reasons"])
        self.assertTrue(report["main_video_speed_mapping_required"])
        self.assertTrue(report["main_video_speed_mapping_validated"])
        self.assertIn("MAIN_VIDEO_SPEED_REQUIRES_MAPPING", report["warnings"])

    def test_speed_mapping_failure_blocks_rewrite(self) -> None:
        report = self._run_fake_inspect(
            self._base_fake_draft(speed=1.2, speed_ref=True),
            speed_mapping_report={
                "passed": False,
                "fatal_reasons": ["SPEED_MAPPING_ROUNDTRIP_SELF_TEST_FAILED"],
            },
        )
        self.assertFalse(report["can_aroll_rewrite"])
        self.assertIn("MAIN_VIDEO_SPEED_MAPPING_SELF_TEST_FAILED", report["fatal_reasons"])

    def test_cloneable_attached_refs_do_not_block_rewrite(self) -> None:
        report = self._run_fake_inspect(
            self._base_fake_draft(
                attached_refs=["effect_1"],
                extra_materials={"effects": [{"id": "effect_1", "type": "beauty"}]},
            )
        )
        self.assertTrue(report["can_aroll_rewrite"])
        self.assertNotIn("MAIN_VIDEO_HAS_UNRECOGNIZED_ATTACHED_EFFECT_REFS", report["fatal_reasons"])
        self.assertTrue(report["attached_effects_report"]["attached_refs_cloneable"])

    def test_uncloneable_attached_refs_block_rewrite(self) -> None:
        report = self._run_fake_inspect(
            self._base_fake_draft(
                attached_refs=["unknown_category_1"],
                extra_materials={"unknown_material_category": [{"id": "unknown_category_1"}]},
            )
        )
        self.assertFalse(report["can_aroll_rewrite"])
        self.assertIn("MAIN_VIDEO_HAS_UNRECOGNIZED_ATTACHED_EFFECT_REFS", report["fatal_reasons"])
        self.assertFalse(report["attached_effects_report"]["attached_refs_cloneable"])

    def test_inspect_default_runtime_is_not_project_local_runtime(self) -> None:
        project_runtime = INSPECT_TOOL_ROOT / "runtime"
        self.assertNotEqual(INSPECT_DEFAULT_RUNTIME, project_runtime)
        self.assertFalse(str(INSPECT_DEFAULT_RUNTIME).startswith(str(project_runtime)))

    def test_v21_tree_does_not_depend_on_removed_legacy_runtime_tools(self) -> None:
        forbidden = {
            "aroll_make_release",
            "aroll_safe_gap_cutter",
            "aroll_decision_plan_builder",
            "aroll_phase4e_full_aroll",
            "aroll_downstream_repair_pipeline",
            "aroll_repair_applier",
        }
        v21_files = list((SRC / "aroll_v21").rglob("*.py"))
        hits: list[tuple[str, str]] = []
        for path in v21_files:
            text = path.read_text("utf-8")
            for token in forbidden:
                if token in text:
                    hits.append((str(path.relative_to(ROOT)), token))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
