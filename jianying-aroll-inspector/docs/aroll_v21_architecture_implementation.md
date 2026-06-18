# A-Roll V21 Architecture Implementation

V21 introduces an independent `src/aroll_v21/` compiler path. It does not replace the V20 operator yet.

## Chain

```text
Draft Ingest
-> Canonical Source Graph
-> Candidate Evidence
-> Semantic Decision Plan
-> Final Timeline Compiler
-> Subtitle Renderer
-> Jianying Material Writer
-> Read-only Validators
-> Postwrite Verification
-> CommitOrBlock
```

## Implemented Boundaries

- `ir/models.py` defines the single intermediate representation.
- `ingest/source_graph.py` binds words, subtitles, source segments, and text materials.
- `evidence/repeat_cluster_builder.py` emits evidence only; it does not edit EDL.
- `decision/semantic_decision_planner.py` accepts only unit-level decisions. Physical fields from DeepSeek are blockers.
- `compiler/final_timeline_compiler.py` generates final timeline once from `DecisionPlan`.
- `render/subtitle_renderer.py` derives captions only from final timeline word ids.
- `writer/caption_material_writer.py` uses one canonical caption template and refuses fallback.
- `validate/validators.py` runs read-only validators and reports blockers.

## Current Scope

This is the first V21 compiler skeleton with production contracts and offline tests. It is not wired to real draft writeback in IDEA. Real UAT remains a Desktop responsibility.
