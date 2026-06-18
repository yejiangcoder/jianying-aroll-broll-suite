# A-Roll V21 Phase 3 Report

Status: IDEA-side entry/gating contract implemented. Real UAT not run.

## Entry

`run_aroll_v21_operator.ps1` now calls `src/aroll_v21.cli`, which delegates to `src/aroll_v21.operator`.

Supported modes:

- `dry-run`
- `write`
- `verify-only`

## Artifacts

Each run writes:

- `source_graph.json`
- `edit_units.json`
- `repeat_clusters.json`
- `decision_plan.json`
- `deepseek_decisions.json`
- `local_policy_decisions.json`
- `final_timeline.json`
- `final_edl.json`
- `captions.json`
- `canonical_caption_template.json`
- `material_write_plan.json`
- `validator_report.json`
- `postwrite_report.json`
- `blocker_report.json`
- `decision_trace.json`
- `run_summary.json`

## Commit Gate

`write` mode first runs prewrite validation. If prewrite fails, write is blocked.

In the IDEA-safe runner, real draft writeback/decrypt is not connected. Therefore:

- normal `write` blocks with `postwrite_mode=unavailable`
- `write -SimulateWrite` is report-only and does not commit
- `verify-only` requires supplied postwrite materials; otherwise it blocks

`commit_performed` remains false in IDEA tests.

## Required Metrics

`run_summary.json` includes:

- `single_source_graph_ok`
- `all_final_segments_have_word_ids`
- `all_captions_derived_from_final_timeline`
- `all_materials_from_canonical_template`
- `no_writer_fallback`
- `validators_readonly`
- `final_repeat_count`
- `hidden_audio_repeat_count`
- `cut_inside_word_count`
- `partial_multichar_cut_count`
- `giant_subtitle_count`
- `template_fingerprint_mismatch_count`
- `content_schema_error_count`
- `caption_coverage_gap_count`
- `prewrite_style_gate_ok`
- `postwrite_style_gate_ok`
- `postwrite_decrypt_ok`
- `commit_only_after_all_validators`

## Real UAT

Not run in IDEA. No claim of real UAT pass is made.
