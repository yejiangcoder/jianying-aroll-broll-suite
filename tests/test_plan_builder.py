from pathlib import Path

from jianying_ai_broll_aligner.plan_builder import build_plans


def test_build_plans(tmp_path: Path) -> None:
    broll = tmp_path / "broll.md"
    broll.write_text(
        """
| index | type | target_quote | visual_direction |
| --- | --- | --- | --- |
| 01 | AI image | "He finally closes the laptop and walks outside." | Night office |
""",
        encoding="utf-8",
    )
    subtitles = tmp_path / "subtitles.srt"
    subtitles.write_text(
        """1
00:00:00,000 --> 00:00:02,100
He finally closes the laptop and walks outside.
""",
        encoding="utf-8",
    )
    image_dir = tmp_path / "assets"
    image_dir.mkdir()
    (image_dir / "sample_AI_01_office.png").write_bytes(b"not-a-real-png")

    semantic, exec_plan, subtitle_rows = build_plans(broll, subtitles, image_dir)

    assert len(semantic) == 1
    assert len(exec_plan) == 1
    assert len(subtitle_rows) == 1
    assert exec_plan[0].start_sec == 0

