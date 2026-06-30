from __future__ import annotations

from typing import Any

from aroll_v21.ir.models import BlockerReport, RunReport


def build_engine_run_report(
    *,
    inputs: Any,
    source_graph: Any,
    repeat_clusters: Any,
    decision_plan: Any,
    final_timeline: list[Any],
    captions: list[Any],
    material_write_plan: dict[str, Any],
    validator_report: dict[str, Any],
    validator_blockers: list[Any],
    blockers: list[Any],
) -> RunReport:
    blocking_blockers = [
        blocker
        for blocker in blockers
        if blocker.severity == "fatal" or (inputs.mode == "write" and blocker.severity == "write_blocker")
    ]
    semantic_write_allowed = bool(decision_plan.semantic_unresolved_count == 0 and decision_plan.write_allowed)
    semantic_adjudication_report = decision_plan.semantic_adjudication_report or {}
    validator_write_allowed = bool(validator_report.get("validator_report_ok")) and not any(
        blocker.severity == "fatal" for blocker in validator_blockers
    )
    writer_fallback_count = int(material_write_plan.get("writer_fallback_count") or 0)
    ready_for_write = bool(
        semantic_write_allowed
        and validator_write_allowed
        and writer_fallback_count == 0
        and not blocking_blockers
    )
    blocker_report = BlockerReport(
        blocked=bool(blocking_blockers),
        blockers=blockers,
        summary={
            "mode": inputs.mode,
            "speech_timeline_provider": str(inputs.ingest_metadata.get("speech_timeline_provider") or ""),
            "speech_timeline_granularity": str(inputs.ingest_metadata.get("speech_timeline_granularity") or ""),
            "speech_timeline_precision": str(inputs.ingest_metadata.get("speech_timeline_precision") or ""),
            "speech_timeline_can_cut_inside_caption": bool(inputs.ingest_metadata.get("speech_timeline_can_cut_inside_caption")),
            "word_timeline_count": int(inputs.ingest_metadata.get("word_timeline_count") or len(source_graph.words)),
            "single_source_graph_ok": source_graph.invariant_report.single_source_graph_ok,
            "all_final_segments_have_word_ids": all(bool(segment.word_ids) for segment in final_timeline),
            "all_captions_derived_from_final_timeline": bool(
                validator_report.get("subtitle_coverage_validator", {}).get("all_captions_derived_from_final_timeline")
            ),
            "all_materials_from_canonical_template": bool(material_write_plan.get("canonical_caption_template_id")),
            "no_writer_fallback": bool(material_write_plan.get("no_writer_fallback")),
            "writer_fallback_count": writer_fallback_count,
            "semantic_unresolved_count": decision_plan.semantic_unresolved_count,
            "semantic_adjudication_gate_passed": bool(semantic_adjudication_report.get("semantic_adjudication_gate_passed")),
            "semantic_request_count": int(semantic_adjudication_report.get("semantic_request_count") or 0),
            "semantic_request_unresolved_count": int(semantic_adjudication_report.get("semantic_request_unresolved_count") or 0),
            "fatal_semantic_issue_count": int(semantic_adjudication_report.get("fatal_semantic_issue_count") or 0),
            "deepseek_provider_configured": bool(semantic_adjudication_report.get("deepseek_provider_configured")),
            "deepseek_provider_called_count": int(semantic_adjudication_report.get("deepseek_provider_called_count") or 0),
            "deepseek_provider_error": str(semantic_adjudication_report.get("deepseek_provider_error") or ""),
            "deepseek_batch_enabled": bool(semantic_adjudication_report.get("deepseek_batch_enabled")),
            "deepseek_batch_request_count": int(semantic_adjudication_report.get("deepseek_batch_request_count") or 0),
            "deepseek_batch_attempt_count": int(semantic_adjudication_report.get("deepseek_batch_attempt_count") or 0),
            "deepseek_batch_retry_count": int(semantic_adjudication_report.get("deepseek_batch_retry_count") or 0),
            "deepseek_batch_issue_count": int(semantic_adjudication_report.get("deepseek_batch_issue_count") or 0),
            "deepseek_batch_resolved_count": int(semantic_adjudication_report.get("deepseek_batch_resolved_count") or 0),
            "deepseek_batch_unresolved_count": int(semantic_adjudication_report.get("deepseek_batch_unresolved_count") or 0),
            "deepseek_batch_missing_issue_ids": list(semantic_adjudication_report.get("deepseek_batch_missing_issue_ids") or []),
            "deepseek_batch_error": str(semantic_adjudication_report.get("deepseek_batch_error") or ""),
            "commit_reused_semantic_cache": bool(semantic_adjudication_report.get("commit_reused_semantic_cache")),
            "semantic_cache_input_hash": str(semantic_adjudication_report.get("semantic_cache_input_hash") or ""),
            "semantic_cache_issue_count": int(semantic_adjudication_report.get("semantic_cache_issue_count") or 0),
            "semantic_cache_resolved_count": int(semantic_adjudication_report.get("semantic_cache_resolved_count") or 0),
            "semantic_cache_unresolved_count": int(semantic_adjudication_report.get("semantic_cache_unresolved_count") or 0),
            "deepseek_provider_skipped_count": int(semantic_adjudication_report.get("deepseek_provider_skipped_count") or 0),
            "deepseek_provider_skipped_reasons": dict(semantic_adjudication_report.get("deepseek_provider_skipped_reasons") or {}),
            "semantic_decision_cache_used": bool(semantic_adjudication_report.get("semantic_decision_cache_used")),
            "semantic_auto_route_count": int(semantic_adjudication_report.get("semantic_auto_route_count") or 0),
            "semantic_local_decision_count": int(semantic_adjudication_report.get("semantic_local_decision_count") or 0),
            "semantic_provider_required_count": int(semantic_adjudication_report.get("semantic_provider_required_count") or 0),
            "deterministic_baseline_refused_count": int(semantic_adjudication_report.get("deterministic_baseline_refused_count") or 0),
            "requires_human_review": decision_plan.requires_human_review,
            "semantic_write_allowed": semantic_write_allowed,
            "validator_write_allowed": validator_write_allowed,
            "write_allowed": ready_for_write,
            "ready_for_write": ready_for_write,
            "READY_FOR_DISPOSABLE_WRITE_PRE_AUDIT": ready_for_write,
            "dry_run_continued_for_discovery": bool(
                inputs.mode == "dry-run" and decision_plan.dry_run_continued_for_discovery and final_timeline
            ),
        },
    )
    return RunReport(
        status="blocked" if blocking_blockers else "ok",
        source_graph=source_graph,
        repeat_clusters=repeat_clusters,
        decision_plan=decision_plan,
        final_timeline=final_timeline,
        captions=captions,
        material_write_plan=material_write_plan,
        validator_report=validator_report,
        postwrite_report=validator_report.get("postwrite_material_validator") or {},
        blocker_report=blocker_report,
        decision_trace=decision_plan.decision_trace,
    )
