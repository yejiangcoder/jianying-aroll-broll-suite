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

    rows = match_broll_to_subtitles(items, assets, subtitles, duration_sec=1.3, monotonic=True)

    assert [row.image_id for row in rows] == ["01", "02"]
    assert rows[0].start_sec == 0
    assert rows[1].start_sec == 2
    assert rows[0].duration_sec == 1.3


def test_match_broll_to_subtitles_does_not_reuse_same_subtitle() -> None:
    items = [
        BrollItem(image_id="01", target_quote="waste"),
        BrollItem(image_id="02", target_quote="waste"),
    ]
    assets = {
        "01": ImageAsset("01", Path("sample_AI_01.png")),
        "02": ImageAsset("02", Path("sample_AI_02.png")),
    }
    subtitles = [
        SubtitleRow(1, "When you feel like waste, keep watching.", 0, 1_000_000),
        SubtitleRow(2, "Stop calling yourself waste.", 2_000_000, 3_000_000),
    ]

    rows = match_broll_to_subtitles(items, assets, subtitles, duration_sec=1.3, monotonic=True)

    assert [row.subtitle_index for row in rows] == [1, 2]


def test_match_broll_to_subtitles_can_match_multi_subtitle_window_start() -> None:
    items = [
        BrollItem(image_id="01", target_quote="He closes the laptop and walks outside."),
    ]
    assets = {"01": ImageAsset("01", Path("sample_AI_01.png"))}
    subtitles = [
        SubtitleRow(1, "He closes the laptop", 0, 1_000_000),
        SubtitleRow(2, "and walks outside.", 1_000_000, 2_000_000),
    ]

    rows = match_broll_to_subtitles(items, assets, subtitles, duration_sec=1.3)

    assert rows[0].subtitle_index == 1
    assert rows[0].start_sec == 0
    assert rows[0].match_method.startswith("subtitle_text_window_global:")


def test_global_matching_allows_non_chronological_design_order() -> None:
    items = [
        BrollItem(image_id="02", target_quote="The later turn."),
        BrollItem(image_id="34", target_quote="The opening claim."),
    ]
    assets = {
        "02": ImageAsset("02", Path("sample_AI_02.png")),
        "34": ImageAsset("34", Path("sample_AI_34.png")),
    }
    subtitles = [
        SubtitleRow(1, "The opening claim.", 0, 1_000_000),
        SubtitleRow(2, "The later turn.", 20_000_000, 21_000_000),
    ]

    rows = match_broll_to_subtitles(items, assets, subtitles, duration_sec=1.3)

    assert [row.subtitle_index for row in rows] == [2, 1]
