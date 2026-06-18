# jianying-aroll-broll-suite

Local-first Jianying / CapCut automation suite for A-Roll rough-cut editing and B-Roll AI image alignment.

The repository is organized around two maintained subprojects:

- `jianying-aroll-inspector`: A-Roll v21 inspection, semantic decision, quality-gate, and draft writeback tooling.
- `jianying-ai-image-aligner`: B-Roll image alignment v0.2, which writes AI image clips into a prepared draft from a `visual_slot_plan`.

No production media, private drafts, generated images, runtime folders, or credentials are included.

## Current Workflow

1. Prepare a Jianying / CapCut draft with source video and subtitles.
2. Run A-Roll v21 from `jianying-aroll-inspector`.
3. QC the A-Roll result before downstream stages.
4. Generate or provide B-Roll design data and normalized AI images.
5. Run `jianying-ai-image-aligner` v0.2 with a `visual_slot_plan`.
6. QC the final draft after B-Roll image alignment.

The old UI, screenshot-drag, overlay-video, and fixed `1.3s` B-Roll alignment routes have been removed. B-Roll image durations come from `target_end_us - target_start_us` in the visual slot plan.

## Runtime And Secrets

Keep runtime output and secrets outside this repository.

Recommended environment variables:

```powershell
$env:AUTO_CLIP_RUNTIME_DIR="$HOME\.auto_clip_runtime"
$env:IMAGE_ALIGNER_RUNTIME_DIR="$HOME\.auto_clip_runtime\image_aligner"
$env:JY_DRAFTC_EXE="<path-to-jy-draftc.exe>"
$env:DEEPSEEK_API_KEY="<your-key-if-using-deepseek>"
```

For file-based DeepSeek config, copy `jianying-aroll-inspector/config/deepseek.example.yaml` to `jianying-aroll-inspector/config/deepseek.local.yaml`. Local config files are ignored by Git.

## Quick Checks

```powershell
py -3 -m compileall -q "jianying-aroll-inspector\src" "jianying-ai-image-aligner\src"
```

With real local inputs, run the B-Roll preflight contract check:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "jianying-ai-image-aligner\run_pipeline_contract_check.ps1" `
  -DraftDir "<path-to-jianying-draft>" `
  -BrollMd "<path-to-broll-design.md>" `
  -ImageDir "<path-to-ai-images>" `
  -VisualSlotPlan "<path-to-visual-slot-plan.json>"
```

Run the larger A-Roll test suite from `jianying-aroll-inspector` when you have the required local draft fixtures and dependencies available.

## License

MIT
