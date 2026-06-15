from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def no_call_report(reason: str = "local semantic overlap trimmer resolved all candidates") -> dict[str, Any]:
    return {
        "llm_provider": "deepseek",
        "called": False,
        "call_count": 0,
        "issues": [],
        "api_key_leaked": False,
        "reason": reason,
    }
