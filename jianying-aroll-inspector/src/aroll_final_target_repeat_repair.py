from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from aroll_repair_applier import source_range_for_word_ids, word_map
from aroll_repair_proposal import RepairProposal, proposal_to_dict


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _norm(text: str) -> str:
    return re.sub(r"[\s,，。.!！?？、:：;；\"'“”‘’（）()【】\[\]《》<>-]+", "", str(text or ""))


def _row_text(row: dict[str, Any]) -> str:
    return str(row.get("fragment_text") or row.get("text") or "")


def _word_tokens(row: dict[str, Any], words_by_id: dict[str, dict[str, Any]]) -> list[str]:
    return [str((words_by_id.get(str(word_id)) or {}).get("word_text") or "") for word_id in (row.get("word_ids") or []) if str(word_id)]


def _word_ids(row: dict[str, Any]) -> list[str]:
    return [str(word_id) for word_id in (row.get("word_ids") or []) if str(word_id)]


def _longest_suffix_prefix_overlap(left_tokens: list[str], right_tokens: list[str]) -> int:
    max_size = min(len(left_tokens), len(right_tokens))
    for size in range(max_size, 1, -1):
        if left_tokens[-size:] == right_tokens[:size]:
            return size
    return 0


def _partial_word_overlap_remove_ids(
    *,
    overlap_text: str,
    left_tokens: list[str],
    left_ids: list[str],
    right_tokens: list[str],
    right_ids: list[str],
) -> tuple[list[str], str]:
    overlap_text = str(overlap_text or "")
    if not overlap_text:
        return [], ""
    consumed = ""
    remove_ids: list[str] = []
    right_index = 0
    for token, word_id in zip(right_tokens, right_ids):
        if overlap_text.startswith(consumed + token):
            consumed += token
            remove_ids.append(word_id)
            right_index += 1
            if consumed == overlap_text:
                return remove_ids, consumed
            continue
        break
    remainder = overlap_text[len(consumed) :]
    if remainder and right_index < len(right_tokens) and right_tokens[right_index].startswith(remainder):
        suffix = ""
        suffix_ids: list[str] = []
        for token, word_id in zip(reversed(left_tokens), reversed(left_ids)):
            suffix = token + suffix
            suffix_ids.insert(0, word_id)
            if suffix == remainder:
                return suffix_ids + remove_ids, overlap_text
            if len(suffix) > len(remainder):
                break
    return [], ""


def _proposal_for_pair(
    *,
    candidate: dict[str, Any],
    left_idx: int,
    left_row: dict[str, Any],
    right_idx: int,
    right_row: dict[str, Any],
    words_by_id: dict[str, dict[str, Any]],
    proposal_index: int,
) -> RepairProposal:
    left_text = _row_text(left_row)
    right_text = _row_text(right_row)
    left_norm = _norm(left_text)
    right_norm = _norm(right_text)
    left_ids = _word_ids(left_row)
    right_ids = _word_ids(right_row)
    left_tokens = _word_tokens(left_row, words_by_id)
    right_tokens = _word_tokens(right_row, words_by_id)
    overlap_text = str(candidate.get("overlap_text") or "")
    if left_norm and right_norm and left_norm in right_norm and len(left_norm) < len(right_norm):
        start, end = source_range_for_word_ids(left_ids, words_by_id)
        return RepairProposal(
            proposal_id=f"final_repeat_{proposal_index:04d}",
            repair_type="drop_contained_final_repeat",
            source_gate="final_repeat_gate",
            confidence=str(candidate.get("confidence") or "medium") if str(candidate.get("confidence") or "") in {"high", "medium", "low"} else "medium",
            reason="left short phrase is contained in the following fuller phrase",
            left_text=left_text,
            right_text=right_text,
            keep_word_ids=right_ids,
            remove_word_ids=left_ids,
            remove_source_start_us=start,
            remove_source_end_us=end,
            source_issue_id=str(candidate.get("cluster_id") or candidate.get("issue_id") or ""),
            candidate_id=str(candidate.get("cluster_id") or candidate.get("issue_id") or ""),
            metadata={"drop_index": left_idx, "keep_index": right_idx, "strategy": "drop_left_short_contained"},
        )

    if right_norm and left_norm and right_norm in left_norm and len(right_norm) < len(left_norm):
        start, end = source_range_for_word_ids(right_ids, words_by_id)
        return RepairProposal(
            proposal_id=f"final_repeat_{proposal_index:04d}",
            repair_type="drop_contained_final_repeat",
            source_gate="final_repeat_gate",
            confidence=str(candidate.get("confidence") or "medium") if str(candidate.get("confidence") or "") in {"high", "medium", "low"} else "medium",
            reason="right short phrase is contained in the previous fuller phrase",
            left_text=left_text,
            right_text=right_text,
            keep_word_ids=left_ids,
            remove_word_ids=right_ids,
            remove_source_start_us=start,
            remove_source_end_us=end,
            source_issue_id=str(candidate.get("cluster_id") or candidate.get("issue_id") or ""),
            candidate_id=str(candidate.get("cluster_id") or candidate.get("issue_id") or ""),
            metadata={"drop_index": right_idx, "keep_index": left_idx, "strategy": "drop_right_short_contained"},
        )

    overlap_size = _longest_suffix_prefix_overlap(left_tokens, right_tokens)
    if overlap_size >= 2 and overlap_size < len(right_ids):
        remove_ids = right_ids[:overlap_size]
        keep_ids = left_ids + right_ids[overlap_size:]
        start, end = source_range_for_word_ids(remove_ids, words_by_id)
        merged = left_text + "".join(right_tokens[overlap_size:])
        return RepairProposal(
            proposal_id=f"final_repeat_{proposal_index:04d}",
            repair_type="overlap_merge_final_repeat",
            source_gate="final_repeat_gate",
            confidence=str(candidate.get("confidence") or "medium") if str(candidate.get("confidence") or "") in {"high", "medium", "low"} else "medium",
            reason="suffix-prefix overlap; remove one copy of the overlap and preserve unique prefix/suffix",
            left_text=left_text,
            right_text=right_text,
            merged_text=merged,
            duplicate_text="".join(right_tokens[:overlap_size]),
            keep_word_ids=keep_ids,
            remove_word_ids=remove_ids,
            remove_source_start_us=start,
            remove_source_end_us=end,
            source_issue_id=str(candidate.get("cluster_id") or candidate.get("issue_id") or ""),
            candidate_id=str(candidate.get("cluster_id") or candidate.get("issue_id") or ""),
            metadata={"left_index": left_idx, "right_index": right_idx, "overlap_size": overlap_size},
        )

    partial_remove_ids, partial_duplicate_text = _partial_word_overlap_remove_ids(
        overlap_text=overlap_text,
        left_tokens=left_tokens,
        left_ids=left_ids,
        right_tokens=right_tokens,
        right_ids=right_ids,
    )
    if partial_remove_ids:
        keep_ids = [word_id for word_id in left_ids + right_ids if word_id not in set(partial_remove_ids)]
        start, end = source_range_for_word_ids(partial_remove_ids, words_by_id)
        return RepairProposal(
            proposal_id=f"final_repeat_{proposal_index:04d}",
            repair_type="overlap_merge_final_repeat",
            source_gate="final_repeat_gate",
            confidence=str(candidate.get("confidence") or "medium") if str(candidate.get("confidence") or "") in {"high", "medium", "low"} else "medium",
            reason="character-level suffix-prefix overlap across word boundary; remove duplicate full words only",
            left_text=left_text,
            right_text=right_text,
            merged_text="",
            duplicate_text=partial_duplicate_text,
            keep_word_ids=keep_ids,
            remove_word_ids=partial_remove_ids,
            remove_source_start_us=start,
            remove_source_end_us=end,
            source_issue_id=str(candidate.get("cluster_id") or candidate.get("issue_id") or ""),
            candidate_id=str(candidate.get("cluster_id") or candidate.get("issue_id") or ""),
            metadata={"left_index": left_idx, "right_index": right_idx, "overlap_text": overlap_text, "partial_word_overlap": True},
        )

    return RepairProposal(
        proposal_id=f"final_repeat_{proposal_index:04d}",
        repair_type="block",
        source_gate="final_repeat_gate",
        confidence=str(candidate.get("confidence") or "medium") if str(candidate.get("confidence") or "") in {"high", "medium", "low"} else "medium",
        reason="final repeat candidate is not a strict containment or suffix-prefix overlap",
        left_text=left_text,
        right_text=right_text,
        source_issue_id=str(candidate.get("cluster_id") or candidate.get("issue_id") or ""),
        candidate_id=str(candidate.get("cluster_id") or candidate.get("issue_id") or ""),
        metadata={"left_index": left_idx, "right_index": right_idx},
    )


def propose_final_target_repeat_repairs(
    *,
    final_repeat_gate_report: dict[str, Any],
    display_subtitle_plan: list[dict[str, Any]],
    word_timeline: list[dict[str, Any]],
) -> tuple[list[RepairProposal], dict[str, Any]]:
    candidates = list(final_repeat_gate_report.get("final_target_repeat_candidates") or [])
    display_by_index = {index: row for index, row in enumerate(display_subtitle_plan, start=1)}
    display_by_uid = {str(row.get("fragment_id") or ""): (index, row) for index, row in enumerate(display_subtitle_plan, start=1)}
    words_by_id = word_map(word_timeline)
    proposals: list[RepairProposal] = []
    unresolved: list[dict[str, Any]] = []

    for candidate in candidates:
        rows: list[tuple[int, dict[str, Any]]] = []
        for item in candidate.get("items") or []:
            idx = int(item.get("subtitle_index") or 0)
            row = display_by_index.get(idx)
            if row:
                rows.append((idx, row))
        if len(rows) < 2:
            unresolved.append(candidate | {"unresolved_reason": "candidate rows not found in display subtitle plan"})
            continue
        rows.sort(key=lambda item: int(item[1].get("source_start_us") or 0))
        for pair_index in range(len(rows) - 1):
            left_idx, left_row = rows[pair_index]
            right_idx, right_row = rows[pair_index + 1]
            proposals.append(
                _proposal_for_pair(
                    candidate=candidate,
                    left_idx=left_idx,
                    left_row=left_row,
                    right_idx=right_idx,
                    right_row=right_row,
                    words_by_id=words_by_id,
                    proposal_index=len(proposals) + 1,
                )
            )

    blocking_issues = [
        row
        for row in (final_repeat_gate_report.get("blocking_issues") or [])
        if str(row.get("issue_type") or "") in {"prefix_overlap", "semantic_containment_repeat"}
    ]
    for issue in blocking_issues:
        subtitle_ids = [str(item) for item in (issue.get("involved_subtitle_ids") or []) if str(item)]
        if len(subtitle_ids) < 2:
            unresolved.append(issue | {"unresolved_reason": "blocking issue lacks involved subtitle ids"})
            continue
        left = display_by_uid.get(subtitle_ids[0])
        right = display_by_uid.get(subtitle_ids[1])
        if not left or not right:
            unresolved.append(issue | {"unresolved_reason": "blocking issue subtitle ids not found in display plan"})
            continue
        left_idx, left_row = left
        right_idx, right_row = right
        proposal = _proposal_for_pair(
            candidate={
                "cluster_id": issue.get("issue_id"),
                "issue_id": issue.get("issue_id"),
                "confidence": issue.get("confidence") or "medium",
                "overlap_text": issue.get("overlap_text") or "",
            },
            left_idx=left_idx,
            left_row=left_row,
            right_idx=right_idx,
            right_row=right_row,
            words_by_id=words_by_id,
            proposal_index=len(proposals) + 1,
        )
        proposals.append(proposal)

    report = {
        "final_target_repeat_before_count": len(candidates),
        "blocking_issue_repeat_before_count": len(blocking_issues),
        "proposal_count": len(proposals),
        "drop_contained_count": len([row for row in proposals if row.repair_type == "drop_contained_final_repeat"]),
        "overlap_merge_count": len([row for row in proposals if row.repair_type == "overlap_merge_final_repeat"]),
        "conservative_keep_count": len([row for row in proposals if row.repair_type == "conservative_keep"]),
        "block_count": len([row for row in proposals if row.repair_type == "block"]) + len(unresolved),
        "proposals": [proposal_to_dict(proposal) for proposal in proposals],
        "unresolved": unresolved,
    }
    return proposals, report
