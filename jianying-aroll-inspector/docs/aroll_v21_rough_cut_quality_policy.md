# A-Roll V21 Rough-Cut Quality Policy

Status: `IDEA-side policy migration complete`

Scope: V21 compiler normalization, read-only rough-cut quality validation, and subtitle-track cleanup in writeback. This policy borrows V20 low-level rough-cut experience without importing V20 orchestration or patch chains.

## V20 To V21 Mapping

V20 low-level ideas migrated into V21:

- Lead/tail guard handling:
  - V21 now annotates each final segment with spoken source range and clip source range.
  - Default handle policy is `220ms` lead and `220ms` tail when source bounds allow it.
- Tiny fragment merge:
  - V21 now performs compile-time whole-segment micro-fragment merging before captions are rendered.
  - This replaces the old late-stage tiny EDL/display fragment cleanup pattern with SSOT timeline normalization.
- Phrase grouping:
  - Adjacent short segments on the same source segment are grouped into a readable phrase instead of remaining at near-word granularity.
- Subtitle track cleanup:
  - V21 writeback now clears all subtitle-bound residue tracks, not only the selected canonical subtitle track.
- Rough-cut quality gating:
  - V21 validators now fail closed on unreadable fragmentation and one-char caption excess.

Not migrated from V20:

- Downstream repair chains
- Repair proposals
- Post-validator patching
- Safe-cut post expansion
- `material_text_rows`

## Compiler Normalization

`RoughCutQualityNormalizer` runs after boundary-prefix normalization and final-target-repeat resolution, but before captions are rendered.

Normalization rules:

- Merge micro segments when duration is too short or caption text is too small.
- Prefer same-source, same-subtitle-neighborhood merges.
- Merge only whole final segments. No word cutting is introduced here.
- Repack target timeline after merges so there are no target gaps or overlaps.
- Apply source handles on video clip ranges while leaving spoken timing intact for captions.

Current defaults:

- `MIN_HARD_SEGMENT_DURATION_US = 300_000`
- `MIN_SOFT_SEGMENT_DURATION_US = 500_000`
- `PREFERRED_MIN_SEGMENT_DURATION_US = 700_000`
- `MIN_CAPTION_CHARS = 3`
- `DEFAULT_LEAD_HANDLE_US = 220_000`
- `DEFAULT_TAIL_HANDLE_US = 220_000`

## Validator Policy

`RoughCutQualityValidator` is read-only. It does not rewrite timeline, captions, or material plans.

Hard gates:

- `segments_lt_300ms == 0`
- `one_char_captions == 0`
- `final_timeline_count == caption_count == material_count == segment_count`
- `target_gap_count == 0`
- `target_overlap_count == 0`

Recorded diagnostics:

- `segments_lt_500ms`
- `segments_lt_700ms`
- `captions_le_3_chars`
- `segments_with_no_lead_handle`
- `segments_with_no_tail_handle`
- `non_adjacent_duplicate_text_count`
- `containment_repeat_count`

## Writeback Policy

Writeback remains execution-only:

- It writes the already-validated V21 `final_timeline`.
- Video clip segments use `clip_source_start_us` and `clip_source_end_us`.
- Caption tracks are replaced from `material_write_plan`.
- All subtitle-bound residue tracks are cleared.
- Non-subtitle title/callout/sticker text tracks are preserved.

Post-write evidence:

- `writeback_report.rough_cut_quality`
- `selected_text_track_id`
- `selected_video_track_id`
- `visible_caption_track_count`
- `old_subtitle_residue_track_count`
- `selected_canonical_subtitle_track_segment_count`

## Architecture Boundary

This policy keeps V21 clean:

- `final_timeline` remains the single source of truth.
- `captions` derive from `final_timeline`.
- `material_write_plan` derives from `captions`.
- validators remain read-only.
- writeback performs no repair.
