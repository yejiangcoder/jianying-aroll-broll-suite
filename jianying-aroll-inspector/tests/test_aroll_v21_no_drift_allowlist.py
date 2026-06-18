from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V21_SRC = ROOT / "src" / "aroll_v21"
V21_ENTRY = ROOT / "run_aroll_v21_operator.ps1"


def v21_text() -> str:
    return "\n".join([*(path.read_text("utf-8") for path in V21_SRC.rglob("*.py")), V21_ENTRY.read_text("utf-8")])


class ArollV21NoDriftAllowlistTests(unittest.TestCase):
    def test_fallback_mentions_are_allowlisted_contract_text_only(self) -> None:
        for line in [line.strip() for line in v21_text().splitlines() if "fallback" in line.lower()]:
            lowered = line.lower()
            self.assertTrue(
                "no_writer_fallback" in lowered
                or "writer_fallback_count" in lowered
                or "without fallback" in lowered
                or "fallback is forbidden" in lowered
                or "fallback_policy" in lowered
                or "fail-closed fallback" in lowered,
                line,
            )

    def test_forbidden_executable_fallback_shapes_are_absent(self) -> None:
        lowered = v21_text().lower()
        for token in (
            "fallback_source =",
            " or fallback",
            "except: fallback",
            "fallback to first",
            "safe_sources[0]",
        ):
            self.assertNotIn(token, lowered)


if __name__ == "__main__":
    unittest.main()
