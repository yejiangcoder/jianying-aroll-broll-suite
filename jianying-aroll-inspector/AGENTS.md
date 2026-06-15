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
