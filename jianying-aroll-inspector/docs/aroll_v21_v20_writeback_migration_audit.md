# A-Roll V21 V20 Low-Level Writeback Migration Audit

Status: `ARCHITECTURE CONDITIONAL PASS`

This audit covers only V21 low-level writeback capability. No real UAT, write, commit, encrypt, or draft mutation was performed during this pass.

## Migrated Low-Level Helpers

1. `jy_bridge.encrypt`
   - V21 `RealDraftWriteback` writes a modified plaintext draft artifact to `run_dir`, encrypts it, then writes encrypted bytes to the active timeline targets.

2. `jy_bridge.root_mirrors_timeline_id`
   - V21 detects whether the project root mirror must be written.
   - If required, it writes root `draft_content.json` and `template-2.tmp` in addition to active timeline targets.
   - If mirror detection fails, V21 records `root_mirror_check_failed` / `root_mirror_check_error` and keeps timeline target writes scoped.

3. Timeline integrity checks
   - V21 calls low-level timeline checks before modifying draft data:
     - `assert_timeline_content_id`
     - `assert_layout_has_no_duplicate_timeline_ids`
     - `assert_all_project_timeline_files_match_folder_ids`
   - Failures block with V21-specific codes:
     - `V21_TIMELINE_CONTENT_ID_MISMATCH`
     - `V21_TIMELINE_LAYOUT_DUPLICATE_IDS`
     - `V21_PROJECT_TIMELINE_FOLDER_ID_MISMATCH`

4. V20 source/material time mapping
   - V21 now maps final timeline source-time values back to material-time using local V21 copies of the low-level math:
     - `source_timeline_to_material_time`
     - `display_to_material_delta`
   - 1x clips preserve the previous simple output.
   - Constant speed clips such as 2x map material duration correctly.
   - Reverse / curve speed / unsafe source-target ratios block instead of silently writing unsafe timing.

5. Track preflight
   - V21 reports audio/filter/speed preflight in `writeback_report`.
   - Independent audio and filter tracks are report-only.
   - Reverse, curve speed, or unsafe source-target mapping block writeback.

## Not Migrated

1. V20 orchestration and repair modules were not migrated.
   - V21 does not import or call Phase4E, UAT full flow, downstream repair, repair applier, safe-cut post resolver, or text-material row fallback logic.

2. Complex curve-speed rewrite support is not implemented.
   - Current policy is fail-closed with `V21_WRITEBACK_UNSUPPORTED_SPEED_MAPPING`.
   - This is intentional because wrong timing writes are worse than blocking.

3. Audio/filter rewrite is not implemented.
   - Current policy is report-only for independent audio/filter tracks.
   - V21 A-Roll writeback remains scoped to final video timeline and canonical caption materials.

## Audit Questions

1. V20 哪些低层 helper 已迁移？
   - `encrypt`, `root_mirrors_timeline_id`, timeline integrity checks, source/material time mapping math, root/active target writes, and audio/filter/speed preflight reporting.

2. V20 哪些低层 helper 未迁移？为什么？
   - Complex curve-speed writing and audio/filter rewriting are not migrated. They are blocked or reported because V21 currently has no validated SSOT for rewriting those structures.

3. V21 是否仍依赖 first text/video track fallback？
   - No. Subtitle track is selected from canonical caption template candidate material bindings. Video track is selected from final timeline `source_segment_id` bindings.

4. V21 是否仍可能删除非字幕 text materials？
   - No by design. It deletes only old segments on the selected subtitle track whose material IDs match canonical template candidate material IDs. Other text tracks/materials are preserved.

5. V21 是否完整处理 root mirror？
   - Yes for low-level target writes. If root mirror is required, V21 writes root `draft_content.json` and `template-2.tmp`; detection failures are recorded and do not expand write scope.

6. V21 是否有 timeline integrity checks？
   - Yes. The three low-level checks run before mutation/encrypt/write.

7. V21 是否有 audio/filter/speed preflight？
   - Yes. Audio/filter is recorded in the report. Unsupported video speed/mapping blocks writeback.

8. V21 是否使用 V20 source/material time mapping？
   - Yes. The V20 low-level formulas were copied into V21 writeback as local helper logic.

9. V21 是否导入任何 V20 主流程/repair 模块？
   - No. Tests scan `real_draft_writeback.py` for forbidden V20 patch modules and helper names.

10. 当前 V21 writeback 是否可称为 clean + general？
   - For 1x and constant-speed A-Roll video plus canonical captions: yes, conditional on Desktop real write verification. Complex speed and audio/filter rewriting remain intentionally blocked/report-only.

11. 如果不能，剩余 P0/P1 是什么？
   - No known P0 remains in writeback backend from this audit. Remaining P1 scope is future support for complex speed curves and independent audio/filter rewrite if the V21 IR explicitly models them.
