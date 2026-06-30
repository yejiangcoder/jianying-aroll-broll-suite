from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aroll_v21.ir.models import RunReport


@dataclass(frozen=True)
class EngineIngestStageResult:
    source_graph: Any
    blockers: list[Any]
    blocked_report: RunReport | None = None


@dataclass(frozen=True)
class EngineDecisionStageResult:
    repeat_clusters: Any
    decision_plan: Any
    blocked_report: RunReport | None = None


@dataclass(frozen=True)
class EngineCompileStageResult:
    final_timeline: list[Any]
    blocked_report: RunReport | None = None


@dataclass(frozen=True)
class EngineQualityStageResult:
    final_timeline: list[Any]
    captions: list[Any]
    visual_pacing_report: dict[str, Any]
    final_visible_repair_report: dict[str, Any]
    quality_mutations: list[dict[str, Any]]


@dataclass(frozen=True)
class EngineWriterStageResult:
    material_write_plan: dict[str, Any]
    blocked_report: RunReport | None = None


@dataclass(frozen=True)
class EngineValidationStageResult:
    validator_report: dict[str, Any]
    validator_blockers: list[Any]


def run_engine_stages(engine: Any, inputs: Any) -> RunReport:
    ingest_stage = engine._run_ingest_stage(inputs)
    if ingest_stage.blocked_report is not None:
        return ingest_stage.blocked_report

    source_graph = ingest_stage.source_graph
    blockers = ingest_stage.blockers
    decision_stage = engine._run_decision_stage(source_graph, blockers)
    if decision_stage.blocked_report is not None:
        return decision_stage.blocked_report

    repeat_clusters = decision_stage.repeat_clusters
    decision_plan = decision_stage.decision_plan
    compile_stage = engine._run_compile_stage(source_graph, repeat_clusters, decision_plan, blockers)
    if compile_stage.blocked_report is not None:
        return compile_stage.blocked_report

    quality_stage = engine._run_quality_stage(
        final_timeline=compile_stage.final_timeline,
        source_graph=source_graph,
        decision_plan=decision_plan,
        blockers=blockers,
    )
    writer_stage = engine._run_writer_stage(
        source_graph=source_graph,
        repeat_clusters=repeat_clusters,
        decision_plan=decision_plan,
        final_timeline=quality_stage.final_timeline,
        captions=quality_stage.captions,
        blockers=blockers,
    )
    if writer_stage.blocked_report is not None:
        return writer_stage.blocked_report

    validation_stage = engine._run_validation_stage(
        inputs=inputs,
        source_graph=source_graph,
        decision_plan=decision_plan,
        final_timeline=quality_stage.final_timeline,
        captions=quality_stage.captions,
        material_write_plan=writer_stage.material_write_plan,
        visual_pacing_report=quality_stage.visual_pacing_report,
        final_visible_repair_report=quality_stage.final_visible_repair_report,
        blockers=blockers,
    )
    return engine._build_final_run_report(
        inputs=inputs,
        source_graph=source_graph,
        repeat_clusters=repeat_clusters,
        decision_plan=decision_plan,
        final_timeline=quality_stage.final_timeline,
        captions=quality_stage.captions,
        material_write_plan=writer_stage.material_write_plan,
        validator_report=validation_stage.validator_report,
        validator_blockers=validation_stage.validator_blockers,
        blockers=blockers,
    )
