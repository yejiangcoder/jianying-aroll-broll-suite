from __future__ import annotations

from typing import Any

from aroll_v21.decision.unit_split_binding import _unit_split_binding
from aroll_v21.ir.models import Blocker, RepeatCluster


FORBIDDEN_DEEPSEEK_FIELDS = {
    "source_start_us",
    "source_end_us",
    "target_start_us",
    "target_end_us",
    "material_id",
    "source_material_id",
    "source_segment_id",
    "segment_id",
    "final_timeline",
    "final_edl",
    "edl",
    "draft_content",
}


def unit_split_semantic_request_payload(cluster: RepeatCluster, blocker: Blocker) -> dict[str, Any]:
    unit = cluster.variants[0] if cluster.variants else None
    split_binding = _unit_split_binding(cluster)
    evidence_rows = []
    drop_text = str(split_binding.get("drop_text") or "")
    for evidence in cluster.evidence:
        metadata = evidence.metadata or {}
        spans = []
        for span in metadata.get("spans") or []:
            if not isinstance(span, dict):
                continue
            safe_span = {
                key: value
                for key, value in span.items()
                if key not in {"source_start_us", "source_end_us", "target_start_us", "target_end_us", "material_id", "segment_id"}
            }
            spans.append(safe_span)
            if not drop_text:
                drop_text = str(span.get("phrase") or "")
        candidate = metadata.get("candidate") if isinstance(metadata.get("candidate"), dict) else {}
        if candidate and not drop_text:
            drop_text = str(candidate.get("phrase") or candidate.get("overlap") or "")
        evidence_rows.append(
            {
                "evidence_id": evidence.evidence_id,
                "evidence_type": evidence.evidence_type,
                "reason": evidence.reason,
                "confidence": evidence.confidence,
                "spans": spans[:10],
            }
        )
    return {
        "issue_id": cluster.cluster_id,
        "cluster_id": cluster.cluster_id,
        "issue_type": "ambiguous_repeat",
        "severity": "medium",
        "type": "unit_split_requires_human_review",
        "repeat_type": "unit_split",
        "source_repeat_type": cluster.repeat_type,
        "text": unit.text if unit is not None else "",
        "text_before": unit.text if unit is not None else "",
        "text_after": "",
        "candidate_segment_ids": [unit.unit_id] if unit is not None else [],
        "candidate_caption_ids": list(unit.subtitle_uids) if unit is not None else [],
        "word_ids": list(unit.word_ids) if unit is not None else [],
        "source_start_us": int(unit.source_start_us) if unit is not None else 0,
        "source_end_us": int(unit.source_end_us) if unit is not None else 0,
        "target_start_us": 0,
        "target_end_us": 0,
        "reason": blocker.code,
        "allowed_decisions": [
            "apply_suggested_split",
            "keep_all",
            "requires_human_review",
        ],
        "recommended_action": "apply_suggested_split",
        "why_local_policy_cannot_decide": "local policy could not bind a safe whole-word split automatically",
        "local_context": {"cluster_id": cluster.cluster_id, "repeat_type": cluster.repeat_type},
        "suggested_for_rough_cut": "apply_suggested_split",
        "split_summary": {
            "drop_text": drop_text,
            "keep_text": "",
            "result_text": "",
            "drop_word_ids": list(split_binding["drop_word_ids"]),
            "keep_word_ids": list(split_binding["keep_word_ids"]),
            "binding": str(split_binding.get("binding") or "missing"),
            "binding_source": str(split_binding.get("binding_source") or ""),
            "failed_reason": str(
                split_binding.get("failed_reason")
                or blocker.context.get("failed_reason")
                or ""
            ),
        },
        "local_evidence": evidence_rows,
        "required_decision_schema": {
            "decision": "apply_suggested_split | keep_all | requires_human_review",
            "reason": "",
            "confidence": 0.0,
            "requires_human_review": False,
        },
    }
