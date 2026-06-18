# Jianying A-Roll Inspector

A-Roll draft inspection and production tooling for Jianying drafts.

## Scope

`run_aroll_inspect.ps1` / `src/aroll_inspect.py` are read-only. Inspect decrypts the target timeline into an external runtime directory, reads video/audio/text/filter structure, exports `subtitle_timeline.json` and `aroll_inspect_report.json`, and decides `can_aroll_rewrite`.

Inspect does not write back to any Jianying draft, call `encrypt()`, call DeepSeek, generate EDL, or modify video/text/audio/filter tracks.

Operator/UAT/Phase4E are the writeback chain. They are production execution paths and may back up, rewrite, encrypt, and write draft files after gates pass. Real UAT and writeback are Desktop Codex responsibilities, not IDEA Codex responsibilities.

## Codex Roles

IDEA Codex is for precise code edits, lightweight tests, and small gate fixes. It must not open real drafts, scan runtime directories, run real UAT, call `encrypt()`, or write `draft_content.json` / `template-2.tmp`.

Desktop Codex is responsible for real Jianying UAT, long-running local execution, worktree maintenance, packaging, runtime cleanup execution, and production writeback.

## Inspect Run

```powershell
.\run_aroll_inspect.ps1 -DraftDir "EDIT_ME_DRAFT_DIR"
```

Optional main-track hints:

```powershell
.\run_aroll_inspect.ps1 `
  -DraftDir "EDIT_ME_DRAFT_DIR" `
  -MainVideoTrackIndex 0
```

```powershell
.\run_aroll_inspect.ps1 `
  -DraftDir "EDIT_ME_DRAFT_DIR" `
  -MainMaterialPath "EDIT_ME_RAW_VIDEO_PATH"
```

If `-DraftDir` is not provided, the runner only reads agent inputs when `-InputJson` is explicitly provided or `JY_ALIGNER_ROOT` points to an aligner checkout containing `agent_inputs.json`.

## Runtime

Runtime output is external by default and resolved through `AUTO_CLIP_AROLL_RUNS_DIR`, `AUTO_CLIP_RUNTIME_DIR`, or `config/runtime_paths*.yaml`. Project-local `runtime/` remains ignored only as a historical safety net.

Inspect writes a timestamped directory named:

```text
aroll_inspect_YYYYMMDD_HHMMSS
```

Files:

```text
draft_content.dec.json
aroll_inspect_report.json
subtitle_timeline.json
```

## Conservative Failures

`can_aroll_rewrite` becomes `false` when inspect detects:

- Timeline ID mismatch.
- Duplicate timeline IDs in `timeline_layout.json`.
- No readable subtitle track.
- Main video track missing or ambiguous.
- Existing `AI_BROLL` or photo-heavy B-Roll.
- Unsupported speed, curve speed, reverse, or source/target duration mismatch.
- Independent audio that cannot be proven to be the main source.
- Complex filter/effect tracks or unrecognized attached effect refs.
