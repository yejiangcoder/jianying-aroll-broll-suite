# A-Roll V21 No-Drift Audit

Status: PASS after one boundary fix.

Scope: `src/aroll_v21/` only. IDEA did not access runtime, real drafts, media, `draft_content.json`, or `template-2.tmp`.

## Static Scans

Commands used:

```powershell
rg -n "repair|fallback|fixup|auto_fix|resolver|downstream|material_text_rows|safe_cut|gate|patch|source_start_us|material_id|draft_content" src\aroll_v21
rg -n "from aroll_|import aroll_" src\aroll_v21
rg -n "aroll_phase4e_full_aroll|aroll_downstream_repair_pipeline|aroll_repair_applier|aroll_safe_cut_boundary_resolver|material_text_rows" src\aroll_v21
rg -n "source_start_us|source_end_us|target_start_us|target_end_us|edl|material_id|segment_id|draft_content|FORBIDDEN_DEEPSEEK_FIELDS" src\aroll_v21\decision src\aroll_v21\compiler src\aroll_v21\writer src\aroll_v21\render src\aroll_v21\validate
```

Legacy-pipeline scan result:

```text
No matches in src/aroll_v21 for:
aroll_phase4e_full_aroll
aroll_downstream_repair_pipeline
aroll_repair_applier
aroll_safe_cut_boundary_resolver
material_text_rows
```

## Findings

1. Validator mutation:
   PASS. `ReadOnlyValidators.run()` snapshots `final_timeline`, `captions`, and `material_write_plan` before validation and reports `validators_read_only`.

2. Silent fallback:
   PASS after fix. `SubtitleRenderer` previously had a text fallback from `segment.text`; it now derives caption text only from `final_timeline.word_ids`. Writer reports `no_writer_fallback=true` and `writer_fallback_count=0`; missing or non-unique template blocks.

3. Downstream repair / fixup / resolver:
   PASS. V21 does not import V20 downstream repair, repair applier, safe cut resolver, or `material_text_rows`.

4. DeepSeek physical fields:
   PASS after fix. `FORBIDDEN_DEEPSEEK_FIELDS` includes `source_start_us`, `source_end_us`, `target_start_us`, `target_end_us`, `edl`, `final_edl`, `material_id`, `segment_id`, and `draft_content`.

5. Canonical caption template:
   PASS. `CaptionTemplateDetector` requires exactly one safe, caption-like template. Title/callout/emphasis/sticker/headline templates are blacklisted.

6. Final timeline generation:
   PASS. `FinalTimelineCompiler` is the only V21 component that creates `FinalTimelineSegment` rows. Validators convert it to read-only EDL rows for checks only.

7. Subtitle rendering:
   PASS after fix. `SubtitleRenderer` builds caption text from canonical words referenced by `final_timeline.word_ids`.

8. V20 dependency as main flow:
   PASS. V21 uses V20 read-only helpers for normalization, CJK evidence, style checks, final/hidden repeat checks, and safe cut validation. It does not use V20 Phase4E, downstream repair, safe cut resolver, or material text row writer as the main flow.

## Allowed Read-Only Reuse

- `aroll_text_normalize`
- `aroll_cjk_short_repeat_gate`
- `aroll_adjacent_modifier_semantic_redundancy_gate`
- `aroll_final_repeat_gate`
- `aroll_hidden_audio_repeat_gate`
- `aroll_safe_cut_boundary_gate`
- `aroll_subtitle_style_integrity_gate`
- `aroll_shared_edit_utils.clone_text_material`

These are used as evidence/validation/helpers, not as mutating downstream repair.

## Blockers

None.
