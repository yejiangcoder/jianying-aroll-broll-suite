from pathlib import Path

from jianying_ai_broll_aligner.parse_subtitles import parse_srt


def test_parse_srt(tmp_path: Path) -> None:
    path = tmp_path / "subtitles.srt"
    path.write_text(
        """1
00:00:00,000 --> 00:00:01,300
He walks outside.

2
00:00:02,000 --> 00:00:03,200
The page is finished.
""",
        encoding="utf-8",
    )

    rows = parse_srt(path)

    assert len(rows) == 2
    assert rows[0].start_sec == 0
    assert rows[1].start_sec == 2
    assert rows[1].text == "The page is finished."

