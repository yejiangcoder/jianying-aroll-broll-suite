# Architecture

## Modules

- `parse_broll_design.py` parses table-style and block-style B-roll markdown.
- `parse_subtitles.py` reads SRT and readable Jianying-style subtitle attachments.
- `plan_builder.py` scans image assets and builds semantic / execution plans.
- `match_broll_to_subtitles.py` normalizes text, builds subtitle windows once, performs global text-anchor matching by default, and keeps monotonic matching as an opt-in mode for strictly chronological designs.
- `draft_reader.py` provides readable draft JSON helpers and an external decoder hook.
- `draft_writer.py` appends an editable `AI_BROLL` photo track to draft JSON.
- `cleanup_runtime.py` removes old runtime outputs.
- `cli.py` exposes the package commands.

## Data Model

The core pipeline uses plain dataclasses:

- `BrollItem`
- `ImageAsset`
- `SubtitleRow`
- `SemanticPlanItem`
- `ExecPlanItem`

Keeping the model small makes it easier to test draft parsing and subtitle matching independently from editor-specific write details.

## Design Principles

- Local-first file processing.
- No bundled private media or draft files.
- No UI screenshot recognition in the core package.
- No hidden cloud upload path.
- Draft writer is an adapter, not a replacement for editor-specific validation.
