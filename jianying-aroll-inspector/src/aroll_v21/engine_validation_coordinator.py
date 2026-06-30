from __future__ import annotations

from typing import Any

from aroll_v21.engine_stages import EngineValidationStageResult


def run_engine_validation_stage(
    engine: Any,
    *,
    inputs: Any,
    source_graph: Any,
    decision_plan: Any,
    final_timeline: list[Any],
    captions: list[Any],
    material_write_plan: dict[str, Any],
    visual_pacing_report: dict[str, Any],
    final_visible_repair_report: dict[str, Any],
    blockers: list[Any],
) -> EngineValidationStageResult:
    validator_report = engine.validators.run(
        source_graph=source_graph,
        decision_plan=decision_plan,
        final_timeline=final_timeline,
        captions=captions,
        material_write_plan=material_write_plan,
        visual_pacing_report=visual_pacing_report,
        postwrite_materials=inputs.postwrite_materials,
        postwrite_mode=inputs.postwrite_mode,
    )
    validator_report["final_visible_caption_repair_report"] = final_visible_repair_report
    validator_report = engine._attach_final_caption_visible_repeat_gate(validator_report, captions)
    final_visible_semantic_changed = engine._merge_final_visible_repeat_semantic_requests(decision_plan, validator_report)
    if engine._route_final_visible_repeat_semantic_requests(decision_plan):
        final_visible_semantic_changed = True
    if final_visible_semantic_changed:
        engine._refresh_semantic_adjudication_report(decision_plan)
        engine._refresh_validator_semantic_gate_after_request_merge(validator_report, decision_plan)
    consistency_blockers = engine._semantic_request_consistency_blockers(decision_plan, validator_report)
    if consistency_blockers:
        blockers.extend(consistency_blockers)
        decision_plan.blockers.extend(consistency_blockers)
    validator_blockers = []
    if not validator_report.get("validator_report_ok"):
        validator_blockers = engine._validator_blockers(validator_report)
        blockers.extend(validator_blockers)
    return EngineValidationStageResult(
        validator_report=validator_report,
        validator_blockers=validator_blockers,
    )
