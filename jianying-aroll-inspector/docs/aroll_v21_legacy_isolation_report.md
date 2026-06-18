# A-Roll V21 Legacy Isolation Report

Status: PASS.

## V21 Import Graph

Current V21 imports from V20 are read-only helper/gate modules:

```text
aroll_text_normalize
aroll_cjk_short_repeat_gate
aroll_adjacent_modifier_semantic_redundancy_gate
aroll_final_repeat_gate
aroll_hidden_audio_repeat_gate
aroll_safe_cut_boundary_gate
aroll_subtitle_style_integrity_gate
aroll_shared_edit_utils.clone_text_material
```

V21 main flow imports:

```text
engine -> ingest/evidence/decision/compiler/render/writer/validate
operator -> engine
cli -> operator
```

## Forbidden Patch Modules

Static scan found no imports in `src/aroll_v21/` for:

```text
aroll_phase4e_full_aroll
aroll_downstream_repair_pipeline
aroll_repair_applier
aroll_safe_cut_boundary_resolver
material_text_rows
run_downstream_repair_pipeline
apply_repair_proposals
resolve_safe_cut_boundaries
```

## Boundary

V20 entrypoints remain in the repository. They are not called by `run_aroll_v21_operator.ps1` or `src/aroll_v21.cli`.

V21 validators may call V20 read-only gate functions to check output. Validators do not mutate final timeline, captions, or materials.
