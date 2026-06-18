# A-Roll V21 Phase 2 Report

Status: implemented for synthetic realistic production-parity fixtures.

## Fixture Scope

The current Phase 2 fixtures are marked `synthetic_realistic`. They are structured to resemble real Jianying material/timeline artifacts but are not exported from a live runtime run and must not be reported as real UAT evidence.

Added fixture roots:

- `fixtures/real_materials/`
- `fixtures/real_timelines/`
- `fixtures/uat_capsules/`

## Material Coverage

- Normal caption template
- Giant title material
- Callout material
- `content` / `base_content` variants
- Malformed content JSON
- Title-like caption confusion case

Covered checks:

- Title/callout/giant materials cannot become canonical caption template.
- `content` and `base_content` remain JSON with styles.
- Output caption material fingerprints are consistent.
- `writer_fallback_count = 0`.

## Timeline Coverage

- Multi-clip gap
- Source rebase
- Multi-char word alignment
- Hidden audio repeat
- CJK short overlap
- Subtitle/audio mismatch
- Restart disfluency

Covered checks:

- Captions derive from final timeline words.
- Hidden audio repeat is detected even when subtitle text is clean.
- Multi-char tokens are not partially cut.
- Unsafe edit units block instead of being guessed.
- Validators remain read-only.

## Capsule Contract

`tools/export_aroll_v21_uat_capsule.py` now exports:

- `source_graph.json`
- `edit_units.json`
- `repeat_clusters.json`
- `decision_plan.json`
- `final_timeline.json`
- `final_edl.json`
- `captions.json`
- `canonical_caption_template.json`
- `material_write_plan.json`
- `validator_report.json`
- `postwrite_report.json`
- `blocker_report.json`
- `decision_trace.json`

Forbidden:

- `draft_content.json`
- `template-2.tmp`
- media files
- large runtime JSON

## Postwrite Verification

V21 reports `postwrite_mode` explicitly:

- `simulated`: validates material structure from the write plan; does not claim real UAT.
- `actual_decrypt`: caller supplied postwrite materials from a real postwrite decrypt step.

Current IDEA tests only cover simulated and supplied-material verification. Real decrypt verification remains Desktop-only.
