from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deepseek_client import (
    DEFAULT_CONFIG,
    extract_json_object,
    extract_message_content,
    load_deepseek_config,
    post_chat_completions,
)
from aroll_semantic_arbiter_prompt import build_semantic_arbiter_messages
from aroll_semantic_arbiter_schema import normalize_arbiter_result, summarize_arbiter_results


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def _chunks(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[i : i + size] for i in range(0, len(rows), size)]


def arbitrate_suspicious_units(
    suspicious_units: list[dict[str, Any]],
    run_dir: Path,
    *,
    model: str = "deepseek-chat",
    config_path: Path = DEFAULT_CONFIG,
    batch_size: int = 12,
    max_failures: int = 3,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    request_rows: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    config = load_deepseek_config(config_path)
    failures = 0
    call_count = 0
    for batch_index, batch in enumerate(_chunks(suspicious_units, batch_size), start=1):
        payload = {
            "model": model,
            "temperature": 0.0,
            "max_tokens": 6000,
            "response_format": {"type": "json_object"},
            "messages": build_semantic_arbiter_messages(batch),
        }
        public_payload = dict(payload)
        public_payload["messages"] = payload["messages"]
        request_rows.append({"batch_index": batch_index, "unit_count": len(batch), "payload": public_payload})
        try:
            response = post_chat_completions(config, payload, timeout_sec=240)
            call_count += 1
            content, meta = extract_message_content(response)
            parsed = extract_json_object(content)
            raw_rows.append(
                {
                    "batch_index": batch_index,
                    "meta": meta,
                    "content_char_count": len(content),
                    "parsed": parsed,
                }
            )
            parsed_results = parsed.get("results") or parsed.get("candidates") or parsed.get("units") or []
            if isinstance(parsed_results, dict):
                parsed_results = [parsed_results]
            by_id = {str(row.get("candidate_id") or row.get("unit_id") or ""): row for row in parsed_results if isinstance(row, dict)}
            for unit in batch:
                raw = by_id.get(str(unit.get("candidate_id") or unit.get("unit_id") or ""), {})
                if not raw:
                    raw = {
                        "candidate_id": unit.get("candidate_id") or unit.get("unit_id"),
                        "classification": "codex_self_review_required",
                        "approved_action": "self_review",
                        "covered_by_final": False,
                        "should_block_write": True,
                        "confidence": "low",
                        "reason": "model did not return this unit",
                    }
                normalized = normalize_arbiter_result(raw)
                normalized["source_text"] = unit.get("source_text")
                normalized["source_subtitle_indices"] = unit.get("source_subtitle_indices")
                normalized["candidate_reason"] = unit.get("candidate_reason")
                normalized["candidate_type"] = unit.get("candidate_type")
                normalized["proposed_action"] = unit.get("proposed_action")
                results.append(normalized)
        except Exception as exc:
            failures += 1
            raw_rows.append({"batch_index": batch_index, "error": str(exc), "error_redacted": True})
            if failures >= max_failures:
                raise RuntimeError(f"DEEPSEEK_SEMANTIC_ARBITER_FAILED:{failures}:{exc}") from exc
            for unit in batch:
                results.append(
                    normalize_arbiter_result(
                        {
                            "candidate_id": unit.get("candidate_id") or unit.get("unit_id"),
                            "classification": "codex_self_review_required",
                            "approved_action": "self_review",
                            "covered_by_final": False,
                            "should_block_write": True,
                            "confidence": "low",
                            "reason": f"arbiter call failed: {exc}",
                        }
                    )
                    | {
                        "source_text": unit.get("source_text"),
                        "source_subtitle_indices": unit.get("source_subtitle_indices"),
                        "candidate_reason": unit.get("candidate_reason"),
                        "candidate_type": unit.get("candidate_type"),
                        "proposed_action": unit.get("proposed_action"),
                    }
                )
    report = summarize_arbiter_results(results, llm_used=True, model=model, call_count=call_count)
    write_json(run_dir / "semantic_llm_arbiter_requests.json", request_rows)
    write_json(run_dir / "semantic_llm_arbiter_raw_response.json", raw_rows)
    write_json(run_dir / "semantic_llm_arbiter_results.json", results)
    lines = [
        "# Semantic LLM Arbiter",
        "",
        f"- llm_used: true",
        f"- model: {model}",
        f"- call_count: {call_count}",
        f"- suspicious_unit_count: {len(suspicious_units)}",
        f"- true_missing_required_count: {report['true_missing_required_count']}",
        f"- self_review_required_count: {report['self_review_required_count']}",
        f"- api_key_leaked: false",
        "",
        "## Results",
    ]
    for row in results:
        lines.append(
            f"- {row.get('candidate_id') or row.get('unit_id')}: {row.get('classification')} {row.get('confidence')} "
            f"covered={row.get('covered_by_final')} text={row.get('source_text')} reason={row.get('reason')}"
        )
    (run_dir / "semantic_llm_arbiter_report.md").write_text("\n".join(lines) + "\n", "utf-8")
    return results, report
