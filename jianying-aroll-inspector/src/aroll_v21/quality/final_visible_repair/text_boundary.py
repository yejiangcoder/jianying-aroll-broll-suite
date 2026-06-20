from __future__ import annotations

from aroll_text_normalize import normalize_text


DE_SHI_BOUNDARY_NORMALIZE_AFTER = ("对", "在", "把", "给", "向", "从", "跟", "为", "为了", "因为", "被", "让", "将")


def join_visible_caption_sequence_text(texts: list[str]) -> str:
    merged = ""
    for text in texts:
        merged = join_visible_boundary_text(merged, text)
    return merged


def join_visible_boundary_text(left_text: str, right_text: str) -> str:
    return f"{left_text}{right_boundary_text_for_join(left_text, right_text)}"


def right_boundary_text_for_join(left_text: str, right_text: str) -> str:
    normalized_left = normalize_text(left_text)
    normalized_right = normalize_text(right_text)
    if (
        normalized_left
        and not normalized_left.endswith("的")
        and normalized_right.startswith("的是")
        and de_shi_boundary_should_drop_de(normalized_right)
    ):
        return drop_leading_de_from_de_shi_text(right_text)
    return right_text


def right_boundary_text_options_after_non_de_left(right_text: str) -> list[str]:
    options = [right_text]
    normalized_right = normalize_text(right_text)
    if normalized_right.startswith("的是") and de_shi_boundary_should_drop_de(normalized_right):
        stripped = drop_leading_de_from_de_shi_text(right_text)
        if stripped and normalize_text(stripped) != normalize_text(right_text):
            options.append(stripped)
    return options


def de_shi_boundary_should_drop_de(normalized_right: str) -> bool:
    if not normalized_right.startswith("的是"):
        return False
    after_shi = normalized_right[2:]
    return any(after_shi.startswith(prefix) for prefix in DE_SHI_BOUNDARY_NORMALIZE_AFTER)


def drop_leading_de_from_de_shi_text(text: str) -> str:
    if text.startswith("的是"):
        return text[1:]
    normalized = normalize_text(text)
    if normalized.startswith("的是"):
        return normalized[1:]
    return text


def text_before_suffix(text: str, suffix: str) -> str | None:
    if text.endswith(suffix):
        return text[: len(text) - len(suffix)]
    normalized_text = normalize_text(text)
    normalized_suffix = normalize_text(suffix)
    if normalized_suffix and normalized_text.endswith(normalized_suffix):
        return normalized_text[: len(normalized_text) - len(normalized_suffix)]
    no_text: str | None = None
    return no_text


def normalized_prefix_before_suffix(text: str, suffix: str) -> str:
    normalized_text = normalize_text(text)
    normalized_suffix = normalize_text(suffix)
    if normalized_suffix and normalized_text.endswith(normalized_suffix):
        return normalized_text[: len(normalized_text) - len(normalized_suffix)]
    return ""
