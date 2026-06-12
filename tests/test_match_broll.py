from pathlib import Path

from jianying_ai_broll_aligner.match_broll_to_subtitles import match_broll_to_subtitles
from jianying_ai_broll_aligner.models import BrollItem, ImageAsset, SubtitleRow


def test_match_broll_to_subtitles_monotonic() -> None:
    items = [
        BrollItem(image_id="01", target_quote="He closes the laptop."),
        BrollItem(image_id="02", target_quote="The phone stays silent."),
    ]
    assets = {
        "01": ImageAsset("01", Path("sample_AI_01.png")),
        "02": ImageAsset("02", Path("sample_AI_02.png")),
    }
    subtitles = [
        SubtitleRow(1, "He closes the laptop.", 0, 1_000_000),
        SubtitleRow(2, "The phone stays silent.", 2_000_000, 3_000_000),
    ]

    rows = match_broll_to_subtitles(items, assets, subtitles, duration_sec=1.3)

    assert [row.image_id for row in rows] == ["01", "02"]
    assert rows[0].start_sec == 0
    assert rows[1].start_sec == 2
    assert rows[0].duration_sec == 1.3

