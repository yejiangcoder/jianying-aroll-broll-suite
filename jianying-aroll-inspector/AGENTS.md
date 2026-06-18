# AGENTS.md

This project is split between lightweight code work and heavy local execution.

## IDEA Codex

- Only make precise code changes.
- Do not scan runtime directories.
- Do not read large JSON, image, video, audio, or log files unless a specific bug requires it.
- Do not modify real Jianying drafts.
- Do not run long tasks.
- Do not batch-generate images.
- Change one problem at a time.

## V21 Controlled Real UAT Exception

The default IDEA Codex rules above remain in force. IDEA Codex may perform one real V21 disposable-draft UAT only when all of the following conditions are satisfied:

- The user explicitly authorizes this UAT turn.
- The user explicitly provides the disposable draft path.
- The run uses only the V21 entry: `run_aroll_v21_operator.ps1 -> src/aroll_v21.cli -> src/aroll_v21.operator -> ArollEngine.run()`.
- The run must not import, call, wrap, or reuse V20 patch modules: `aroll_phase4e_full_aroll`, `aroll_downstream_repair_pipeline`, `aroll_repair_applier`, `aroll_safe_cut_boundary_resolver`, `material_text_rows` fallback, any V20 downstream repair, any V20 safe-cut post resolver, or any V20 subtitle fallback writer.
- The run may operate only on the user-specified disposable draft.
- The run must not scan or modify any other draft.
- All run artifacts must be written to the user-specified `run_dir`.
- If the actual write/decrypt backend is unavailable, the run must block and must not claim UAT pass.
- Any blocker may be fixed only inside V21 layers: SourceGraph, CandidateEvidence, DecisionPlan, FinalTimelineCompiler, SubtitleRenderer, CaptionMaterialWriter, Validators/PostwriteVerifier.
- Do not add symptom-specific if/else gates to pass UAT.
- Validators must remain read-only and must not repair.
- Writer fallback is forbidden.
- DeepSeek must not output physical edit fields.
- After UAT, run a no-drift scan to confirm V21 was not polluted.

## Desktop Codex

- Handles project migration.
- Handles worktree-style maintenance and packaging.
- Runs long tasks, UAT, batch jobs, image API scripts, and report generation.
- Defaults to dry-run for migration and cleanup.
- Must back up before writing real drafts.

## Runtime

- Runtime is external.
- Runtime does not belong in IDEA.
- Runtime does not belong in the source tree.
- Runtime does not belong in dev snapshots.
