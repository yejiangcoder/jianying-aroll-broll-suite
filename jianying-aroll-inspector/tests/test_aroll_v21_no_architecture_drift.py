from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V21_SRC = ROOT / "src" / "aroll_v21"
V21_ENTRY = ROOT / "run_aroll_v21_operator.ps1"


def read_rel(path: str) -> str:
    return (ROOT / path).read_text("utf-8")


def py_text_under(path: Path) -> str:
    if not path.exists():
        return ""
    return "\n".join(file.read_text("utf-8") for file in sorted(path.rglob("*.py")))


def v21_text() -> str:
    return "\n".join([*(path.read_text("utf-8") for path in V21_SRC.rglob("*.py")), V21_ENTRY.read_text("utf-8")])


class ArollV21NoArchitectureDriftTests(unittest.TestCase):
    def test_no_v20_patch_modules_or_patch_entrypoints(self) -> None:
        text = v21_text()
        for token in (
            "aroll_phase4e_full_aroll",
            "aroll_uat_full",
            "aroll_downstream_repair_pipeline",
            "aroll_repair_applier",
            "aroll_safe_cut_boundary_resolver",
            "material_text_rows",
            "run_downstream_repair_pipeline",
            "apply_repair_proposals",
            "resolve_safe_cut_boundaries",
        ):
            self.assertNotIn(token, text)

    def test_no_fixup_or_downstream_style_logic_in_v21(self) -> None:
        text = v21_text().lower()
        for token in ("auto_fix", "fixup", "downstream_repair", "safe_cut_expand", "validator repair", "writer fallback"):
            self.assertNotIn(token, text)

    def test_fallback_mentions_are_only_no_writer_contract_fields_or_block_messages(self) -> None:
        lines = [line.strip() for line in v21_text().splitlines() if "fallback" in line.lower()]
        for line in lines:
            lowered = line.lower()
            self.assertTrue(
                "no_writer_fallback" in lowered
                or "writer_fallback_count" in lowered
                or "without fallback" in lowered
                or "fallback is forbidden" in lowered
                or "fallback_policy" in lowered
                or "fail-closed fallback" in lowered,
                line,
            )

    def test_phase0_governance_lock_documents_current_boundaries(self) -> None:
        architecture = read_rel("ARCHITECTURE.md")
        for token in (
            "PHASE_0_GOVERNANCE_LOCK_ACTIVE",
            "engine.py",
            "quality/pipeline.py",
            "final_visible_caption_repair.py",
            "final_caption_visible_repeat.py",
            "engine_summary.py",
            "quality_gate.py",
            "validators/writeback cannot import repair modules",
            "advisory_only_no_timeline_mutation",
        ):
            self.assertIn(token, architecture)

    def test_engine_does_not_directly_import_final_visible_rule_modules(self) -> None:
        engine = (V21_SRC / "engine.py").read_text("utf-8")

        for token in (
            "quality.final_visible_repair.rules",
            "FinalVisibleRepairContext",
            "FinalVisibleRepairRuleRegistry",
            "TimelineRepairProposal",
            "FinalVisibleRepairTransaction",
        ):
            self.assertNotIn(token, engine)

        for token in (
            "QualityPipeline(",
            "QualityPipelineHooks(",
            "repair_final_visible_caption_issues=repair_final_visible_caption_issues",
        ):
            self.assertIn(token, engine)

    def test_phase1_engine_run_delegates_to_stage_runner(self) -> None:
        engine = (V21_SRC / "engine.py").read_text("utf-8")
        stages = (V21_SRC / "engine_stages.py").read_text("utf-8")
        artifact_manifest = (V21_SRC / "artifact_manifest.py").read_text("utf-8")

        for token in (
            "run_engine_stages",
            "EngineIngestStageResult",
            "EngineDecisionStageResult",
            "EngineCompileStageResult",
            "EngineQualityStageResult",
            "EngineWriterStageResult",
            "EngineValidationStageResult",
        ):
            self.assertIn(token, stages)

        for token in (
            "engine._run_ingest_stage",
            "engine._run_decision_stage",
            "engine._run_compile_stage",
            "engine._run_quality_stage",
            "engine._run_writer_stage",
            "engine._run_validation_stage",
            "engine._build_final_run_report",
        ):
            self.assertIn(token, stages)

        self.assertIn("from aroll_v21.engine_stages import", engine)
        self.assertIn("return run_engine_stages(self, inputs)", engine)
        for token in (
            "class _IngestStageResult",
            "class _DecisionStageResult",
            "class _CompileStageResult",
            "class _QualityStageResult",
            "class _WriterStageResult",
            "class _ValidationStageResult",
            "ingest_stage = self._run_ingest_stage",
            "decision_stage = self._run_decision_stage",
            "compile_stage = self._run_compile_stage",
            "writer_stage = self._run_writer_stage",
        ):
            self.assertNotIn(token, engine)

        self.assertIn("src/aroll_v21/engine_stages.py", artifact_manifest)

    def test_phase2_validation_stage_delegates_to_validation_coordinator(self) -> None:
        engine = (V21_SRC / "engine.py").read_text("utf-8")
        coordinator = (V21_SRC / "engine_validation_coordinator.py").read_text("utf-8")
        architecture = read_rel("ARCHITECTURE.md")
        artifact_manifest = (V21_SRC / "artifact_manifest.py").read_text("utf-8")

        for token in (
            "run_engine_validation_stage",
            "engine.validators.run",
            'validator_report["final_visible_caption_repair_report"] = final_visible_repair_report',
            "engine._attach_final_caption_visible_repeat_gate",
            "engine._merge_final_visible_repeat_semantic_requests",
            "engine._route_final_visible_repeat_semantic_requests",
            "engine._refresh_validator_semantic_gate_after_request_merge",
            "engine._semantic_request_consistency_blockers",
            "engine._validator_blockers",
            "EngineValidationStageResult",
        ):
            self.assertIn(token, coordinator)

        self.assertIn("from aroll_v21.engine_validation_coordinator import run_engine_validation_stage", engine)
        self.assertIn("return run_engine_validation_stage(", engine)
        for token in (
            "validator_report = self.validators.run(",
            'validator_report["final_visible_caption_repair_report"] = final_visible_repair_report',
            "final_visible_semantic_changed = self._merge_final_visible_repeat_semantic_requests",
            "consistency_blockers = self._semantic_request_consistency_blockers(decision_plan, validator_report)",
            "validator_blockers: list[Blocker] = []",
        ):
            self.assertNotIn(token, engine)

        self.assertIn("Phase 2 Validation Coordinator", architecture)
        self.assertIn("src/aroll_v21/engine_validation_coordinator.py", architecture)
        self.assertIn("src/aroll_v21/engine_validation_coordinator.py", artifact_manifest)

    def test_phase3_final_run_report_delegates_to_report_builder(self) -> None:
        engine = (V21_SRC / "engine.py").read_text("utf-8")
        builder = (V21_SRC / "engine_report_builder.py").read_text("utf-8")
        architecture = read_rel("ARCHITECTURE.md")
        artifact_manifest = (V21_SRC / "artifact_manifest.py").read_text("utf-8")

        for token in (
            "build_engine_run_report",
            "blocking_blockers =",
            "semantic_write_allowed =",
            "validator_write_allowed =",
            "writer_fallback_count =",
            "READY_FOR_DISPOSABLE_WRITE_PRE_AUDIT",
            "BlockerReport(",
            "RunReport(",
        ):
            self.assertIn(token, builder)

        self.assertIn("from aroll_v21.engine_report_builder import build_engine_run_report", engine)
        self.assertIn("return build_engine_run_report(", engine)
        for token in (
            "blocking_blockers = [",
            "semantic_write_allowed = bool(decision_plan.semantic_unresolved_count == 0",
            "validator_write_allowed = bool(validator_report.get(\"validator_report_ok\"))",
            "writer_fallback_count = int(material_write_plan.get(\"writer_fallback_count\") or 0)",
            "READY_FOR_DISPOSABLE_WRITE_PRE_AUDIT",
            "BlockerReport(",
            "return RunReport(",
        ):
            self.assertNotIn(token, engine)

        self.assertIn("Phase 3 Run Report Builder", architecture)
        self.assertIn("src/aroll_v21/engine_report_builder.py", architecture)
        self.assertIn("src/aroll_v21/engine_report_builder.py", artifact_manifest)

    def test_validators_and_writeback_do_not_import_repair_modules(self) -> None:
        validator_and_writeback = "\n".join(
            [
                py_text_under(V21_SRC / "validate"),
                py_text_under(V21_SRC / "writeback"),
            ]
        )

        for token in (
            "quality.final_visible_caption_repair",
            "quality.final_visible_repair",
            "repair_final_visible_caption_issues",
            "TimelineRepairProposal",
            "FinalVisibleRepairContext",
            "apply_next_final_timeline_repair_intent",
        ):
            self.assertNotIn(token, validator_and_writeback)

    def test_summary_and_quality_gate_are_report_consumers_not_repair_engines(self) -> None:
        summary_and_gate = "\n".join(
            [
                (V21_SRC / "engine_summary.py").read_text("utf-8"),
                (V21_SRC / "quality" / "quality_gate.py").read_text("utf-8"),
            ]
        )

        for token in (
            "final_visible_caption_repair_report",
            "final_visible_repair_success",
            "blocker_codes",
            "gate_passed",
        ):
            self.assertIn(token, summary_and_gate)

        for token in (
            "from aroll_v21.quality.final_visible_repair",
            "repair_final_visible_caption_issues",
            "TimelineRepairProposal",
            "FinalVisibleRepairContext",
            "apply_next_final_timeline_repair_intent",
            "QualityPipeline(",
        ):
            self.assertNotIn(token, summary_and_gate)

    def test_final_caption_visible_repeat_keeps_detector_classifier_policy_gate_boundary(self) -> None:
        repeat_entry = (V21_SRC / "quality" / "final_caption_visible_repeat.py").read_text("utf-8")

        for token in (
            "FinalCaptionVisibleDetectorSet",
            "build_final_caption_visible_gate_report",
            "detect_final_caption_visible_evidence",
            "classify_final_caption_visible_evidence",
            "build_final_caption_visible_policy",
            "build_final_caption_visible_repair_signal",
        ):
            self.assertIn(token, repeat_entry)

        for token in (
            "repair_final_visible_caption_issues",
            "TimelineRepairProposal",
            "FinalVisibleRepairContext",
            "QualityPipeline(",
        ):
            self.assertNotIn(token, repeat_entry)

    def test_final_caption_visible_repeat_has_explicit_quality_layers(self) -> None:
        root = V21_SRC / "quality" / "final_caption_visible"
        for name in ("detector.py", "classifier.py", "policy.py", "repair_signal.py", "gate.py"):
            self.assertTrue((root / name).exists(), name)
        entry = (V21_SRC / "quality" / "final_caption_visible_repeat.py").read_text("utf-8")
        for token in (
            "detect_final_caption_visible_evidence",
            "classify_final_caption_visible_evidence",
            "build_final_caption_visible_policy",
            "build_final_caption_visible_repair_signal",
            "build_final_caption_visible_gate_report",
        ):
            self.assertIn(token, entry)
        policy = (root / "policy.py").read_text("utf-8")
        for verdict in ("BLOCKER_FATAL", "REPAIRABLE_FATAL", "WARNING", "ALLOW", "HUMAN_REVIEW"):
            self.assertIn(verdict, policy)

    def test_phase4_final_visible_repair_report_aggregation_lives_in_report_builder(self) -> None:
        root = V21_SRC / "quality" / "final_visible_repair"
        entry = (V21_SRC / "quality" / "final_visible_caption_repair.py").read_text("utf-8")
        report_builder = (root / "report_builder.py").read_text("utf-8")
        architecture = read_rel("ARCHITECTURE.md")

        for token in (
            "build_final_visible_caption_repair_report",
            "final_visible_repair_enabled",
            "final_visible_repair_transaction_rule_names",
            "pre_visible_semantic_junk_repair_action_count",
            "repeated_island_repair_action_count",
            "boundary_restart_repair_action_count",
            "timeline_repair_proposal_action_count",
            "final_timeline_repair_intent_action_count",
            "caption_only_materialized_merge_count",
            "final_visible_recheck_required_count",
        ):
            self.assertIn(token, report_builder)

        self.assertIn("from aroll_v21.quality.final_visible_repair.report_builder import build_final_visible_caption_repair_report", entry)
        self.assertIn("report = build_final_visible_caption_repair_report(", entry)
        for token in (
            "semantic_junk_actions = [",
            "boundary_restart_actions = [",
            "repeated_island_actions = [",
            "timeline_repair_proposal_actions = [",
            "transaction_actions = [",
            "\"final_visible_repair_enabled\": True",
            "\"pre_visible_semantic_junk_repair_action_count\": len(semantic_junk_actions)",
            "\"boundary_restart_repair_action_count\": len(boundary_restart_actions)",
            "def _repeated_island_confidence_count",
        ):
            self.assertNotIn(token, entry)

        self.assertIn("Phase 4 Final-Visible Repair Report Builder", architecture)
        self.assertIn("src/aroll_v21/quality/final_visible_repair/report_builder.py", architecture)

    def test_phase5_final_visible_repair_main_loop_lives_in_loop_runner(self) -> None:
        root = V21_SRC / "quality" / "final_visible_repair"
        entry = (V21_SRC / "quality" / "final_visible_caption_repair.py").read_text("utf-8")
        loop_runner = (root / "loop_runner.py").read_text("utf-8")
        architecture = read_rel("ARCHITECTURE.md")

        for token in (
            "FinalVisibleRepairLoopRunResult",
            "run_final_visible_repair_loop",
            "rule_registry.transaction_rules",
            "rule_registry.proposal_transaction_rules",
            "rule_registry.open_tail_transaction_rules",
            "rule_registry.tail_proposal_transaction_rules",
            "build_gate_candidate_repair_rules",
            "no_safe_deterministic_repair_available",
            "consume_pipeline_result",
            "run_final_visible_repair_pipeline_once",
        ):
            self.assertIn(token, loop_runner)

        self.assertIn("from aroll_v21.quality.final_visible_repair.loop_runner import run_final_visible_repair_loop", entry)
        self.assertIn("loop_run_result = run_final_visible_repair_loop(", entry)
        self.assertIn("passes_executed = loop_run_result.passes_executed", entry)
        for token in (
            "for pass_index in range(max_pass_limit):",
            "transaction_result = run_final_visible_repair_pipeline_once(",
            "proposal_result = run_final_visible_repair_pipeline_once(",
            "open_tail_result = run_final_visible_repair_pipeline_once(",
            "tail_proposal_result = run_final_visible_repair_pipeline_once(",
            "gate_candidate_result = run_final_visible_repair_pipeline_once(",
            "rule_registry.proposal_transaction_rules",
            "rule_registry.open_tail_transaction_rules",
            "rule_registry.tail_proposal_transaction_rules",
            "build_gate_candidate_repair_rules(",
        ):
            self.assertNotIn(token, entry)

        self.assertIn("Phase 5 Final-Visible Repair Loop Runner", architecture)
        self.assertIn("src/aroll_v21/quality/final_visible_repair/loop_runner.py", architecture)

    def test_phase6_final_visible_repair_post_loop_lives_in_post_loop_runner(self) -> None:
        root = V21_SRC / "quality" / "final_visible_repair"
        entry = (V21_SRC / "quality" / "final_visible_caption_repair.py").read_text("utf-8")
        post_loop_runner = (root / "post_loop_runner.py").read_text("utf-8")
        architecture = read_rel("ARCHITECTURE.md")

        for token in (
            "FinalVisibleRepairPostLoopResult",
            "run_final_visible_repair_post_loop",
            "rule_registry.residual_transaction_rules",
            "rule_registry.caption_only_finalizer_rules",
            "recompute_final_timeline_safe_handles",
            "repair_context.repair_state_signature",
            "consume_pipeline_result",
            "run_final_visible_repair_pipeline_once",
        ):
            self.assertIn(token, post_loop_runner)

        self.assertIn(
            "from aroll_v21.quality.final_visible_repair.post_loop_runner import run_final_visible_repair_post_loop",
            entry,
        )
        self.assertIn("post_loop_result = run_final_visible_repair_post_loop(", entry)
        self.assertIn("loop_state = post_loop_result.loop_state", entry)
        for token in (
            "residual_result = run_final_visible_repair_pipeline_once(",
            "for caption_only_finalizer_rule in rule_registry.caption_only_finalizer_rules:",
            "final_safe_handle_result = recompute_final_timeline_safe_handles(",
            "rule_registry.residual_transaction_rules",
            "rule_registry.caption_only_finalizer_rules",
            "recompute_final_timeline_safe_handles",
            "run_final_visible_repair_pipeline_once",
        ):
            self.assertNotIn(token, entry)

        self.assertIn("Phase 6 Final-Visible Repair Post-Loop Runner", architecture)
        self.assertIn("src/aroll_v21/quality/final_visible_repair/post_loop_runner.py", architecture)

    def test_final_visible_repair_has_transaction_pipeline_seed(self) -> None:
        root = V21_SRC / "quality" / "final_visible_repair"
        context = (root / "context.py").read_text("utf-8")
        pipeline = (root / "pipeline.py").read_text("utf-8")
        loop_runner = (root / "loop_runner.py").read_text("utf-8")
        post_loop_runner = (root / "post_loop_runner.py").read_text("utf-8")
        proposal_apply = (root / "proposal_apply.py").read_text("utf-8")
        registry = (root / "registry.py").read_text("utf-8")
        loop_state = (root / "loop_state.py").read_text("utf-8")
        entry = (V21_SRC / "quality" / "final_visible_caption_repair.py").read_text("utf-8")
        leading = (root / "rules" / "leading_filler.py").read_text("utf-8")
        word_span = (root / "rules" / "word_span_edit.py").read_text("utf-8")
        caption_fragment = (root / "rules" / "caption_fragment.py").read_text("utf-8")
        final_repeat_caption = (root / "rules" / "final_repeat_caption.py").read_text("utf-8")
        connector = (root / "rules" / "connector_intrusion.py").read_text("utf-8")
        short_residual = (root / "rules" / "short_residual.py").read_text("utf-8")
        pre_visible = (root / "rules" / "pre_visible_semantic_junk.py").read_text("utf-8")
        source_boundary = (root / "rules" / "source_boundary_prefix.py").read_text("utf-8")
        restart_repeat = (root / "rules" / "restart_repeat.py").read_text("utf-8")
        caption_only_merge = (root / "rules" / "caption_only_merge.py").read_text("utf-8")
        for token in (
            "source_graph",
            "render_captions",
            "repair_state_signature",
        ):
            self.assertIn(token, context)
        for token in (
            "FinalVisibleRepairTransaction",
            "FinalVisibleRepairRuleOutcome",
            "FinalVisibleRepairPipelineResult",
            "ProposalRepairRule",
            "StepRepairRule",
            "run_final_visible_repair_pipeline_once",
            "unresolved_rule_name",
        ):
            self.assertIn(token, pipeline)
        for token in (
            "FinalVisibleRepairLoopState",
            "consume_pipeline_result",
        ):
            self.assertIn(token, loop_state)
        self.assertIn("FinalVisibleRepairLoopState", entry)
        for token in (
            "consume_pipeline_result",
        ):
            self.assertIn(token, loop_runner)
            self.assertIn(token, post_loop_runner)
        for token in (
            "FinalVisibleRepairRuleCallbacks",
            "build_final_visible_repair_rule_registry",
        ):
            self.assertIn(token, registry)
            self.assertIn(token, entry)
        self.assertIn("build_gate_candidate_repair_rules", registry)
        self.assertIn("build_gate_candidate_repair_rules", loop_runner)
        self.assertIn("FinalVisibleRepairRuleRegistry", registry)
        for token in (
            "CaptionOnlyFinalizerRule",
            "FinalVisibleRepairRuleOutcome",
        ):
            self.assertIn(token, caption_only_merge)
        self.assertIn("CaptionOnlyFinalizerRule", registry)
        self.assertNotIn("run_final_visible_repair_pipeline_once", entry)
        self.assertIn("run_final_visible_repair_pipeline_once", loop_runner)
        self.assertIn("run_final_visible_repair_pipeline_once", post_loop_runner)
        self.assertIn("rule_registry.proposal_transaction_rules", loop_runner)
        self.assertIn("rule_registry.open_tail_transaction_rules", loop_runner)
        self.assertIn("rule_registry.tail_proposal_transaction_rules", loop_runner)
        self.assertIn("rule_registry.caption_only_finalizer_rules", post_loop_runner)
        for token in (
            "RenderCallbackAdapter",
            "apply_timeline_repair_proposal_as_step",
            "build_caption_span_drop_proposal",
            "repair_boundary_restart_with_proposal",
            "repair_repeated_island_with_proposal",
            "proposal_unresolved",
            "proposal_action",
        ):
            self.assertIn(token, proposal_apply)
        for token in (
            "repair_contained_short_fragment_with_proposal",
            "repair_self_repair_aborted_phrase_with_proposal",
            "repair_short_aborted_prefix_caption_with_proposal",
            "repair_open_tail_short_caption_with_next",
            "repair_fatal_tiny_caption_with_proposal",
            "short_aborted_prefix_candidate",
            "open_tail_short_caption_should_merge",
            "COMMON_CLOSED_DE_PHRASES",
        ):
            self.assertIn(token, caption_fragment)
        self.assertIn("_caption_fragment_rules.repair_contained_short_fragment_with_proposal", entry)
        self.assertIn("_caption_fragment_rules.repair_self_repair_aborted_phrase_with_proposal", entry)
        self.assertIn("_caption_fragment_rules.repair_short_aborted_prefix_caption_with_proposal", entry)
        self.assertIn("_caption_fragment_rules.repair_open_tail_short_caption_with_next", entry)
        self.assertIn("_caption_fragment_rules.repair_fatal_tiny_caption_with_proposal", entry)
        self.assertIn("partial(", entry)
        for token in (
            "repair_caption_level_final_repeat_aborted_containment",
            "final_repeat_caption_rows",
            "caption_level_final_repeat_aborted_drop_caption_id",
            "caption_level_containment_match",
            "relaxed_containment_text",
            "final_target_repeat_caption_containment",
        ):
            self.assertIn(token, final_repeat_caption)
        self.assertIn(
            "_final_repeat_caption_rules.repair_caption_level_final_repeat_aborted_containment",
            entry,
        )
        self.assertIn("LeadingFillerGapRule", registry)
        for token in (
            "ConnectorSingleWordIntrusionRule",
            "ConnectorFillerRestartRule",
            "RepeatedObjectHeadTailRule",
            "SubjectPrefixCompletedPredicateRestartRule",
        ):
            self.assertIn(token, connector)
            self.assertIn(token, registry)
        self.assertIn("ShortRepairResidualRule", short_residual)
        self.assertIn("ShortRepairResidualRule", registry)
        for token in (
            "PreVisibleSemanticJunkCandidateRule",
            "IsolatedSemanticJunkCaptionRule",
        ):
            self.assertIn(token, pre_visible)
            self.assertIn(token, registry)
        for token in (
            "OmittedLegalReduplicationRule",
            "SourceBoundaryPrefixGapRule",
            "SourceBoundaryCompoundSuffixRule",
            "SourceBoundaryTruncatedCompoundTailRule",
        ):
            self.assertIn(token, source_boundary)
            self.assertIn(token, registry)
        self.assertIn("GateCandidateRepairRule", restart_repeat)
        self.assertIn("GateCandidateRepairRule", registry)
        self.assertNotIn("_configure_final_visible_rule_modules", entry)
        self.assertNotIn(".configure_rule_dependencies", entry)
        for rule_path in sorted((root / "rules").glob("*.py")):
            rule_text = rule_path.read_text("utf-8")
            self.assertNotIn("configure_rule_dependencies", rule_text, rule_path.name)
            self.assertNotIn("globals().update", rule_text, rule_path.name)

        for token in (
            "_segment_with_word_ids",
            "_drop_contiguous_word_ids_from_timeline",
            "_safe_merge_segments",
        ):
            self.assertIn(token, word_span)
        for token in (
            "class _RenderCallbackAdapter",
            "def _repair_boundary_restart_with_proposal",
            "def _repair_repeated_island_with_proposal",
            "def _caption_span_drop_proposal",
            "def _apply_caption_span_drop_proposal",
            "def _repair_contained_short_fragment_with_proposal",
            "def _repair_self_repair_aborted_phrase_with_proposal",
            "def _repair_short_aborted_prefix_caption_with_proposal",
            "def _repair_open_tail_short_caption_with_next",
            "def _repair_fatal_tiny_caption_with_proposal",
            "def _short_aborted_prefix_candidate",
            "def _open_tail_short_caption_should_merge",
            "TimelineRepairProposal(",
            "build_tiny_caption_classification_report",
            "build_final_repeat_gate_report",
            "def _repair_caption_level_final_repeat_aborted_containment",
            "def _final_repeat_caption_rows",
            "def _caption_level_final_repeat_aborted_drop_caption_id",
            "def _caption_level_containment_match",
            "def _relaxed_containment_text",
            "CONTAINED_SHORT_FRAGMENT_OPEN_TAIL_CHARS",
            "OPEN_TAIL_SHORT_CAPTION_MAX_CHARS",
            "SHORT_ABORTED_PREFIX_MAX_CHARS",
            "COMMON_CLOSED_DE_PHRASES",
            "connector_intrusion_step =",
            "connector_restart_step =",
            "repeated_object_head_step =",
            "subject_prefix_restart_step =",
            "residual_step = _repair_short_repair_residual_segments",
            "pre_semantic_junk_step =",
            "omitted_reduplication_step =",
            "source_prefix_step =",
            "compound_step =",
            "truncated_tail_step =",
            "junk_step =",
            "step = _repair_next_issue(",
            "open_tail_merge_step =",
            "actions.append(",
            "repeated_island_step,",
            "boundary_restart_step,",
            "containment_fragment_step,",
            "self_repair_step,",
            "short_aborted_prefix_step,",
            "tiny_residual_step,",
            "final_caption_only_actions =",
            "subject_prefix_caption_actions =",
            "same_subtitle_short_tail_actions =",
        ):
            self.assertNotIn(token, entry)

    def test_engine_quality_stage_delegates_to_quality_pipeline(self) -> None:
        engine = (V21_SRC / "engine.py").read_text("utf-8")
        quality_pipeline = (V21_SRC / "quality" / "pipeline.py").read_text("utf-8")

        for token in (
            "class QualityPipelineHooks",
            "class QualityPipelineResult",
            "class QualityPipeline",
            "def run(",
            "repair_final_visible_caption_issues",
            "recompute_final_timeline_safe_handles",
        ):
            self.assertIn(token, quality_pipeline)

        for token in (
            "QualityPipeline(",
            "QualityPipelineHooks(",
            "repair_final_visible_caption_issues=repair_final_visible_caption_issues",
        ):
            self.assertIn(token, engine)

        for token in (
            "max_final_visible_repair_cycles = 8",
            "repair_cycle_state_repeated",
            "visual_pacing_reintroduced_seen_repair_state",
            "post_cleanup_visual_pacing_reintroduced_seen_repair_state",
        ):
            self.assertNotIn(token, engine)

    def test_final_timeline_quality_guard_uses_unified_fact_intent_apply_gate_layers(self) -> None:
        quality_root = V21_SRC / "quality"
        fact = (quality_root / "final_timeline_quality_guard.py").read_text("utf-8")
        intent = (quality_root / "final_timeline_repair_intent.py").read_text("utf-8")
        apply = (quality_root / "final_timeline_repair_apply.py").read_text("utf-8")
        gate = (quality_root / "quality_gate.py").read_text("utf-8")
        validators = (V21_SRC / "validate" / "validators.py").read_text("utf-8")
        engine_validation = (V21_SRC / "engine_validation.py").read_text("utf-8")
        repair_entry = (quality_root / "final_visible_caption_repair.py").read_text("utf-8")
        repair_registry = (quality_root / "final_visible_repair" / "registry.py").read_text("utf-8")
        artifacts = (V21_SRC / "artifact_manifest.py").read_text("utf-8")

        for token in (
            "build_final_timeline_quality_guard_report",
            "PHYSICAL_BLOCKING_CANDIDATE_TYPES",
            "caption_video_word_text_mismatch",
            "blocking_candidates",
        ):
            self.assertIn(token, fact)
        for token in (
            "build_final_timeline_repair_intent_report",
            "source_words_are_authoritative",
            "drop_restart_residue_segment",
            "trim_dangling_words_before_connector",
            "recompute_missing_lead_handle",
        ):
            self.assertIn(token, intent)
        for token in (
            "apply_next_final_timeline_repair_intent",
            "_recompute_safe_handles",
            "render_captions",
            "is_visual_gap_split",
        ):
            self.assertIn(token, apply)
        for token in (
            "final_timeline_quality_guard_gate",
            "V21_FINAL_TIMELINE_QUALITY_GUARD_FAILED",
        ):
            self.assertIn(token, gate)
            self.assertIn(token, engine_validation)
        self.assertIn("final_timeline_quality_guard.get(\"gate_passed\")", validators)
        self.assertIn("final_timeline_quality_intent.apply_next", repair_registry)
        self.assertIn("apply_next_final_timeline_repair_intent", repair_entry)
        self.assertIn("final_timeline_quality_guard_report.json", artifacts)
        self.assertIn("final_timeline_quality_guard_report.json", (V21_SRC / "engine_artifacts.py").read_text("utf-8"))

        self.assertLess(
            repair_registry.index("final_timeline_quality_intent.apply_next"),
            repair_registry.index("LeadingFillerGapRule"),
        )


if __name__ == "__main__":
    unittest.main()
