# A-Roll V21 Phase 4 Follow-Up Report

Result: `ARCHITECTURE CONDITIONAL PASS`

Completed follow-up items:

- Real draft word discovery was tightened to explicit word/token schemas only.
- Native `text_materials[*].words` discovery is supported when rows satisfy word-level schema and timing.
- Round 2 update: native words now accept `start_time/end_time`, nested time ranges, `content` text fields, and relative subtitle timing that maps through text segment target time to source segment time.
- Round 3 update: DraftNativeWordTimelineProvider now scans both raw `draft_content` and normalized `text_materials[*].words` passed by the real draft adapter. This covers real drafts where the adapter has preserved text material word rows in SourceGraph inputs.
- Round 4 update: DraftNativeWordTimelineProvider now receives normalized `text_materials`, `text_segments`, and `source_segments` from real ingest, prioritizes `text_materials[*].words`, and emits debug metadata (`candidate_count`, `accepted_count`, `rejected_count`, scan counts, and sample rejection reasons). Schema-invalid native rows fail closed with `DRAFT_NATIVE_WORD_ROWS_REJECTED`.
- Round 5 update: the provider now handles the concrete sample-pack word schema where `words` is a dict of parallel arrays: `start_time`, `end_time`, and `text`. Valid rows are expanded into word rows using millisecond-to-microsecond conversion; mismatched arrays are rejected with `dict_of_arrays_length_mismatch`. `current_words={}` remains ignored.
- Round 6 update: native dict-of-arrays words are mapped through their owning text segment target range, including `clip.target_timerange`, then through the source segment target/source range. Mapping failures now emit explicit native word blockers, and successful ingest reports `native_word_mapping` diagnostics.
- Subtitle/sentence timed rows are rejected as word timeline input.
- External `word_timeline.json` adapter and CLI/PowerShell parameters were added.
- Intra-edit-unit repeats now produce word-boundary `split_decisions` when safe, or specific split blockers when unsafe.
- DeepSeek-unconfigured semantic clusters now emit `semantic_request_payloads.json` and non-empty decision trace.
- Round 2 update: unresolved semantic clusters are kept for dry-run discovery as `write_blocker` issues. They do not execute semantic deletion and do not permit write.
- Legal CJK A-not-A question structures such as `X不X` are filtered in V21 evidence before hidden repeat split planning; true repeated phrases remain detectable.
- Modifier semantic payloads now carry raw phrase/span/context and mark segmentation as untrusted instead of trusting regex fields such as `left_modifier/right_modifier/head_text`.
- Downstream artifacts that are not reached now carry explicit `not_reached` status instead of empty placeholders.
- Round 3 update: Caption template detection now uses SourceGraph subtitle/material/segment relations before style grouping. It reports `rejection_summary` and `sample_rejections` for `CAPTION_TEMPLATE_NOT_FOUND` instead of only `rejected_count`.
- Round 4 update: Caption template detection no longer lets a title-like marker override a positive subtitle/material binding. Subtitle-bound safe materials record the title-like signal in `title_like_reasons`, while real giant/callout/unsafe templates remain rejected. This is covered by a 117-material Round4-like regression.
- Round 5 update: position diagnostics now classify `clip.transform.y <= -0.45` as `bottom_subtitle_position`. The sample-pack normal caption shape (`font_size=5.0`, `initial_scale=1.0`, `scale=1.0`, `clip.transform.y=-0.73`) is accepted as a subtitle-bound safe template, with `subtitle_bound_position_risk_downgraded` recorded instead of `title_like` rejection.
- Round 6 update: FinalTimelineCompiler now respects edit-unit/subtitle boundaries and blocks unsafe oversized or mixed-subtitle compiled segments. Caption template fingerprinting now normalizes volatile per-caption fields so same-style caption materials collapse to one group while real style differences remain ambiguous. `SubtitleIdentityResolver` maps external normalized ids such as `sub_000001` to real subtitle/material rows by subtitle index.
- Caption template selection now groups by safe fingerprint instead of requiring one material candidate.
- FinalTimelineCompiler respects `source_segment_id` when grouping final segments.
- CanonicalSourceGraph now records source material inventory or emits explicit blockers.
- V21 writer now uses V21-local caption material cloning and no longer imports legacy shared edit utils.
- Legacy gate reuse is documented as read-only.
- Audit zip packaging rules were added.

Remaining conditions:

- Real write/encrypt/postwrite commit remains out of IDEA scope.
- Desktop Codex may use native `text_materials[*].words` or provide a validated external word timeline before the next real UAT.
- V20 remains present as legacy code until V21 real UAT is stable.
