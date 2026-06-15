from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any


DEFAULT_PROTECTED_TERMS: tuple[str, ...] = ()


def normalize_compact_text(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?：:；;（）()\[\]【】「」『』\"'“”‘’]", "", text or "")


def atoms_in_text(text: str, atoms: Iterable[str] | None = None) -> list[str]:
    compact = normalize_compact_text(text)
    protected = tuple(atoms) if atoms is not None else DEFAULT_PROTECTED_TERMS
    return [atom for atom in protected if normalize_compact_text(atom) in compact]


def guard_drop_span(span: dict[str, Any], atoms: Iterable[str] | None = None) -> dict[str, Any]:
    drop_text = str(span.get("drop_text") or "")
    keep_text = str(span.get("keep_instead_text") or "")
    dropped_atoms = atoms_in_text(drop_text, atoms)
    if not dropped_atoms:
        return {"action": "allow", "protected_atoms": []}

    keep_compact = normalize_compact_text(keep_text)
    unprotected = [
        atom
        for atom in dropped_atoms
        if normalize_compact_text(atom) not in keep_compact
    ]
    if not unprotected:
        return {"action": "allow", "protected_atoms": dropped_atoms}

    start = int(span.get("subtitle_start_index") or 0)
    end = int(span.get("subtitle_end_index") or start)
    if start == end:
        best_atom = max(unprotected, key=lambda item: len(normalize_compact_text(item)))
        return {
            "action": "convert_to_micro_cleanup",
            "protected_atoms": dropped_atoms,
            "kept_text": best_atom,
            "reason": f"drop contains protected semantic atom: {best_atom}",
        }

    return {
        "action": "force_keep",
        "protected_atoms": dropped_atoms,
        "reason": "multi-subtitle drop contains protected semantic atom",
    }


def build_semantic_guard_report(
    guarded_rows: list[dict[str, Any]],
    fatal_reasons: list[str] | None = None,
    protected_atoms: Iterable[str] | None = None,
) -> dict[str, Any]:
    blocked = [row for row in guarded_rows if row.get("guard_action") == "force_keep"]
    converted = [row for row in guarded_rows if row.get("guard_action") == "convert_to_micro_cleanup"]
    force_keep = [row for row in guarded_rows if row.get("guard_action") in {"force_keep", "must_keep"}]
    return {
        "protected_atoms": list(protected_atoms) if protected_atoms is not None else list(DEFAULT_PROTECTED_TERMS),
        "blocked_full_drops": blocked,
        "converted_to_micro_cleanup": converted,
        "force_keep": force_keep,
        "fatal_reasons": fatal_reasons or [],
    }
