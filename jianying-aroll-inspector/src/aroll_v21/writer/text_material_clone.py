from __future__ import annotations

import json
from copy import deepcopy
from typing import Any


def _rewrite_range(value: Any, text_len: int) -> Any:
    if isinstance(value, dict):
        out = dict(value)
        if "start" in out:
            out["start"] = 0
        if "location" in out:
            out["location"] = 0
        if "end" in out:
            out["end"] = text_len
        if "length" in out:
            out["length"] = text_len
        if "len" in out:
            out["len"] = text_len
        return out
    if isinstance(value, list) and len(value) == 2 and all(isinstance(item, int) for item in value):
        return [0, text_len]
    return value


def _rewrite_content_payload(value: Any, text: str) -> Any:
    as_string = isinstance(value, str)
    if as_string:
        payload = json.loads(value)
    else:
        payload = deepcopy(value)
    if not isinstance(payload, dict):
        return value
    payload["text"] = text
    styles = payload.get("styles")
    if isinstance(styles, list):
        for style in styles:
            if isinstance(style, dict) and "range" in style:
                style["range"] = _rewrite_range(style.get("range"), len(text))
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if as_string else payload


def set_caption_text_payload(material: dict[str, Any], text: str) -> None:
    for key in ("text", "recognize_text"):
        if isinstance(material.get(key), str):
            material[key] = text
    for key in ("content", "base_content"):
        if key in material:
            material[key] = _rewrite_content_payload(material.get(key), text)


def clone_caption_text_material(material: dict[str, Any], new_id: str, text: str) -> dict[str, Any]:
    cloned = deepcopy(material)
    cloned["id"] = new_id
    set_caption_text_payload(cloned, text)
    return cloned
