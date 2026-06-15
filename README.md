# jianying-aroll-broll-suite

Jianying / CapCut automation suite for A-Roll editing and AI-assisted B-Roll image alignment.

This toolkit combines maintained A-Roll editing automation with B-Roll image alignment workflows for Jianying / CapCut drafts.

This project was developed with Codex to reduce repetitive editing work in AI-assisted video production workflows.

## What It Does

`jianying-aroll-broll-suite` brings together two local-first workflows:

- A-Roll editing tools for draft inspection, safety gates, rewrite planning, and production operator flows.
- B-Roll image alignment tools that turn a structured B-roll markdown plan and a final subtitle timeline into an execution plan for editable image clips.

When a readable draft JSON structure is available, the B-Roll workflow can also append a dedicated `AI_BROLL` image track to the draft content.

It is local-first:

- Input: B-roll design markdown, final subtitles, local AI-generated image directory.
- Output: semantic plan CSV, execution plan CSV, optional modified draft JSON.
- No cloud upload is required by this package.
- No real user media, private drafts, or production assets are included in this repository.
- This is not a video generator and not a commercial appearance or private delivery system.

## Why It Exists

AI-assisted video workflows often create dozens of B-roll images, but manually placing each image on a timeline is repetitive and error-prone. This project automates the bridge between:

```text
B-roll design document
        +
AI image assets
        +
final subtitle timestamps
        |
        v
editable AI_BROLL image clips in a draft timeline
```

## Workflow

1. Write a B-roll design document with one row per intended AI image.
2. Export or read the final subtitle timeline.
3. Put generated AI images in a local directory using stable IDs such as `sample_AI_01_office.png`.
4. Build a semantic plan from the design document and image directory.
5. Match each B-roll target quote to subtitle start times.
6. Write an execution plan.
7. Optionally append an editable `AI_BROLL` track to a readable Jianying / CapCut draft JSON.

## Features

- Parse markdown B-roll tables and block-style AI image entries.
- Scan AI image directories by stable image IDs.
- Parse SRT subtitle files.
- Parse Jianying-style `attachment_script_video.json` files when available.
- Match B-roll target quotes to subtitle text with global text-anchor matching and normalized fuzzy fallback.
- Enforce fixed image duration, default `1.3s`.
- Build `broll_semantic_plan.csv` and `broll_exec_plan.csv`.
- Append photo materials and segments to a draft JSON adapter layer.
- Clean runtime output directories safely.

## Installation

```bash
python -m pip install -e .
```

For tests:

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

## Quick Start

Create a plan from the included examples:

```bash
python -m jianying_ai_broll_aligner.cli plan \
  --broll examples/broll_design_sample.md \
  --subtitles examples/final_subtitles_sample.srt \
  --image-dir examples/assets \
  --output-dir runtime/sample_run \
  --duration-sec 1.3
```

The command writes:

- `runtime/sample_run/broll_semantic_plan.csv`
- `runtime/sample_run/broll_exec_plan.csv`

## Input Examples

See:

- `examples/broll_design_sample.md`
- `examples/final_subtitles_sample.srt`
- `examples/config.sample.json`

Example B-roll row:

```markdown
| index | type | target_quote | visual_direction |
| --- | --- | --- | --- |
| 01 | AI image | "He finally closes the laptop and walks outside." | A man leaving an office at night |
```

## Output Examples

See:

- `examples/broll_semantic_plan_sample.csv`
- `examples/broll_exec_plan_sample.csv`

Execution rows include:

- `image_id`
- `image_path`
- `subtitle_index`
- `subtitle_text`
- `start_sec`
- `duration_sec`
- `match_method`
- `confidence`

## Privacy / Local-First Statement

This repository is designed as a local creator tool. It does not include real drafts, real production footage, real private scripts, generated image caches, runtime screenshots, or credentials. The included examples are fictional.

You should keep private draft files, generated images, and editor runtime folders outside the repository. The default `.gitignore` excludes media files, runtime folders, logs, local config, and secret files.

## Roadmap

- Improve draft adapters for more Jianying / CapCut versions.
- Add more subtitle source readers.
- Add regression fixtures for draft timeline structures.
- Add safer dry-run validation before draft writes.
- Add optional OpenTimelineIO / XML export.

## License

MIT
