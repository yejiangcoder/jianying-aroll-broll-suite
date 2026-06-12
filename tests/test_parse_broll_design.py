from pathlib import Path

from jianying_ai_broll_aligner.parse_broll_design import parse_broll_design


def test_parse_markdown_table(tmp_path: Path) -> None:
    path = tmp_path / "broll.md"
    path.write_text(
        """
| index | type | target_quote | visual_direction |
| --- | --- | --- | --- |
| 01 | AI image | "He walks outside." | Night street |
| 02 | real video | "Ignore this." | Archive clip |
| 03 | AI image | "The page is finished." | Desk close-up |
""",
        encoding="utf-8",
    )

    rows = parse_broll_design(path)

    assert [row.image_id for row in rows] == ["01", "03"]
    assert rows[0].target_quote == "He walks outside."
    assert rows[1].visual_direction == "Desk close-up"


def test_parse_block_format(tmp_path: Path) -> None:
    path = tmp_path / "broll.md"
    path.write_text(
        """
【04】
type: AI image
target_quote: "The first small win changes the week."
visual_direction: Person finishing a task
""",
        encoding="utf-8",
    )

    rows = parse_broll_design(path)

    assert len(rows) == 1
    assert rows[0].image_id == "04"
    assert "small win" in rows[0].target_quote

