from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aroll_v21.ingest.real_draft_adapter import RealDraftIngestAdapter
from aroll_v21.engine import ArollEngine, ArollRunInput


def _draft_payload() -> dict:
    content = json.dumps(
        {"text": "示例字幕", "styles": [{"range": {"start": 0, "end": 4}, "font_size": 42}]},
        ensure_ascii=False,
    )
    return {
        "id": "tl1",
        "materials": {
            "texts": [
                {
                    "id": "text_1",
                    "type": "caption",
                    "content": content,
                    "base_content": content,
                    "font_size": 42,
                }
            ]
        },
        "tracks": [
            {
                "id": "video_track",
                "type": "video",
                "segments": [
                    {
                        "id": "video_seg_1",
                        "material_id": "main_video",
                        "source_timerange": {"start": 0, "duration": 1000000},
                        "target_timerange": {"start": 0, "duration": 1000000},
                    }
                ],
            },
            {
                "id": "text_track",
                "type": "text",
                "segments": [
                    {
                        "id": "subtitle_seg_1",
                        "material_id": "text_1",
                        "target_timerange": {"start": 0, "duration": 1000000},
                    }
                ],
            },
        ],
        "word_timeline": [
            {
                "word_id": "w1",
                "word_text": "示例字幕",
                "start_us": 0,
                "end_us": 1000000,
                "source_material_id": "main_video",
                "source_segment_id": "video_seg_1",
                "subtitle_uid": "subtitle_seg_1",
                "subtitle_index": 1,
            }
        ],
    }


def _make_real_draft_skeleton(root: Path, *, with_required_files: bool = True) -> Path:
    draft_dir = root / "draft"
    timeline_dir = draft_dir / "Timelines" / "tl1"
    timeline_dir.mkdir(parents=True)
    (draft_dir / "timeline_layout.json").write_text(json.dumps({"activeTimeline": "tl1"}), "utf-8")
    if with_required_files:
        (timeline_dir / "draft_content.json").write_text("encrypted", "utf-8")
        (timeline_dir / "template-2.tmp").write_text("encrypted", "utf-8")
    return draft_dir


class ArollV21RealDraftIngestAdapterTests(unittest.TestCase):
    def test_successful_read_produces_non_empty_v21_input_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir = _make_real_draft_skeleton(root)
            plain_payload = _draft_payload()

            def fake_decrypt(_jy_draftc: Path, _encrypted: Path, output: Path) -> None:
                output.write_text(json.dumps(plain_payload, ensure_ascii=False), "utf-8")

            result = RealDraftIngestAdapter(decrypt_func=fake_decrypt).load(draft_dir, root / "run")
            self.assertEqual(result.blockers, [])
            self.assertTrue(result.draft_data)
            self.assertEqual(len(result.word_timeline), 1)
            self.assertEqual(len(result.subtitles), 1)
            self.assertEqual(len(result.text_materials), 1)
            self.assertEqual(len(result.text_segments), 1)
            self.assertEqual(len(result.source_segments), 1)

            report = ArollEngine().run(
                ArollRunInput(
                    draft_data=result.draft_data,
                    word_timeline=result.word_timeline,
                    subtitles=result.subtitles,
                    source_segments=result.source_segments,
                    text_materials=result.text_materials,
                    text_segments=result.text_segments,
                    ingest_blockers=result.blockers,
                    ingest_metadata=result.metadata,
                    postwrite_mode="simulated",
                )
            )
            self.assertEqual(report.status, "ok")
            self.assertTrue(report.source_graph)
            self.assertTrue(report.material_write_plan["canonical_caption_template_id"])

    def test_decrypt_backend_failure_is_explicit_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir = _make_real_draft_skeleton(root)

            def failing_decrypt(_jy_draftc: Path, _encrypted: Path, _output: Path) -> None:
                raise RuntimeError("backend missing")

            result = RealDraftIngestAdapter(decrypt_func=failing_decrypt).load(draft_dir, root / "run")
            self.assertEqual([blocker.code for blocker in result.blockers], ["REAL_DRAFT_DECRYPT_FAILED"])
            self.assertFalse((root / "run" / ".v21_real_ingest_tmp" / "draft_content.dec.json").exists())

    def test_missing_required_files_are_explicit_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir = _make_real_draft_skeleton(root, with_required_files=False)
            result = RealDraftIngestAdapter(decrypt_func=lambda *_args: None).load(draft_dir, root / "run")
            self.assertEqual([blocker.code for blocker in result.blockers], ["REAL_DRAFT_REQUIRED_FILE_MISSING"])

    def test_missing_word_timeline_uses_subtitle_phrase_fallback_without_fabricating_word_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            draft_dir = _make_real_draft_skeleton(root)
            payload = _draft_payload()
            payload.pop("word_timeline")

            def fake_decrypt(_jy_draftc: Path, _encrypted: Path, output: Path) -> None:
                output.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")

            result = RealDraftIngestAdapter(decrypt_func=fake_decrypt).load(draft_dir, root / "run")
            self.assertEqual([blocker.code for blocker in result.blockers], [])
            self.assertEqual(len(result.word_timeline), 1)
            self.assertEqual(result.word_timeline[0]["speech_timeline_granularity"], "subtitle_phrase")
            self.assertFalse(result.word_timeline[0]["can_cut_inside_caption"])
            self.assertEqual(result.metadata["speech_timeline_granularity"], "subtitle_phrase")


if __name__ == "__main__":
    unittest.main()
