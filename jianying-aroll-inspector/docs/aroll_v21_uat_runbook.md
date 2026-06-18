# A-Roll V21 UAT Runbook

IDEA Codex only runs offline gates. Desktop Codex owns real Jianying UAT.

## V21 Entry

`run_aroll_v21_operator.ps1` is the V21-only entry. It does not call V20 Phase4E or downstream repair.

```powershell
.\run_aroll_v21_operator.ps1 `
  -InputJson path\to\v21_input.json `
  -RunDir path\to\run_dir `
  -Mode dry-run
```

Real draft dry-run with an explicit external word timeline:

```powershell
.\run_aroll_v21_operator.ps1 `
  -DraftDir path\to\disposable\draft `
  -RunDir path\to\run_dir `
  -Mode dry-run `
  -JyDraftc path\to\jy-draftc.exe `
  -WordTimelineJson path\to\word_timeline.json
```

Modes:

- `dry-run`: compile and validate V21 artifacts, no draft write.
- `write`: requires prewrite validators to pass. In the IDEA-safe runner, real write/decrypt backend is not connected, so non-simulated write blocks with `postwrite_mode=unavailable`.
- `verify-only`: requires supplied postwrite material JSON. Without actual postwrite material input, it blocks with `ACTUAL_POSTWRITE_DECRYPT_UNAVAILABLE`.

For test-only simulation:

```powershell
.\run_aroll_v21_operator.ps1 `
  -InputJson path\to\v21_input.json `
  -RunDir path\to\run_dir `
  -Mode write `
  -SimulateWrite
```

This writes reports only and does not commit.

The offline runner writes:

- `source_graph.json`
- `edit_units.json`
- `repeat_clusters.json`
- `decision_plan.json`
- `semantic_request_payloads.json`
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

## Real UAT Boundary

Real draft ingest, backup, decrypt/encrypt, postwrite decrypt, and commit are Desktop-only until the V21 real draft backend is explicitly connected. If actual decrypt is unavailable, V21 must block and report `postwrite_mode=unavailable`; it must not claim real UAT pass.

If V21 blocks, fix V21 source graph, decision plan, compiler, subtitle renderer, writer, or validators. Do not add V20 downstream repair patches.

Current conditional status:

- Real draft decrypt/read is connected for dry-run ingest.
- V21 accepts native `text_materials[*].words` only when rows satisfy word-level schema and timing.
- Native word timing can be absolute source time, target timeline time, or relative-to-subtitle time when it can be mapped through text/source segments. Missing timing still blocks.
- The real draft adapter passes normalized `text_materials` into the native word provider; inspect `word_timeline_provider.draft_native.selected_path` to confirm whether words came from raw `materials.texts[]` or normalized text materials.
- V21 supports explicit external `word_timeline.json`.
- V21 must not fabricate words from subtitles or sentences.
- If semantic planning is required but DeepSeek is not configured, inspect `semantic_request_payloads.json` and `decision_trace.json`.
- Unresolved semantic clusters do not stop dry-run discovery, but they set `write_allowed=false`, `requires_human_review=true`, and `semantic_unresolved_count>0`. Write mode must block.
- If writer blocks with `CAPTION_TEMPLATE_NOT_FOUND`, inspect `material_write_plan.json.template_report.rejection_summary` and `sample_rejections`. Candidate selection is based on subtitle/material/segment relation plus safe fingerprint grouping, not fallback to arbitrary text material.
- `run_aroll_v21_operator.ps1` is the only V21 entry. V20 production wrappers and Phase4/Phase4E scripts are not part of the active source tree.
