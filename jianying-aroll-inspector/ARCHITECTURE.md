# A-Roll V21 Architecture Baseline

Status: `PHASE_0_GOVERNANCE_LOCK_ACTIVE`

Date: 2026-06-30

This document freezes the current architecture shape before the next refactor
wave. It is a governance baseline, not a feature specification.

## Active Entry

The active V21 production entry is:

```text
run_aroll_v21_operator.ps1
-> src/aroll_v21.cli
-> src/aroll_v21.operator.run_operator
-> src/aroll_v21.engine.ArollEngine.run
-> src/aroll_v21.engine_stages.run_engine_stages
```

The operator owns runtime boundary checks, real draft ingest, dry-run/write
mode selection, semantic provider construction, artifact writing, and writeback
commit orchestration.

`engine_stages.run_engine_stages` owns the in-memory editing stage order:

```text
ingest/source graph
-> repeat evidence
-> semantic decision plan
-> final timeline compile
-> quality mutation passes
-> captions
-> material write plan
-> read-only validators
-> blocker/report summary
```

`ArollEngine` still owns stage implementations and helper state. `run()` is a
thin entry that delegates to the stage runner.

## Current Quality Chain

The current quality chain is behaviorally stable but still too centralized.

Implemented layers:

- `ReadOnlyValidators` builds quality gates without mutating timeline, captions,
  or material write plans.
- `final_caption_visible` has explicit detector, classifier, policy, repair
  signal, gate, and semantic arbitration surfaces.
- `final_visible_repair` has an explicit context and transaction pipeline.
- Quality mutations record before/after signatures and can reject regressions.
- DeepSeek and other semantic providers are limited to semantic decisions.
- Final-visible repeat provider output is advisory only and does not mutate the
  final timeline.

Remaining centralization:

- `src/aroll_v21/engine.py` is still the largest orchestration object.
- `ArollEngine` still owns stage implementations, semantic helper methods, and
  quality hook wiring.
- `src/aroll_v21/quality/final_visible_caption_repair.py` still combines entry,
  dispatcher, aggregation, and historical repair glue.
- `src/aroll_v21/quality/final_caption_visible_repeat.py` still contains many
  detector families in one module.
- `quality_gate.py` and `engine_summary.py` still act as broad report-field
  buses.

## Phase 0 Governance Lock

Phase 0 does not migrate logic or change quality rules. It locks the current
known-good boundaries so later cleanup cannot turn into another patch pile.

Current cleanup targets:

1. `src/aroll_v21/engine.py` remains the broad run orchestrator, but quality
   pass sequencing must stay in `src/aroll_v21/quality/pipeline.py`.
2. `src/aroll_v21/quality/final_visible_caption_repair.py` remains the public
   repair entry and historical glue, but rule execution must stay in the
   registry, pipeline, proposal-apply, context, and rule modules.
3. `src/aroll_v21/quality/final_caption_visible_repeat.py` still assembles the
   detector family, but detector, classifier, policy, repair-signal, gate, and
   semantic-arbitration surfaces must stay explicit.
4. `src/aroll_v21/engine_summary.py` and
   `src/aroll_v21/quality/quality_gate.py` are report buses only; they must not
   become repair or decision engines.

Locked boundaries:

- `engine.py` may inject `QualityPipelineHooks`, but must not import
  `final_visible_repair.rules` or repair transaction internals.
- validators/writeback cannot import repair modules.
- summary/gate code cannot import repair proposal, context, or timeline
  mutation APIs.
- DeepSeek and other semantic providers remain
  `advisory_only_no_timeline_mutation` for final-visible repeat.
- `final_visible_repair/rules/*.py` cannot use dependency injection through
  `configure_rule_dependencies` or `globals().update(...)`.
- real draft writes are out of scope for architecture cleanup.

Phase 0 verification commands:

```powershell
py -3 -m pytest tests/test_aroll_v21_no_architecture_drift.py tests/test_aroll_v21_no_drift.py tests/test_aroll_v21_no_drift_allowlist.py tests/test_aroll_v21_no_v20_patch_imports.py tests/test_aroll_v21_static_hidden_bug_scan.py -q
py -3 -m pytest -q
git diff --check
```

## Phase 1 Engine Stage Runner

Status: `COMPLETE`

Phase 1 moves only the top-level run-stage ordering out of `engine.py` and
into:

```text
src/aroll_v21/engine_stages.py
```

The new module owns:

- stage result data carriers
- ingest/decision/compile/quality/writer/validation/summary order
- early return when a stage produces a blocked report

`ArollEngine.run()` now delegates to `run_engine_stages(self, inputs)`.
`ArollEngine` still owns the stage methods, quality hook wiring, semantic
helpers, and report construction helpers.

Behavior boundary:

- no quality rule changes
- no semantic-provider changes
- no validator/writeback repair
- no real draft writes

Architecture guard:

- `tests/test_aroll_v21_no_architecture_drift.py` asserts that stage ordering
  lives in `engine_stages.py` and does not drift back into `ArollEngine.run`.
- `artifact_manifest.py` includes `engine_stages.py` in `code_version_hash` so
  runner changes are visible to artifact reuse checks.

## Phase 2 Validation Coordinator

Status: `COMPLETE`

Phase 2 moves validation-stage orchestration out of `engine.py` and into:

```text
src/aroll_v21/engine_validation_coordinator.py
```

The new module owns:

- `ReadOnlyValidators.run` invocation
- final-visible repair report attachment to validator output
- final caption visible repeat gate attachment
- final-visible semantic request merge and route refresh
- semantic consistency blocker aggregation
- validator blocker aggregation

`ArollEngine._run_validation_stage()` now delegates to
`run_engine_validation_stage(self, ...)`. The existing semantic helper methods
and validator blocker helpers remain on `ArollEngine` for compatibility with
current tests and debug seams.

Behavior boundary:

- no validator rule changes
- no semantic-provider decision changes
- no final timeline or caption mutation
- no writeback repair

Architecture guard:

- `tests/test_aroll_v21_no_architecture_drift.py` asserts that validation
  orchestration lives in `engine_validation_coordinator.py` and does not drift
  back into `_run_validation_stage`.
- `artifact_manifest.py` includes `engine_validation_coordinator.py` in
  `code_version_hash`.

## Phase 3 Run Report Builder

Status: `COMPLETE`

Phase 3 moves final `RunReport` and `BlockerReport` construction out of
`engine.py` and into:

```text
src/aroll_v21/engine_report_builder.py
```

The new module owns:

- blocking blocker selection
- semantic/write/validator readiness booleans
- blocker report summary fields
- final `RunReport` construction

`ArollEngine._build_final_run_report()` now delegates to
`build_engine_run_report(...)`. `engine_summary.py` remains the artifact
summary layer for `run_summary.json`; this phase only moves the in-memory
`RunReport` assembly out of the engine.

Behavior boundary:

- no summary field changes
- no ready/write gate changes
- no blocker severity changes
- no artifact schema changes beyond including this module in the code hash

Architecture guard:

- `tests/test_aroll_v21_no_architecture_drift.py` asserts that final report
  construction lives in `engine_report_builder.py` and does not drift back into
  `_build_final_run_report`.
- `artifact_manifest.py` includes `engine_report_builder.py` in
  `code_version_hash`.

## Phase 4 Final-Visible Repair Report Builder

Status: `COMPLETE`

Phase 4 starts reducing `final_visible_caption_repair.py` by moving final
repair report aggregation into:

```text
src/aroll_v21/quality/final_visible_repair/report_builder.py
```

The new module owns:

- action-family counts for semantic junk, repeated island, boundary restart,
  proposals, final timeline intents, and transactions
- final visible repair success/count/blocker report fields
- caption-only materialization report fields
- pre-visible semantic junk report enrichment

`repair_final_visible_caption_issues()` still owns the repair loop, final gate
calculation, unresolved-state decision, and result construction. No detector,
rule, transaction, or safe-handle behavior moves in this phase.

Behavior boundary:

- no rule execution order changes
- no detector/classifier/policy changes
- no safe-cut or safe-handle recompute changes
- no report field shape changes

Architecture guard:

- `tests/test_aroll_v21_no_architecture_drift.py` asserts that final-visible
  repair report aggregation lives in `report_builder.py` and does not drift
  back into `final_visible_caption_repair.py`.

## Phase 5 Final-Visible Repair Loop Runner

Status: `COMPLETE`

Phase 5 moves the main final-visible repair loop ordering out of
`final_visible_caption_repair.py` and into:

```text
src/aroll_v21/quality/final_visible_repair/loop_runner.py
```

The new module owns:

- transaction rule pass
- proposal transaction pass
- open-tail transaction pass
- tail-proposal transaction pass
- gate-candidate fallback pass
- no-safe-deterministic-repair unresolved row emission for the main loop

`repair_final_visible_caption_issues()` still owns context construction, rule
registry construction, final gates, and result assembly.

Behavior boundary:

- no rule execution order changes
- no candidate/gate condition changes
- no residual or caption-only finalizer changes
- no safe-handle recompute changes

Architecture guard:

- `tests/test_aroll_v21_no_architecture_drift.py` asserts that the main loop
  ordering lives in `loop_runner.py` and does not drift back into
  `final_visible_caption_repair.py`.

## Phase 6 Final-Visible Repair Post-Loop Runner

Status: `COMPLETE`

Phase 6 moves the final-visible repair post-loop finalization out of
`final_visible_caption_repair.py` and into:

```text
src/aroll_v21/quality/final_visible_repair/post_loop_runner.py
```

The new module owns:

- residual transaction pass
- caption-only finalizer pass order
- final safe-handle recompute
- post-safe-handle signature refresh

`repair_final_visible_caption_issues()` still owns context construction, rule
registry construction, final gate calculation, unresolved-state decision,
report construction, and result construction.

Behavior boundary:

- no residual transaction rule changes
- no caption-only finalizer rule changes
- no safe-handle recompute condition changes
- no final gate or report field changes

Architecture guard:

- `tests/test_aroll_v21_no_architecture_drift.py` asserts that post-loop
  finalization lives in `post_loop_runner.py` and does not drift back into
  `final_visible_caption_repair.py`.

## Non-Negotiable Boundaries

- Do not import or revive V20 patch orchestration.
- Do not add symptom-specific production phrases to source code.
- Do not let validators repair.
- Do not let writeback repair.
- Do not let writer fallback create captions.
- Do not let DeepSeek return or apply physical edit fields.
- Do not mutate real Jianying drafts during architecture work.
- Do not add another direct final-timeline rewrite path outside a recorded
  quality mutation or repair transaction.

## Timeline Mutation Policy

Every pass that can change `final_timeline` or `captions` must expose:

- input timeline/caption signature
- output timeline/caption signature
- action rows
- accepted/rejected state
- rejection reason
- whether a downstream quality recheck is required

The next refactor wave should move scattered quality-pass sequencing out of
`ArollEngine.run` and into a dedicated `QualityPipeline`.

## Semantic Provider Policy

Semantic providers may classify or adjudicate semantic ambiguity. They must not
directly decide physical edit boundaries.

Final-visible repeat advisory fields currently include:

- `final_visible_repeat_advisory_count`
- `final_visible_repeat_advisory_result_count`
- `final_visible_repeat_advisory_decision_counts`
- `final_visible_repeat_advisory_keep_count`
- `final_visible_repeat_advisory_drop_candidate_count`
- `final_visible_repeat_advisory_review_count`
- `final_visible_repeat_advisory_unresolved_count`
- `final_visible_repeat_advisory_applied_count`
- `final_visible_repeat_advisory_provider_called_count`
- `final_visible_repeat_advisory_policy`

The required policy value is:

```text
advisory_only_no_timeline_mutation
```

## Historical Phase 0 Dirty Baseline

This section records the initial 2026-06-29 dirty baseline. It is historical
trace only; current cleanliness must be checked with `git status`.

Before this document was added, the behavior changes from the latest quality
architecture phases were local and uncommitted.

Tracked files modified:

```text
src/aroll_v21/engine.py
src/aroll_v21/engine_summary.py
src/aroll_v21/quality/boundary_overlap.py
src/aroll_v21/quality/final_caption_visible/__init__.py
src/aroll_v21/quality/final_caption_visible/gate.py
src/aroll_v21/quality/final_caption_visible_repeat.py
src/aroll_v21/quality/final_visible_repeat_classification.py
src/aroll_v21/quality/quality_gate.py
tests/test_aroll_v21_quality_gates.py
tests/test_aroll_v21_repeat_gate_classification.py
tests/test_aroll_v21_semantic_request_consistency_gate.py
```

Untracked implementation file:

```text
src/aroll_v21/quality/final_caption_visible/semantic_arbitration.py
```

## Verification Baseline

Phase 0 verification commands:

```powershell
python -m pytest tests/test_aroll_v21_no_architecture_drift.py tests/test_aroll_v21_no_drift.py tests/test_aroll_v21_no_drift_allowlist.py tests/test_aroll_v21_no_v20_patch_imports.py -q
python -m pytest -q
git diff --check
```

Expected result:

- architecture drift tests pass
- full test suite passes
- no whitespace errors
- runtime-path warnings are acceptable when runtime env vars are unset

## Next Refactor Order

1. Split `ArollEngine.run` into explicit stage orchestration.
2. Move quality sequencing into `QualityPipeline`.
3. Complete final-visible repair dispatcher cleanup.
4. Split final-visible repeat detector families.
5. Replace broad report dictionaries with registered report schemas.
6. Add Python project tooling and refresh stale docs.
7. Build a durable quality case fixture library.

## Phase 1 Progress

Status: `COMPLETE`

`ArollEngine.run` is now a stage orchestration function instead of the full
pipeline body. It delegates to:

```text
_run_ingest_stage
_run_decision_stage
_run_compile_stage
_run_quality_stage
_run_writer_stage
_run_validation_stage
_build_final_run_report
```

The refactor is behavior-preserving. It does not introduce new quality rules,
change edit decisions, or write real drafts.

Known remaining stage-2 target:

- `_run_quality_stage` still owns the large quality-pass sequence. It should be
  split into a dedicated `QualityPipeline` next.

Verification:

```text
python -m compileall -q src tests tools
python -m pytest tests/test_aroll_v21_no_architecture_drift.py tests/test_aroll_v21_no_drift.py tests/test_aroll_v21_no_drift_allowlist.py tests/test_aroll_v21_no_v20_patch_imports.py tests/test_aroll_v21_static_hidden_bug_scan.py -q
python -m pytest tests/test_aroll_v21_semantic_request_consistency_gate.py tests/test_aroll_v21_quality_gates.py tests/test_aroll_v21_final_backend_integration_contract.py tests/test_aroll_v21_final_failure_path_matrix.py -q
python -m pytest -q
git diff --check
```

## Phase 2 Progress

Status: `COMPLETE`

The quality-pass sequence has moved out of `ArollEngine` and into:

```text
src/aroll_v21/quality/pipeline.py
```

The new module owns:

- `QualityPipelineHooks`
- `QualityPipelineResult`
- `QualityPipeline`
- `QualityPipeline.run`

`ArollEngine._run_quality_stage` now only wires dependencies into
`QualityPipelineHooks` and delegates to `QualityPipeline.run`. The old
`aroll_v21.engine.repair_final_visible_caption_issues` import is intentionally
kept as a compatibility injection point for existing tests and future controlled
repair substitution; the quality sequence itself remains in the pipeline.

Behavior boundary:

- no new quality rules
- no edit-decision changes
- no real draft writes
- no validator or writer repair
- no DeepSeek physical edit application

Architecture guard:

- `tests/test_aroll_v21_no_architecture_drift.py` now asserts that quality
  sequencing stays in `quality/pipeline.py` and does not drift back into
  `engine.py`.

Verification:

```text
python -m compileall -q src tests tools
python -m pytest tests/test_aroll_v21_no_architecture_drift.py tests/test_aroll_v21_no_drift.py tests/test_aroll_v21_no_drift_allowlist.py tests/test_aroll_v21_no_v20_patch_imports.py tests/test_aroll_v21_static_hidden_bug_scan.py -q
python -m pytest tests/test_aroll_v21_semantic_request_consistency_gate.py tests/test_aroll_v21_quality_gates.py tests/test_aroll_v21_final_backend_integration_contract.py tests/test_aroll_v21_final_failure_path_matrix.py -q
python -m pytest -q
git diff --check
```

Known remaining stage-3 target:

- `final_visible_caption_repair.py` still combines entry, dispatcher,
  aggregation, and historical repair glue. It should be reduced to a thin
  dispatcher over the existing final-visible repair transaction pipeline.

## Phase 3 Progress

Status: `COMPLETE`

The final-visible repair entry has been reduced by moving dispatcher-owned
state and rule registration into dedicated modules:

```text
src/aroll_v21/quality/final_visible_repair/loop_state.py
src/aroll_v21/quality/final_visible_repair/registry.py
```

`loop_state.py` owns:

- current timeline/caption/signature state
- seen-signature tracking
- accepted action accumulation
- unresolved repair rows
- pipeline-result consumption

`registry.py` owns:

- `FinalVisibleRepairRuleCallbacks`
- `FinalVisibleRepairRuleRegistry`
- deterministic transaction rule ordering
- proposal rule ordering
- open-tail and residual rule groups
- caption-only finalizer rule groups
- gate-candidate repair rule construction

`final_visible_caption_repair.py` still owns the public repair entry and the
historical repair helper functions, but it no longer embeds the rule-list
construction or the pipeline-result state machine.

Behavior boundary:

- no new quality rules
- no sample-specific phrase handling
- no rule ordering changes
- no real draft writes
- no validator or writer repair

Architecture guard:

- `tests/test_aroll_v21_no_architecture_drift.py` now asserts that final-visible
  repair rules are registered through `registry.py`, loop mutation is consumed
  through `loop_state.py`, and old `globals().update` / rule dependency
  configuration does not return.

Verification:

```text
python -m py_compile src\aroll_v21\quality\final_visible_caption_repair.py src\aroll_v21\quality\final_visible_repair\registry.py src\aroll_v21\quality\final_visible_repair\loop_state.py tests\test_aroll_v21_no_architecture_drift.py
python -m pytest tests/test_aroll_v21_no_architecture_drift.py tests/test_aroll_v21_no_drift.py tests/test_aroll_v21_no_drift_allowlist.py tests/test_aroll_v21_static_hidden_bug_scan.py -q
python -m pytest tests/test_aroll_v21_quality_gates.py tests/test_aroll_v21_final_visible_generic_qc_regressions.py tests/test_aroll_v21_jimei_qc_regressions_round12.py tests/test_aroll_v21_repeat_gate_classification.py -q
```

Known remaining stage-4 target:

- `final_visible_caption_repair.py` still contains many historical helper
  aliases and local repair functions. The next cleanup should move one helper
  family at a time into owned rule modules while keeping the registry order
  unchanged.

## Phase 4 Progress

Status: `COMPLETE`

The final-visible proposal materialization layer has moved out of
`final_visible_caption_repair.py` and into:

```text
src/aroll_v21/quality/final_visible_repair/proposal_apply.py
```

The new module owns:

- render callback adaptation for timeline proposal materialization
- proposal materialization into `_RepairStep`
- unresolved proposal rows
- proposal action rows and coverage summaries
- caption span-drop proposal construction
- boundary restart proposal repair application
- repeated island proposal repair application

The repair entry still owns the public orchestration and the remaining
historical helper families, but it no longer embeds boundary/repeated proposal
apply wrappers or duplicated span-drop materialization/report construction.

Behavior boundary:

- no detector or classifier condition changes
- no proposal ordering changes
- no action/report field shape changes
- no sample-specific phrase handling
- no real draft writes

Architecture guard:

- `tests/test_aroll_v21_no_architecture_drift.py` now asserts that proposal
  apply helpers live in `proposal_apply.py` and do not drift back into
  `final_visible_caption_repair.py`.

Verification:

```text
python -m py_compile src\aroll_v21\quality\final_visible_caption_repair.py src\aroll_v21\quality\final_visible_repair\proposal_apply.py tests\test_aroll_v21_no_architecture_drift.py
python -m pytest tests/test_aroll_v21_no_architecture_drift.py tests/test_aroll_v21_boundary_restart_repair.py tests/test_aroll_v21_repeated_island_repair.py tests/test_aroll_v21_quality_integration_gate.py -q
python -m pytest tests/test_aroll_v21_quality_gates.py::ArollV21QualityGateTests::test_final_visible_repair_keeps_progressive_semantic_expansion tests/test_aroll_v21_quality_gates.py::ArollV21QualityGateTests::test_final_visible_repair_trims_repeated_short_discourse_opener -q
```

Known remaining stage-5 target:

- Move the next isolated helper family out of `final_visible_caption_repair.py`,
  preferably open-tail / short-aborted caption proposal helpers, while keeping
  the registry order unchanged.

## Phase 5 Progress

Status: `COMPLETE`

The short caption fragment repair family has moved out of
`final_visible_caption_repair.py` and into:

```text
src/aroll_v21/quality/final_visible_repair/rules/caption_fragment.py
```

The new module owns:

- contained short fragment proposal repair
- self-repair aborted phrase proposal repair
- short-aborted-prefix caption proposal repair
- open-tail short caption merge repair
- short-aborted prefix candidate classification
- open-tail merge eligibility checks
- contained-fragment drop selection
- the family-specific constants for short/open-tail caption handling

The repair entry still wires this family through `FinalVisibleRepairRuleRegistry`
callbacks. Open-tail repair receives
`render_captions_preserving_caption_only_materializations` as an explicit
callback so the existing caption-only materialization behavior is preserved
without importing the public entry module from a rule module.

Behavior boundary:

- no detector or classifier condition changes
- no proposal ordering changes
- no caption render behavior changes
- no action/report field shape changes
- no sample-specific phrase handling
- no real draft writes

Architecture guard:

- `tests/test_aroll_v21_no_architecture_drift.py` now asserts that the caption
  fragment family lives in `rules/caption_fragment.py`, that the repair entry
  only wires it through `_caption_fragment_rules`, and that the old local helper
  functions/constants do not drift back into `final_visible_caption_repair.py`.

Verification:

```text
python -m py_compile src\aroll_v21\quality\final_visible_caption_repair.py src\aroll_v21\quality\final_visible_repair\rules\caption_fragment.py tests\test_aroll_v21_no_architecture_drift.py
python -m pytest tests/test_aroll_v21_no_architecture_drift.py tests/test_aroll_v21_static_hidden_bug_scan.py -q
python -m pytest tests/test_aroll_v21_quality_integration_gate.py tests/test_aroll_v21_quality_gates.py::ArollV21QualityGateTests::test_final_visible_repair_trims_repeated_short_discourse_opener tests/test_aroll_v21_quality_gates.py::ArollV21QualityGateTests::test_final_visible_repair_trims_repeated_short_discourse_opener_inside_merged_segment tests/test_aroll_v21_quality_gates.py::ArollV21QualityGateTests::test_final_visible_repair_keeps_restart_lead_after_internal_prefix_fragment -q
```

Known remaining stage-6 target:

- Move the next bounded helper family out of `final_visible_caption_repair.py`,
  likely fatal tiny caption proposal repair or caption-level final-repeat
  aborted containment, while preserving the current registry order.

## Phase 6 Progress

Status: `COMPLETE`

Fatal tiny caption proposal repair has moved out of
`final_visible_caption_repair.py` and into the caption fragment rule family:

```text
src/aroll_v21/quality/final_visible_repair/rules/caption_fragment.py
```

The caption fragment module now owns:

- fatal tiny caption classification lookup
- tiny-caption residual proposal construction
- tiny-caption residual proposal application through `proposal_apply.py`
- the existing contained-fragment, self-repair-aborted, short-aborted-prefix,
  and open-tail short-caption repairs from phase 5

The repair entry still wires the callback through `FinalVisibleRepairRuleRegistry`
but no longer imports `TimelineRepairProposal`, `build_tiny_caption_classification_report`,
or a local tiny-residual proposal apply helper.

Behavior boundary:

- no tiny-caption classifier changes
- no proposal ordering changes
- no action/report field shape changes
- no sample-specific phrase handling
- no real draft writes

Architecture guard:

- `tests/test_aroll_v21_no_architecture_drift.py` now asserts that fatal tiny
  caption repair lives in `rules/caption_fragment.py`, that the repair entry
  only wires it through `_caption_fragment_rules`, and that the old local
  implementation/import shape does not drift back into
  `final_visible_caption_repair.py`.

Verification:

```text
python -m py_compile src\aroll_v21\quality\final_visible_caption_repair.py src\aroll_v21\quality\final_visible_repair\rules\caption_fragment.py tests\test_aroll_v21_no_architecture_drift.py
python -m pytest tests/test_aroll_v21_no_architecture_drift.py tests/test_aroll_v21_static_hidden_bug_scan.py -q
python -m pytest tests/test_aroll_v21_quality_integration_gate.py::test_final_visible_repairs_fatal_tiny_caption_residual_through_proposal tests/test_aroll_v21_boundary_restart_repair.py::test_boundary_restart_repair_trims_previous_suffix_and_keeps_next_complete -q
```

Known remaining stage-7 target:

- Move caption-level final-repeat aborted containment helpers into a dedicated
  final-repeat caption repair module, keeping `_repair_next_issue` and registry
  ordering unchanged.

## Phase 7 Progress

Status: `COMPLETE`

Caption-level final-repeat aborted containment repair has moved out of
`final_visible_caption_repair.py` and into:

```text
src/aroll_v21/quality/final_visible_repair/rules/final_repeat_caption.py
```

The new module owns:

- caption rows used by `build_final_repeat_gate_report`
- aborted containment drop-caption selection
- relaxed containment matching
- final-target-repeat caption containment repair dispatch

The repair entry still wires the callback through `FinalVisibleRepairRuleRegistry`
but no longer imports `build_final_repeat_gate_report` or contains the
caption-level final-repeat helper functions.

Behavior boundary:

- no final-repeat detector changes
- no `_repair_next_issue` changes
- no registry ordering changes
- no action/report field shape changes
- no sample-specific phrase handling
- no real draft writes

Architecture guard:

- `tests/test_aroll_v21_no_architecture_drift.py` now asserts that
  caption-level final-repeat containment logic lives in
  `rules/final_repeat_caption.py`, that the repair entry only wires it through
  `_final_repeat_caption_rules`, and that the old local helper functions/imports
  do not drift back into `final_visible_caption_repair.py`.

Verification:

```text
python -m py_compile src\aroll_v21\quality\final_visible_caption_repair.py src\aroll_v21\quality\final_visible_repair\rules\final_repeat_caption.py tests\test_aroll_v21_no_architecture_drift.py
python -m pytest tests/test_aroll_v21_no_architecture_drift.py tests/test_aroll_v21_static_hidden_bug_scan.py -q
python -m pytest tests/test_aroll_v21_quality_gates.py::ArollV21QualityGateTests::test_final_visible_repair_drops_caption_level_aborted_final_repeat_containment -q
```

Known remaining stage-8 target:

- Continue reducing `final_visible_caption_repair.py` by moving the next
  bounded helper family, likely semantic-integrity repair or gate-candidate
  dispatch helpers, without changing `_repair_next_issue` ordering.
