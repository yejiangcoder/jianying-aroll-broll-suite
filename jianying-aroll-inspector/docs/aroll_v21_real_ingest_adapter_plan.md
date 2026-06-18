# A-Roll V21 Real Draft Ingest Adapter Plan

## Scope

This adapter only connects V21 dry-run to a user-authorized disposable Jianying draft. It is read-only and does not write draft files, call `encrypt()`, invoke V20 orchestration, or repair any blocker.

## Files Read From A Real Draft

- `timeline_layout.json`: resolves the active timeline id.
- `Timelines/<timeline_id>/draft_content.json`: encrypted timeline payload, decrypted read-only into a temporary file under `run_dir`.
- `Timelines/<timeline_id>/template-2.tmp`: required presence check only for this phase.

The root-level mirror `draft_content.json` and `template-2.tmp` are not modified. They are not needed for Phase 3 ingest dry-run.

## Existing Low-Level IO / Decrypt Capabilities

- `jy_bridge.read_json(path)`: safe local JSON reader.
- `jy_bridge.decrypt(jy_draftc, encrypted, output)`: low-level decrypt bridge. It calls the external Jianying decrypt backend.
- `jy_bridge.resolve_timeline_id(...)`: low-level helper, but V21 does not need it for the first adapter because active timeline resolution is implemented locally from `timeline_layout.json`.

## Safely Reused Pieces

- `jy_bridge.decrypt` is reused as a low-level decrypt primitive only.
- No writer, encrypt, EDL, repair, safe-cut resolver, or Phase4E orchestration code is reused.
- Decrypted plaintext is temporary and deleted immediately after JSON parsing.

## Explicitly Forbidden Reuse

V21 real ingest must not import or call:

- `aroll_phase4e_full_aroll`
- `aroll_uat_full`
- `aroll_downstream_repair_pipeline`
- `aroll_repair_applier`
- `aroll_safe_cut_boundary_resolver`
- `material_text_rows` fallback
- any V20 downstream repair, writeback, or safe-cut post resolver

## Adapter Contract

Input:

- `DraftDir`: user-authorized disposable draft directory.
- `run_dir`: isolated artifact directory.
- optional `jy_draftc`: explicit Jianying decrypt backend path. If omitted, `jy_bridge.DEFAULT_JY_DRAFTC` is used, which can be configured with `JY_DRAFTC` / `JY_DRAFTC_EXE`.

Output:

- `draft_data`: decrypted `draft_content` object.
- `text_tracks` / `text_segments`: text segments extracted from real tracks.
- `text_materials`: text materials extracted from `materials.texts`.
- `subtitle candidates`: text segments bound to their text materials and content text.
- `source media / clip segments`: video/audio segments with nested timerange normalized.
- `word_timeline`: real word rows only if present in a legal provider.
- `template/material metadata`: counts and resolved timeline metadata.
- `blockers`: explicit V21 blockers when ingest cannot prove source truth.

## Word Timeline Providers

Provider priority:

1. Explicit external `word_timeline.json` via `-WordTimelineJson` / `--word-timeline-json`.
2. Draft-native word/token schema discovered in decrypted `draft_content`.
3. Future ASR provider contract. This is not implemented and does not fabricate words.

Draft-native discovery accepts only explicit word/token paths such as `words`, `word_timeline`, `tokens`, `asr_words`, or `recognized_words`, and only rows with word-level text keys such as `word_text`, `word`, or `token` plus explicit word-level timing.

Forbidden:

- Treating subtitle rows as word rows.
- Treating sentence rows as word rows.
- Treating a timed row with only `text` as a word.
- Treating an entire subtitle as one word.

Block contract:

- `REAL_DRAFT_REQUIRED_FILE_MISSING`: missing draft directory, timeline layout, timeline dir, `draft_content.json`, or `template-2.tmp`.
- `REAL_DRAFT_DECRYPT_FAILED`: decrypt/read backend failed.
- `REAL_DRAFT_SCHEMA_UNSUPPORTED`: decrypted JSON shape is unsupported.
- `REAL_DRAFT_WORD_TIMELINE_MISSING`: no real word timeline found; V21 will not fabricate one.
- `REAL_DRAFT_TEXT_MATERIALS_MISSING`: no text materials found.
- `REAL_DRAFT_TEXT_SEGMENTS_MISSING`: no text/subtitle segments found.
- `REAL_DRAFT_SOURCE_SEGMENTS_MISSING`: no video/audio source segments found.

## Dry-Run Behavior

`run_aroll_v21_operator.ps1 -DraftDir ... -Mode dry-run` now calls `RealDraftIngestAdapter` instead of blocking at `REAL_DRAFT_INGEST_NOT_CONNECTED`.

If decrypt is unavailable, dry-run blocks with `REAL_DRAFT_DECRYPT_FAILED`. If decrypt succeeds but the real draft lacks word-level source truth, SourceGraph blocks with `REAL_DRAFT_WORD_TIMELINE_MISSING` and/or binding blockers. No sanitized `input_json` may be mixed with `DraftDir`.

The wrapper also accepts `-JyDraftc <path>` for machines where the decrypt executable is not available as `JianyingPro` on `PATH`.
