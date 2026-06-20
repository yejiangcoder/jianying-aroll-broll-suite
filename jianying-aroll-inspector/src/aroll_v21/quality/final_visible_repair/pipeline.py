from __future__ import annotations

from typing import Protocol


class RepairRule(Protocol):
    name: str
