# A-Roll V21 Current Status

Status: `ARCHITECTURE CONDITIONAL PASS`

V21 is not a V20 patch wrapper. The V21 entry is `run_aroll_v21_operator.ps1`, which routes to `src/aroll_v21.cli`, `src/aroll_v21.operator`, and `ArollEngine.run`.

Confirmed:

- V21 does not import Phase4E, downstream repair, repair applier, safe-cut resolver, or `material_text_rows`.
- Validators remain read-only.
- Writer fallback is forbidden.
- DeepSeek is limited to semantic decisions and physical fields are blocked.
- Final timeline is the only compiled edit truth.
- Captions are derived from final timeline word ids.
- Real draft decrypt/read adapter is connected for dry-run ingest.
- Native `text_materials[*].words` can be used as word truth only when each row has explicit word text and source timing.
- Native word variants currently accepted include `text/word_text/word/token/content`, `source_start_us/source_end_us`, `start_us/end_us`, `start_time/end_time`, `start/end/duration`, and nested `time_range`/`timerange`/`range`.
- Native word timing may be relative to the owning subtitle; V21 maps it through the text segment target range and source media segment target/source range.
- Native discovery scans both raw `materials.texts[*].words` and adapter-normalized `text_materials[*].words`.
- Round 4 update: native discovery now reports production-useful scan metadata for adapter-normalized text materials, including scanned material count, materials with `words`, candidate word-row count, accepted/rejected counts, and sample rejection reasons. If word rows exist but all are schema-invalid, V21 emits an explicit `DRAFT_NATIVE_WORD_ROWS_REJECTED` blocker instead of only reporting a missing word timeline.
- Round 5 update: native discovery supports the real Jianying `text_materials[*].words` dict-of-arrays schema observed in the minimal sample pack: `start_time[]`, `end_time[]`, and `text[]`. These values are treated as millisecond offsets relative to the owning text segment/subtitle and converted to microseconds before source mapping. `current_words={}` is ignored and does not become word truth.
- Round 6 update: real ingest maps native dict-of-arrays words through the owning text segment target range, including nested `clip.target_timerange`, before converting target time to source media time. Missing text segment binding or source mapping now blocks with explicit native word mapping errors. Successful native ingest reports mapping diagnostics such as mapped text/source segment counts and sample mapped words.
- Intra-edit-unit repeat evidence can compile through word-boundary split decisions instead of V20 downstream repair.
- Semantic clusters emit request payloads and trace when DeepSeek is not configured.
- DeepSeek-unconfigured semantic clusters are unresolved write blockers: dry-run discovery may continue to compiler/writer/validators, but write is not allowed.
- A-not-A CJK question structures are filtered as legal evidence-layer false positives; repeated A-not-A phrases remain repeat candidates.
- Caption template detection is relation-first: subtitle rows and caption `source_subtitle_uids` constrain candidate text materials, then safe style/content schema and unique fingerprint grouping select the canonical template. Rejection diagnostics are emitted when selection fails.
- Round 4 update: subtitle-bound text materials are not rejected solely by a title-like marker or position heuristic. That signal is recorded in `title_like_reasons` as style risk; actual giant/callout/title/unsafe-schema materials are still rejected. This preserves `writer_fallback_count = 0` while avoiding the real 117-subtitle `title_like` over-rejection pattern.
- Round 5 update: the title-like position diagnostic now distinguishes normal bottom subtitles from center-title risk. The observed real subtitle shape (`font_size=5.0`, `initial_scale=1.0`, `scale=1.0`, `clip.transform.y=-0.73`) is accepted when subtitle-bound and schema-safe; horizontal centering alone does not reject a caption template.
- Round 6 update: FinalTimelineCompiler now breaks at edit-unit/subtitle boundaries and fail-closes oversized or mixed-subtitle compiled segments instead of merging unrelated subtitle words by source-time proximity. Caption template grouping now uses a V21 stable style fingerprint that excludes per-caption ids, text, `content.text`, `base_content.text`, recognition text, and text-length ranges while retaining real style differences. External normalized subtitle ids such as `sub_000001` resolve through subtitle_index to the real text material via `SubtitleIdentityResolver`.

Still conditional:

- Real draft word truth must come from native word rows or an explicit external `word_timeline.json`; subtitles and sentences are never accepted as word truth.
- V21 now supports an explicit external `word_timeline.json` input through `-WordTimelineJson` / `--word-timeline-json`.
- Future ASR provider is a contract only and does not fabricate word truth.
- Real write/encrypt/postwrite commit backend remains outside the IDEA-safe path.

Entrypoint boundary:

- `run_aroll_v21_operator.ps1` is the V21 compiler entry.
- V20 production wrappers and Phase4/Phase4E scripts have been removed from the active source tree.
- V21 still preserves selected low-level read-only helper ideas where they have explicit V21 tests.
