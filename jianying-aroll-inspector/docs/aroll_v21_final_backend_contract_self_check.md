# A-Roll V21 Final Backend Contract Self-Check

Status: `READY_FOR_DESKTOP_REAL_UAT`

Scope: V21 backend integration, artifact contracts, failure injection, static hidden-bug scan, and low-level writeback contract. This pass used only temporary fixtures and fake encrypt. No real UAT, real draft write, commit, or real encrypt was performed.

## Answers

1. V21 是否还有 first-track fallback？
   - No. Subtitle track selection is bound to canonical caption template candidate material IDs. Video track selection is bound to `final_timeline.source_segment_id`.

2. V21 是否可能误删非字幕 text materials？
   - Current tests cover title/callout tracks and materials. V21 deletes only old subtitle-bound segments/materials on the selected subtitle track.

3. V21 是否可能 fake commit？
   - Contract tests now require `commit_performed=true` only when `writeback_success=true`; fake encrypt and target-write failures keep `commit_performed=false`.

4. V21 是否在 writeback 前验证 semantic/validator/writer gates？
   - Yes. Gate-failure injection verifies RealDraftWriteback is not called when prewrite or postwrite validators fail.

5. V21 是否真实写 temp target files？
   - Yes. Full-chain backend tests compare temp `draft_content.json` and `template-2.tmp` before/after, including root mirror targets.

6. V21 是否迁移 V20 root mirror / timeline integrity / source time mapping？
   - Yes. Root mirror writes, timeline integrity checks, and source/material time mapping are covered by dedicated tests.

7. V21 是否迁移 audio/filter/speed preflight？
   - Yes. Audio/filter preflight is report-only. Reverse, curve speed, and unsafe source-target mapping fail closed.

8. V21 是否仍导入 V20 repair/material_text_rows/downstream？
   - No. Static scans cover V21 source and entrypoint for forbidden V20 patch symbols.

9. V21 是否能称为 clean + general backend？
   - For V21 SSOT final timeline, canonical captions, constant-speed A-Roll video, and canonical caption material writeback: yes. Complex curve-speed rewrite and independent audio/filter rewrite remain future explicit IR work, not silent behavior.

10. 如果不能，剩余 P0/P1 是什么？
   - No known P0 remains from the IDEA backend contract sweep. P1: future explicit support for complex speed curves and independent audio/filter rewrite if required by product scope.

## Contract Tests Added

- `tests/test_aroll_v21_backend_contract_full_chain.py`
- `tests/test_aroll_v21_backend_contract_failure_injection.py`
- `tests/test_aroll_v21_windows_path_contracts.py`
- `tests/test_aroll_v21_no_fake_success_contract.py`
- `tests/test_aroll_v21_static_hidden_bug_scan.py`
- `tests/aroll_v21_contract_assertions.py`

## Bugs Found And Fixed In This Sweep

1. Real `DraftDir` paths did not pass `postwrite_materials_json` into validators.
2. Actual-postwrite `write + commit` path did not call `RealDraftWriteback`.
3. `postwrite_materials_json` shape was not validated at the operator boundary.
4. Failed sacrificial writeback could still mark `ready_for_user_manual_qc=true`.
5. `writer_fallback_count` was missing from `run_summary`.
