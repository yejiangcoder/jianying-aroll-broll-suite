from __future__ import annotations

from aroll_v21.ir.models import Blocker


def combine_compiler_blockers(*groups: list[Blocker]) -> list[Blocker]:
    combined: list[Blocker] = []
    for group in groups:
        combined.extend(group)
    return combined
