# Deterministic Cover Maker

`cover-maker` produces three paired 16:9 and 9:16 cover candidates from one approved title and one local subject image.

The subject is replaceable. The selected `cover_type` locks the background, title color, font, layout regions, output dimensions, and template family. Supplying a face or screenshot never changes the style automatically.

## Cover Types

- `white_editorial` is the default: near-white background and oversized black serif title.
- `dark_face` is explicit only: dark background and oversized white serif title.

The repository does not bundle real template images, faces, screenshots, production scripts, or generated covers. The JSON template library is a structural example only.

## Requirements

- Python 3.10+
- Pillow
- Windows PowerShell for promotion/import/closeout helpers
- A Chinese font configured in `cover_maker_config.json`; the checked-in default targets Noto Serif SC on Windows

Set `AUTO_CLIP_RUNTIME_DIR` to override the default `$HOME/.auto_clip_runtime` state root used by the PowerShell helpers.

## Core Flow

```powershell
py -3 cover-maker\scripts\prepare_cover_job.py <arguments>
py -3 cover-maker\scripts\render_cover_candidates.py --job <cover_job.json>
py -3 cover-maker\scripts\validate_cover_package.py --manifest <cover_generation_manifest.json>
```

The renderer creates exact 3840x2160 and 2160x3840 PNG files, a prompt package, per-candidate manifests, a contact sheet, and a top-level `cover_generation_manifest.v2`.

`workflow_mode=standard_pipeline` requires draft/B-Roll bindings. `workflow_mode=old_video_recovery` remains project-local and cannot be promoted into the global current-draft state.

## Verification

```powershell
py -3 -m pytest cover-maker\tests -q
```

The tests cover deterministic dimensions and colors, style-routing isolation, state binding, tamper detection, candidate promotion, external import aspect selection, and delivery closeout blockers.
