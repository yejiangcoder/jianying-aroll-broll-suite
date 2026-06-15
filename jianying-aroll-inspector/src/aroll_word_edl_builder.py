from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aroll_semantic_guard import DEFAULT_PROTECTED_TERMS, normalize_compact_text


SOURCE_DURATION_US = 308_800_000
MAX_WORD_GAP_US = 100_000
TARGET_GAP_US = 0
WORD_LEAD_PAD_US = 20_000
WORD_TAIL_PAD_US = 30_000
MAX_PAUSE_AFTER_US = 40_000
EXTRA_PROTECTED_TERMS = ["虚伪", "踩踏"]
ALL_PROTECTED_TERMS = list(dict.fromkeys([*DEFAULT_PROTECTED_TERMS, *EXTRA_PROTECTED_TERMS]))


@dataclass
class WordDecision:
    drop_subtitle_uids: set[str]
    micro_keep_text: dict[str, str]
    decision_rows: list[dict[str, Any]]
    guard_rows: list[dict[str, Any]]


def subtitle_texts(subtitles: list[dict[str, Any]]) -> dict[str, str]:
    return {str(row.get("subtitle_uid") or ""): str(row.get("subtitle_text") or "") for row in subtitles}


def words_by_subtitle(words: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for word in words:
        out.setdefault(str(word["subtitle_uid"]), []).append(word)
    for items in out.values():
        items.sort(key=lambda item: (int(item["start_us"]), int(item["end_us"])))
    return out


def text_from_words(words: list[dict[str, Any]]) -> str:
    return "".join(str(word.get("word_text") or "") for word in words)


def find_word_span_for_text(words: list[dict[str, Any]], keep_text: str, prefer: str = "first") -> tuple[int, int] | None:
    wanted = normalize_compact_text(keep_text)
    if not words or not wanted:
        return None
    compact_words = [normalize_compact_text(str(word.get("word_text") or "")) for word in words]
    joined = "".join(compact_words)
    pos = joined.rfind(wanted) if prefer == "last" else joined.find(wanted)
    if pos < 0:
        return None
    cursor = 0
    start_i = 0
    end_i = len(words) - 1
    for i, token in enumerate(compact_words):
        next_cursor = cursor + len(token)
        if cursor <= pos < next_cursor:
            start_i = i
        if cursor < pos + len(wanted) <= next_cursor:
            end_i = i
            break
        cursor = next_cursor
    return start_i, end_i


def protected_atoms_in(text: str) -> list[str]:
    compact = normalize_compact_text(text)
    return [atom for atom in ALL_PROTECTED_TERMS if normalize_compact_text(atom) in compact]


def guard_drop(drop_text: str, keep_text: str) -> dict[str, Any]:
    atoms = protected_atoms_in(drop_text)
    if not atoms:
        return {"action": "allow", "atoms": []}
    keep_compact = normalize_compact_text(keep_text)
    uncovered = [atom for atom in atoms if normalize_compact_text(atom) not in keep_compact]
    if not uncovered:
        return {"action": "allow", "atoms": atoms}
    return {"action": "manual_review", "atoms": atoms, "uncovered_atoms": uncovered}


def decision_from_clusters(clusters: list[dict[str, Any]], subtitles: list[dict[str, Any]]) -> WordDecision:
    text_by_uid = subtitle_texts(subtitles)
    drop_uids: set[str] = set()
    micro_keep: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    guard_rows: list[dict[str, Any]] = []

    def add_micro(uid: str, keep_text: str, reason: str, source_cluster: str) -> None:
        if micro_keep.get(uid) == keep_text:
            return
        micro_keep[uid] = keep_text
        rows.append(
            {
                "decision": "micro_cleanup",
                "subtitle_uid": uid,
                "drop_uids": [],
                "keep_text": keep_text,
                "reason": reason,
                "source_cluster": source_cluster,
            }
        )

    def add_drop(uid: str, keep_uid: str, reason: str, source_cluster: str) -> None:
        if uid in drop_uids:
            return
        drop_text = text_by_uid.get(uid, "")
        keep_text = text_by_uid.get(keep_uid, "") or " ".join(text_by_uid.get(u, "") for u in sorted(drop_uids))
        guard = guard_drop(drop_text, keep_text)
        guard_rows.append({"source_cluster": source_cluster, "drop_uid": uid, "keep_uid": keep_uid, "drop_text": drop_text, "keep_text": keep_text, **guard})
        if guard["action"] == "allow":
            drop_uids.add(uid)
            rows.append(
                {
                    "decision": "drop",
                    "subtitle_uid": uid,
                    "drop_uids": [uid],
                    "keep_uid": keep_uid,
                    "reason": reason,
                    "source_cluster": source_cluster,
                }
            )
        else:
            rows.append(
                {
                    "decision": "manual_review",
                    "subtitle_uid": uid,
                    "drop_uids": [],
                    "keep_uid": keep_uid,
                    "reason": "semantic guard blocked full drop",
                    "source_cluster": source_cluster,
                    "guard": guard,
                }
            )

    for cluster in clusters:
        cluster_id = str(cluster.get("cluster_id") or "")
        ctype = str(cluster.get("cluster_type") or "")
        action = str(cluster.get("suggested_action") or "")
        items = cluster.get("items") or []
        if ctype in {"pronoun_variant_duplicate", "exact_duplicate", "near_duplicate", "prefix_fragment", "weak_prefix_fragment"} and action in {"drop_left", "drop_right"}:
            for uid in cluster.get("suggested_drop_uids") or []:
                add_drop(str(uid), str(cluster.get("suggested_keep_uid") or ""), str(cluster.get("reason") or ""), cluster_id)
        elif ctype == "same_subtitle_repeated_phrase":
            uid = str(cluster.get("suggested_keep_uid") or ((items[0] or {}).get("subtitle_uid") if items else ""))
            text = text_by_uid.get(uid, "")
            keep_text = infer_same_subtitle_keep_text(text)
            if keep_text and keep_text != text:
                add_micro(uid, keep_text, str(cluster.get("reason") or "same subtitle repeated phrase"), cluster_id)
        elif ctype == "semantic_replacement_candidate":
            uid = str(cluster.get("suggested_keep_uid") or ((items[0] or {}).get("subtitle_uid") if items else ""))
            text = text_by_uid.get(uid, "")
            keep_text = infer_semantic_keep_text(text)
            if keep_text and keep_text != text:
                add_micro(uid, keep_text, str(cluster.get("reason") or "semantic replacement candidate"), cluster_id)

    return WordDecision(drop_uids, micro_keep, rows, guard_rows)


def infer_same_subtitle_keep_text(text: str) -> str:
    compact = normalize_compact_text(text)
    if not compact:
        return text
    for size in range(min(8, len(compact) // 2), 0, -1):
        prefix = compact[:size]
        if compact.startswith(prefix + prefix):
            return prefix + compact[size * 2 :]
    return text


def infer_semantic_keep_text(text: str) -> str:
    return text


def kept_words_for_subtitle(subtitle_uid: str, words: list[dict[str, Any]], decision: WordDecision) -> tuple[list[dict[str, Any]], str, str]:
    if subtitle_uid in decision.drop_subtitle_uids:
        return [], "", "drop"
    keep_text = decision.micro_keep_text.get(subtitle_uid)
    if keep_text:
        prefer = "first"
        span = find_word_span_for_text(words, keep_text, prefer=prefer)
        if span is None:
            return words, keep_text, "micro_cleanup_span_missing"
        start_i, end_i = span
        return words[start_i : end_i + 1], keep_text, "micro_cleanup"
    return words, text_from_words(words), "normal"


def build_gap_cut_plan(gaps: list[dict[str, Any]], drop_uids: set[str]) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for gap in gaps:
        if str(gap.get("gap_type") or "") == "subtitle_time_gap":
            continue
        duration = int(gap.get("gap_duration_us") or 0)
        if duration <= MAX_WORD_GAP_US:
            continue
        prev_uid = str(gap.get("prev_subtitle_uid") or "")
        next_uid = str(gap.get("next_subtitle_uid") or "")
        near_drop = prev_uid in drop_uids or next_uid in drop_uids
        kept_gap = 0 if near_drop else min(MAX_PAUSE_AFTER_US, duration)
        cut_duration = max(0, duration - kept_gap)
        if cut_duration <= 0:
            continue
        plan.append(
            {
                "gap_id": gap.get("gap_id"),
                "gap_type": gap.get("gap_type"),
                "gap_duration_us": duration,
                "cut_duration_us": cut_duration,
                "kept_gap_us": kept_gap,
                "left_text": gap.get("left_text_context") or gap.get("prev_word") or "",
                "right_text": gap.get("right_text_context") or gap.get("next_word") or "",
                "reason": "near drop boundary -> zero gap" if near_drop else "word gap > 100ms -> keep max 40ms",
            }
        )
    return plan


def build_word_level_edl(
    subtitles: list[dict[str, Any]],
    words: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], WordDecision]:
    by_sub = words_by_subtitle(words)
    decision = decision_from_clusters(clusters, subtitles)
    gap_cut_plan = build_gap_cut_plan(gaps, decision.drop_subtitle_uids)
    target_start = 0
    edl: list[dict[str, Any]] = []
    subtitle_plan: list[dict[str, Any]] = []

    for row in sorted(subtitles, key=lambda item: int(item.get("subtitle_index") or 0)):
        uid = str(row.get("subtitle_uid") or "")
        original_words = by_sub.get(uid) or []
        kept_words, text_override, reason = kept_words_for_subtitle(uid, original_words, decision)
        if not kept_words:
            continue
        islands: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for word in kept_words:
            if not current:
                current = [word]
                continue
            gap = int(word["start_us"]) - int(current[-1]["end_us"])
            if gap > MAX_WORD_GAP_US:
                islands.append(current)
                current = [word]
            else:
                current.append(word)
        if current:
            islands.append(current)

        for island_index, island in enumerate(islands, start=1):
            source_start = max(0, int(island[0]["start_us"]) - WORD_LEAD_PAD_US)
            source_end = min(SOURCE_DURATION_US, int(island[-1]["end_us"]) + WORD_TAIL_PAD_US)
            duration = max(1, source_end - source_start)
            clip_id = f"wl_{len(edl) + 1:06d}"
            clip_text = text_from_words(island)
            source_reason = "word_gap_split" if len(islands) > 1 else reason
            edl.append(
                {
                    "clip_id": clip_id,
                    "source_reason": source_reason,
                    "subtitle_start_uid": uid,
                    "subtitle_end_uid": uid,
                    "word_start_id": island[0]["word_id"],
                    "word_end_id": island[-1]["word_id"],
                    "source_start_us": source_start,
                    "source_end_us": source_end,
                    "target_start_us": target_start,
                    "target_duration_us": duration,
                    "text": clip_text,
                    "drop_before_us": max(0, int(island[0]["start_us"]) - source_start),
                    "drop_after_us": max(0, source_end - int(island[-1]["end_us"])),
                    "text_override": text_override if reason.startswith("micro_cleanup") else "",
                    "near_drop_boundary": uid in decision.micro_keep_text or uid in decision.drop_subtitle_uids,
                    "warnings": [] if reason != "micro_cleanup_span_missing" else ["MICRO_CLEANUP_WORD_SPAN_MISSING"],
                }
            )
            subtitle_plan.append(
                {
                    "fragment_id": f"sf_{len(subtitle_plan) + 1:06d}",
                    "source_subtitle_uid": uid,
                    "source_text": str(row.get("subtitle_text") or ""),
                    "fragment_text": clip_text if source_reason == "word_gap_split" else (text_override or clip_text),
                    "source_start_us": source_start,
                    "source_end_us": source_end,
                    "target_start_us": target_start,
                    "target_duration_us": duration,
                    "word_start_id": island[0]["word_id"],
                    "word_end_id": island[-1]["word_id"],
                    "requires_cloned_material": reason != "normal" or len(islands) > 1,
                    "text_override": text_override if reason.startswith("micro_cleanup") else "",
                    "reason": source_reason if source_reason else "normal",
                }
            )
            target_start += duration

    guard_report = {
        "blocked_full_drops": [row for row in decision.guard_rows if row.get("action") == "manual_review"],
        "converted_to_micro_cleanup": [row for row in decision.decision_rows if row.get("decision") == "micro_cleanup"],
        "force_keep": [],
        "manual_review": [row for row in decision.decision_rows if row.get("decision") == "manual_review"],
        "guard_rows": decision.guard_rows,
        "protected_atoms": ALL_PROTECTED_TERMS,
    }
    return edl, subtitle_plan, gap_cut_plan, guard_report, decision
