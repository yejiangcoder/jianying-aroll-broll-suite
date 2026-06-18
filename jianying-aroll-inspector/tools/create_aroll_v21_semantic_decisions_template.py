from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

FORBIDDEN_DECISION_OUTPUT_FIELDS = {
    "source_start_us",
    "source_end_us",
    "target_start_us",
    "target_end_us",
    "edl",
    "final_edl",
    "draft_content",
    "material_id",
    "segment_id",
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def build_template(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for payload in payloads:
        cluster_id = str(payload.get("cluster_id") or "")
        if not cluster_id:
            continue
        rows.append(
            {
                "cluster_id": cluster_id,
                "decision": "keep_all",
                "reason": "",
                "confidence": 0.0,
                "requires_human_review": True,
            }
        )
    return rows


def build_suggested_for_rough_cut(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for payload in payloads:
        cluster_id = str(payload.get("cluster_id") or "")
        if not cluster_id:
            rows.append(_template_error_decision("", "TEMPLATE_CANNOT_SUGGEST_DECISION: payload is missing cluster_id"))
            continue
        if str(payload.get("type") or "") == "unit_split_requires_human_review":
            rows.append(_unit_split_rough_cut_decision(payload, cluster_id))
            continue
        explicit = _explicit_suggested_decision(payload, cluster_id)
        if explicit is not None:
            rows.append(explicit)
        elif _has_invalid_explicit_suggestion(payload):
            rows.append(_template_error_decision(cluster_id, "TEMPLATE_SUGGESTED_DECISION_NOT_ALLOWED: suggested_for_rough_cut is not allowed by payload.allowed_decisions"))
        elif str(payload.get("type") or "") == "final_target_repeat" and str(payload.get("cluster_type") or "") == "semantic_containment_take":
            rows.append(
                {
                    "cluster_id": cluster_id,
                    "decision": "keep_longest_drop_others",
                    "reason": "rough cut closeout: remove shorter contained take",
                    "confidence": 0.75,
                    "requires_human_review": False,
                }
            )
        elif str(payload.get("repeat_type") or "") == "modifier_redundancy":
            rows.append(
                {
                    "cluster_id": cluster_id,
                    "decision": "drop_redundant_modifier",
                    "reason": "rough cut closeout: remove left adjacent modifier before the same head",
                    "confidence": 0.75,
                    "requires_human_review": False,
                }
            )
        else:
            rows.append(
                _template_error_decision(
                    cluster_id,
                    "TEMPLATE_UNSUPPORTED_SEMANTIC_PAYLOAD_TYPE: "
                    f"type={str(payload.get('type') or '')} repeat_type={str(payload.get('repeat_type') or '')}",
                )
            )
    return rows


def _template_error_decision(cluster_id: str, reason: str) -> dict[str, Any]:
    return {
        "cluster_id": cluster_id,
        "decision": "requires_human_review",
        "reason": reason,
        "confidence": 0.0,
        "requires_human_review": True,
    }


def _unit_split_rough_cut_decision(payload: dict[str, Any], cluster_id: str) -> dict[str, Any]:
    suggested = str(payload.get("suggested_for_rough_cut") or "").strip()
    allowed = _allowed_decisions(payload)
    if not allowed:
        return _template_error_decision(cluster_id, "TEMPLATE_CANNOT_SUGGEST_DECISION: unit split payload is missing allowed_decisions")
    if suggested and suggested not in allowed:
        return _template_error_decision(
            cluster_id,
            "TEMPLATE_SUGGESTED_DECISION_NOT_ALLOWED: suggested_for_rough_cut is not allowed by payload.allowed_decisions",
        )
    if _unit_split_has_safe_whole_word_binding(payload) and "apply_suggested_split" in allowed:
        return {
            "cluster_id": cluster_id,
            "decision": "apply_suggested_split",
            "reason": "rough cut closeout: unit split has safe whole-word binding",
            "confidence": 0.75,
            "requires_human_review": False,
        }
    if "keep_all" in allowed:
        return {
            "cluster_id": cluster_id,
            "decision": "keep_all",
            "reason": "rough cut closeout: unit split lacks safe whole-word binding; keep all to avoid unsafe cut",
            "confidence": 0.65,
            "requires_human_review": False,
        }
    return _template_error_decision(
        cluster_id,
        "TEMPLATE_CANNOT_SUGGEST_DECISION: unit split cannot apply safe split and keep_all is not allowed",
    )


def _unit_split_has_safe_whole_word_binding(payload: dict[str, Any]) -> bool:
    summary = payload.get("split_summary") if isinstance(payload.get("split_summary"), dict) else {}
    binding = str(summary.get("binding") or "").strip()
    drop_word_ids = summary.get("drop_word_ids") if isinstance(summary.get("drop_word_ids"), list) else []
    keep_word_ids = summary.get("keep_word_ids") if isinstance(summary.get("keep_word_ids"), list) else []
    return bool(binding == "whole_word" and drop_word_ids and keep_word_ids)


def _allowed_decisions(payload: dict[str, Any]) -> set[str]:
    return {str(value).strip() for value in (payload.get("allowed_decisions") or []) if str(value).strip()}


def _explicit_suggestion_schema_error(payload: dict[str, Any]) -> str:
    suggested = str(payload.get("suggested_for_rough_cut") or "").strip()
    if suggested != "apply_suggested_split" or str(payload.get("type") or "") != "unit_split_requires_human_review":
        return ""
    summary = payload.get("split_summary") if isinstance(payload.get("split_summary"), dict) else {}
    binding = str(summary.get("binding") or "").strip()
    drop_word_ids = list(summary.get("drop_word_ids") or []) if "drop_word_ids" in summary else None
    keep_word_ids = list(summary.get("keep_word_ids") or []) if "keep_word_ids" in summary else None
    if binding and binding != "whole_word":
        return "TEMPLATE_CANNOT_SUGGEST_DECISION: unit split suggested split does not have whole-word binding"
    if drop_word_ids is not None and keep_word_ids is not None and (not drop_word_ids or not keep_word_ids):
        return "TEMPLATE_CANNOT_SUGGEST_DECISION: unit split suggested split is missing drop/keep word ids"
    return ""


def _explicit_suggested_decision(payload: dict[str, Any], cluster_id: str) -> dict[str, Any] | None:
    suggested = str(payload.get("suggested_for_rough_cut") or "").strip()
    if not suggested:
        return None
    allowed = {str(value).strip() for value in (payload.get("allowed_decisions") or []) if str(value).strip()}
    if suggested not in allowed:
        return None
    return {
        "cluster_id": cluster_id,
        "decision": suggested,
        "reason": f"rough cut closeout: payload suggested {suggested}",
        "confidence": 0.75,
        "requires_human_review": suggested == "requires_human_review",
    }


def _has_invalid_explicit_suggestion(payload: dict[str, Any]) -> bool:
    suggested = str(payload.get("suggested_for_rough_cut") or "").strip()
    if not suggested:
        return False
    allowed = {str(value).strip() for value in (payload.get("allowed_decisions") or []) if str(value).strip()}
    return suggested not in allowed


def _assert_no_physical_decision_fields(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        forbidden = FORBIDDEN_DECISION_OUTPUT_FIELDS & set(row)
        if forbidden:
            raise ValueError(f"SEMANTIC_DECISION_OUTPUT_HAS_PHYSICAL_FIELDS:{sorted(forbidden)}")


def _template_error_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("reason") or "").startswith("TEMPLATE_")]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a V21 semantic decisions template from semantic_request_payloads.json.")
    parser.add_argument("semantic_request_payloads", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--suggest-rough-cut", action="store_true", help="write rough-cut suggested decisions to --output")
    args = parser.parse_args()

    payloads = _read_json(args.semantic_request_payloads)
    if not isinstance(payloads, list):
        raise SystemExit("SEMANTIC_REQUEST_PAYLOADS_MUST_BE_LIST")
    dict_payloads = [row for row in payloads if isinstance(row, dict)]
    if payloads and not dict_payloads:
        raise SystemExit("TEMPLATE_CANNOT_SUGGEST_DECISION: semantic request payload rows must be objects")
    template = build_template(dict_payloads)
    suggested = build_suggested_for_rough_cut(dict_payloads)
    if dict_payloads and not suggested:
        raise SystemExit("TEMPLATE_CANNOT_SUGGEST_DECISION: payload_count>0 decision_count=0")
    _assert_no_physical_decision_fields(template)
    _assert_no_physical_decision_fields(suggested)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(suggested if args.suggest_rough_cut else template, ensure_ascii=False, indent=2), "utf-8")
    suggested_path = args.output.with_name("semantic_decisions.suggested_for_rough_cut.json")
    suggested_path.write_text(json.dumps(suggested, ensure_ascii=False, indent=2), "utf-8")
    if args.suggest_rough_cut:
        error_rows = _template_error_rows(suggested)
        if error_rows:
            raise SystemExit(
                json.dumps(
                    {
                        "code": "TEMPLATE_CANNOT_SUGGEST_DECISION",
                        "errors": [
                            {
                                "cluster_id": str(row.get("cluster_id") or ""),
                                "decision": str(row.get("decision") or ""),
                                "reason": str(row.get("reason") or ""),
                            }
                            for row in error_rows
                        ],
                    },
                    ensure_ascii=False,
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
