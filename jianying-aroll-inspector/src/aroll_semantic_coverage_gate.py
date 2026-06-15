from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aroll_text_normalize import char_ngrams, jaccard, lcs_ratio, normalize_text, protected_atoms_in


FILLER_ONLY = {"啊", "呐", "呢", "吧", "嘛", "哎", "额", "嗯"}
LEGAL_DROP_MARKERS = (
    "重复",
    "duplicate",
    "prefix",
    "fragment",
    "unfinished",
    "restart",
    "damaged",
    "dirty",
    "不完整",
    "弱",
    "weak",
    "pronoun",
    "保留完整",
    "保留最终",
)

DIRTY_STUTTER_MAX_PREFIX = 8
SINGLE_CHAR_STUTTER_PREFIXES = {"给", "我", "你", "他", "她", "它", "这", "那", "就", "再", "重", "是", "有", "不"}


def _best_coverage(norm: str, final_norm: str, final_texts: list[str]) -> dict[str, Any]:
    return _coverage_score(norm, final_norm, final_texts)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _load_script_context(script_path: Path | None) -> dict[str, Any]:
    if not script_path or not script_path.exists():
        return {"script_path": str(script_path) if script_path else "", "exists": False, "norm_text": ""}
    text = script_path.read_text("utf-8", errors="ignore")
    return {"script_path": str(script_path), "exists": True, "norm_text": normalize_text(text)}


def _fragment_text(row: dict[str, Any]) -> str:
    return str(row.get("fragment_text") or row.get("text") or row.get("subtitle_text") or "")


def _drop_maps(merged: dict[str, Any]) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    drops = {
        int(row.get("subtitle_index") or 0): row
        for row in (merged.get("drop_decisions") or [])
        if int(row.get("subtitle_index") or 0) > 0
    }
    micros = {
        int(row.get("subtitle_index") or 0): row
        for row in (merged.get("micro_cleanups") or [])
        if int(row.get("subtitle_index") or 0) > 0
    }
    return drops, micros


def _is_meaningful(text: str) -> bool:
    norm = normalize_text(text)
    if len(norm) < 4:
        return False
    if norm in FILLER_ONLY:
        return False
    return True


def _importance(text: str, indices: list[int], script_norm: str) -> tuple[str, str]:
    norm = normalize_text(text)
    atoms = protected_atoms_in(text)
    if atoms:
        return "high", "protected atom: " + ",".join(atoms)
    if script_norm and norm and norm in script_norm:
        return "high", "source phrase appears in script context"
    if len(indices) >= 2 and len(norm) >= 8:
        return "high", "multi-subtitle semantic unit"
    if len(norm) >= 7:
        return "medium", "meaningful subtitle"
    return "low", "short semantic unit"


def build_source_semantic_units(
    subtitles: list[dict[str, Any]],
    script_path: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    script = _load_script_context(script_path)
    rows = sorted(subtitles, key=lambda row: int(row.get("subtitle_index") or 0))
    units: list[dict[str, Any]] = []
    uid = 1
    for row in rows:
        index = int(row.get("subtitle_index") or 0)
        text = str(row.get("subtitle_text") or "")
        if not _is_meaningful(text):
            continue
        importance, reason = _importance(text, [index], script["norm_text"])
        units.append(
            {
                "unit_id": f"su_{uid:04d}",
                "subtitle_indices": [index],
                "source_text": text,
                "norm_text": normalize_text(text),
                "importance": importance,
                "reason": reason,
            }
        )
        uid += 1
    return units, script


def _coverage_score(norm: str, final_norm: str, final_texts: list[str]) -> dict[str, Any]:
    if not norm:
        return {"covered": True, "method": "empty", "score": 1.0, "matched_text": ""}
    if norm in final_norm:
        return {"covered": True, "method": "substring", "score": 1.0, "matched_text": norm}
    best = {"score": 0.0, "matched_text": "", "method": "lcs"}
    for start in range(len(final_texts)):
        window = ""
        for end in range(start, min(len(final_texts), start + 4)):
            window = normalize_text((window + final_texts[end]))
            if not window:
                continue
            lcs = lcs_ratio(norm, window)
            jac = jaccard(char_ngrams(norm, 2), char_ngrams(window, 2))
            score = max(lcs, jac)
            if score > best["score"]:
                best = {"score": round(score, 4), "matched_text": " ".join(final_texts[start : end + 1]), "method": "lcs_or_jaccard"}
    return {"covered": float(best["score"]) >= 0.82, **best}


def _dedupe_prefix(norm: str) -> tuple[str, str]:
    """Collapse obvious ASR stutters and repeated phrase prefixes."""
    if not norm:
        return norm, ""
    n = len(norm)
    max_len = min(DIRTY_STUTTER_MAX_PREFIX, n // 2)
    for size in range(max_len, 0, -1):
        prefix = norm[:size]
        if size == 1 and prefix not in SINGLE_CHAR_STUTTER_PREFIXES:
            continue
        if norm.startswith(prefix + prefix):
            return prefix + norm[size * 2 :], "same_phrase_repeated"
    if n % 2 == 0 and norm[: n // 2] == norm[n // 2 :]:
        return norm[: n // 2], "same_phrase_repeated"
    return norm, ""


def _prefix_restart_fragment(norm: str) -> tuple[bool, str]:
    """Detect half-sentence restarts like 就是在亲手摧毁就是在."""
    if len(norm) < 6:
        return False, ""
    max_len = min(DIRTY_STUTTER_MAX_PREFIX, len(norm) // 2)
    for size in range(max_len, 1, -1):
        prefix = norm[:size]
        if norm.endswith(prefix) and len(norm) > size * 2:
            return True, prefix
    return False, ""


def _classify_dirty_unit(
    unit: dict[str, Any],
    drops: dict[int, dict[str, Any]],
    micros: dict[int, dict[str, Any]],
    final_norm: str,
    final_texts: list[str],
) -> tuple[bool, dict[str, Any] | None]:
    indices = [int(index) for index in unit.get("subtitle_indices") or []]
    source_text = str(unit.get("source_text") or "")
    norm = str(unit.get("norm_text") or normalize_text(source_text))

    if len(indices) == 1 and indices[0] in micros:
        kept_text = str(micros[indices[0]].get("kept_text") or "")
        kept_norm = normalize_text(kept_text)
        coverage = _best_coverage(kept_norm, final_norm, final_texts)
        if kept_norm and coverage.get("covered"):
            return True, {
                **unit,
                "filtered_reason": "micro_cleanup_covered",
                "clean_text": kept_text,
                "clean_norm_text": kept_norm,
                "equivalent_coverage": coverage,
            }

    if indices and all(index in drops for index in indices):
        keep_text = " ".join(str(drops[index].get("keep_instead_text") or "") for index in indices).strip()
        keep_norm = normalize_text(keep_text)
        coverage = _best_coverage(keep_norm, final_norm, final_texts) if keep_norm else {"covered": False, "score": 0}
        reasons = " ".join(str(drops[index].get("reason") or "") + " " + str(drops[index].get("source") or "") for index in indices)
        if coverage.get("covered") or any(marker in reasons for marker in LEGAL_DROP_MARKERS):
            return True, {
                **unit,
                "filtered_reason": "duplicate_take_covered" if coverage.get("covered") else "self_correction",
                "clean_text": keep_text,
                "clean_norm_text": keep_norm,
                "equivalent_coverage": coverage,
                "drop_reasons": reasons[:240],
            }

    collapsed_norm, collapsed_reason = _dedupe_prefix(norm)
    if collapsed_reason and collapsed_norm != norm:
        coverage = _best_coverage(collapsed_norm, final_norm, final_texts)
        return True, {
            **unit,
            "filtered_reason": collapsed_reason,
            "clean_text": collapsed_norm,
            "clean_norm_text": collapsed_norm,
            "equivalent_coverage": coverage,
        }

    is_restart, prefix = _prefix_restart_fragment(norm)
    if is_restart:
        coverage = _best_coverage(norm[: -len(prefix)] if prefix else norm, final_norm, final_texts)
        return True, {
            **unit,
            "filtered_reason": "prefix_fragment",
            "clean_text": norm[: -len(prefix)] if prefix else "",
            "clean_norm_text": norm[: -len(prefix)] if prefix else "",
            "equivalent_coverage": coverage,
            "repeated_prefix": prefix,
        }

    return False, None


def _legal_drop(
    unit: dict[str, Any],
    drops: dict[int, dict[str, Any]],
    micros: dict[int, dict[str, Any]],
    final_norm: str,
) -> tuple[bool, str]:
    indices = [int(index) for index in unit.get("subtitle_indices") or []]
    if len(indices) == 1 and indices[0] in micros:
        kept_text = str(micros[indices[0]].get("kept_text") or "")
        if kept_text and normalize_text(kept_text) and normalize_text(kept_text) in final_norm:
            return True, "micro cleanup kept core text"
    if not indices or not all(index in drops for index in indices):
        return False, ""
    reasons = " ".join(str(drops[index].get("reason") or "") + " " + str(drops[index].get("source") or "") for index in indices)
    keep_text = " ".join(str(drops[index].get("keep_instead_text") or "") for index in indices)
    if keep_text and normalize_text(keep_text) and normalize_text(keep_text) in final_norm:
        return True, "dropped with equivalent keep text covered"
    if any(marker in reasons for marker in LEGAL_DROP_MARKERS):
        return True, "legal drop marker: " + reasons[:160]
    return False, ""


def build_semantic_coverage_report(
    subtitles: list[dict[str, Any]],
    final_display_subtitle_plan: list[dict[str, Any]],
    merged: dict[str, Any],
    duplicate_family_guard_report: dict[str, Any],
    script_path: Path | None = None,
) -> tuple[dict[str, Any], str]:
    units, script = build_source_semantic_units(subtitles, script_path)
    next_unit_number = len(units) + 1
    for family in duplicate_family_guard_report.get("families") or []:
        for candidate in family.get("candidates") or []:
            text = str(candidate.get("text") or "")
            indices = [int(index) for index in candidate.get("subtitle_indices") or []]
            if not text or not indices:
                continue
            units.append(
                {
                    "unit_id": f"su_{next_unit_number:04d}",
                    "subtitle_indices": indices,
                    "source_text": text,
                    "norm_text": normalize_text(text),
                    "importance": "high",
                    "reason": f"duplicate family candidate {family.get('family_id')}",
                    "duplicate_family_id": family.get("family_id"),
                    "duplicate_take_id": candidate.get("take_id"),
                }
            )
            next_unit_number += 1
    drops, micros = _drop_maps(merged)
    final_texts = [_fragment_text(row) for row in final_display_subtitle_plan if _fragment_text(row)]
    final_norm = normalize_text("\n".join(final_texts))
    covered_units: list[dict[str, Any]] = []
    missing_required: list[dict[str, Any]] = []
    allowed_dropped: list[dict[str, Any]] = []
    filtered_dirty_units: list[dict[str, Any]] = []
    raw_required_units = [unit for unit in units if unit.get("importance") in {"high", "medium"}]
    clean_required_units: list[dict[str, Any]] = []
    for unit in raw_required_units:
        is_dirty, dirty_row = _classify_dirty_unit(unit, drops, micros, final_norm, final_texts)
        if is_dirty and dirty_row:
            filtered_dirty_units.append(dirty_row)
            continue
        clean_required_units.append(unit)

    for unit in clean_required_units:
        coverage = _coverage_score(str(unit.get("norm_text") or ""), final_norm, final_texts)
        if coverage["covered"]:
            covered_units.append(unit | {"coverage": coverage})
            continue
        allowed, reason = _legal_drop(unit, drops, micros, final_norm)
        if allowed:
            allowed_dropped.append(unit | {"allowed_drop_reason": reason, "coverage": coverage})
            continue
        missing_required.append(unit | {"coverage": coverage})
    fatal_reasons = []
    if missing_required:
        fatal_reasons.append("SEMANTIC_COVERAGE_MISSING_REQUIRED_UNITS")
    if int(duplicate_family_guard_report.get("all_dropped_family_count_after") or 0) > 0:
        fatal_reasons.append("DUPLICATE_FAMILY_STILL_ALL_DROPPED")
    report = {
        "source_unit_count": len(units),
        "required_unit_count": len(clean_required_units),
        "raw_source_unit_count": len(units),
        "raw_required_unit_count": len(raw_required_units),
        "clean_required_unit_count": len(clean_required_units),
        "filtered_dirty_unit_count": len(filtered_dirty_units),
        "dirty_unit_filtered_count": len(filtered_dirty_units),
        "allowed_dropped_unit_count": len(allowed_dropped),
        "coverage_false_positive_prevented_count": len(filtered_dirty_units) + len(allowed_dropped),
        "covered_unit_count": len(covered_units),
        "covered_required_unit_count": len(covered_units),
        "missing_required_unit_count": len(missing_required),
        "missing_required_units": missing_required,
        "covered_units": covered_units,
        "allowed_dropped_units": allowed_dropped,
        "filtered_dirty_units": filtered_dirty_units,
        "clean_required_units": clean_required_units,
        "raw_source_units": units,
        "script": {"path": script.get("script_path"), "exists": script.get("exists")},
        "duplicate_family_guard": {
            "family_count": duplicate_family_guard_report.get("family_count"),
            "all_dropped_family_count_after": duplicate_family_guard_report.get("all_dropped_family_count_after"),
        },
        "fatal_reasons": fatal_reasons,
    }
    lines = [
        "# Semantic Coverage Gate",
        "",
        f"- raw_source_unit_count: {report['raw_source_unit_count']}",
        f"- clean_required_unit_count: {report['clean_required_unit_count']}",
        f"- filtered_dirty_unit_count: {report['filtered_dirty_unit_count']}",
        f"- covered_required_unit_count: {report['covered_required_unit_count']}",
        f"- missing_required_unit_count: {report['missing_required_unit_count']}",
        f"- coverage_false_positive_prevented_count: {report['coverage_false_positive_prevented_count']}",
        f"- fatal_reasons: {', '.join(fatal_reasons) if fatal_reasons else 'none'}",
        "",
        "## A. Required Units Covered",
    ]
    for unit in covered_units[:50]:
        lines.append(f"- {unit['unit_id']} {unit['subtitle_indices']}: {unit['source_text']} | score={unit['coverage'].get('score')}")
    lines.extend([
        "",
        "## B. Dirty Units Filtered",
    ])
    for unit in filtered_dirty_units[:80]:
        coverage = unit.get("equivalent_coverage") or {}
        lines.append(
            f"- {unit['unit_id']} {unit['subtitle_indices']}: {unit['source_text']} | "
            f"reason={unit.get('filtered_reason')} | covered={coverage.get('covered')} score={coverage.get('score')}"
        )
    lines.extend([
        "",
        "## C. Missing Required Units",
    ])
    for unit in missing_required[:50]:
        lines.append(f"- {unit['unit_id']} {unit['subtitle_indices']}: {unit['source_text']} | score={unit['coverage'].get('score')}")
    lines.extend(["", "## Allowed Dropped Units"])
    for unit in allowed_dropped[:50]:
        lines.append(f"- {unit['unit_id']} {unit['subtitle_indices']}: {unit['source_text']} | {unit['allowed_drop_reason']}")
    return report, "\n".join(lines) + "\n"
