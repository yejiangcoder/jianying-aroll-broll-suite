# Jianying A-Roll Inspector

Phase 1 A-Roll read-only draft structure inspector.

This tool inspects a prepared Jianying draft and reports whether it is safe to proceed to an A-Roll EDL rewrite phase.

## Scope

This tool only does:

- Decrypt the target timeline `draft_content.json` into `runtime/`.
- Read video/audio/text/filter track structure.
- Export `subtitle_timeline.json`.
- Export `aroll_inspect_report.json`.
- Decide `can_aroll_rewrite`.

This tool does not:

- Write back to any Jianying draft.
- Call `encrypt()`.
- Call DeepSeek.
- Generate EDL.
- Modify video/text/audio/filter tracks.
- Modify `D:\video tools\jianying-ai-image-aligner`.

## Run

```powershell
cd "D:\video tools\jianying-aroll-inspector"
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
  -MainMaterialPath "D:\video\raw.mp4"
```

If `-DraftDir` is not provided, the runner will try to read:

```text
D:\video tools\jianying-ai-image-aligner\agent_inputs.json
```

## Output

Each run writes a timestamped directory:

```text
D:\video tools\jianying-aroll-inspector\runtime\aroll_inspect_YYYYMMDD_HHMMSS\
```

Files:

```text
draft_content.dec.json
aroll_inspect_report.json
subtitle_timeline.json
```

## Conservative Failures

`can_aroll_rewrite` becomes `false` when the inspector detects:

- Timeline ID mismatch.
- Duplicate timeline IDs in `timeline_layout.json`.
- No readable subtitle track.
- Main video track missing or ambiguous.
- Existing `AI_BROLL` or photo-heavy B-Roll.
- Non-1.0x speed, curve speed, reverse, or source/target duration mismatch.
- Independent audio that cannot be proven to be the main source.
- Complex filter/effect tracks or unrecognized attached effect refs.

## Open Source Export Notice

This repository contains source code only.

Runtime artifacts, Jianying drafts, media files, generated images, local configs, cookies, and API keys are not included.

Configure local runtime paths with environment variables or example config files.
