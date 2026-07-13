# Changelog

## Unreleased

- Added deterministic paired 16:9 / 9:16 cover generation with explicit white/dark style routing.
- Added machine-readable cover jobs, locked renderer manifests, tamper validation, state-bound promotion, and external-cover import checks.
- Kept reference images and subject media outside the public repository.
- Improved subtitle matching with prebuilt subtitle windows for faster planning.
- Changed the default planner to global text-anchor matching so appended B-roll batches can map back to earlier subtitles.
- Kept monotonic matching as an opt-in mode for strictly chronological designs.
- Added regression tests for repeated short targets, multi-subtitle matches, and non-chronological design order.

## 0.1.0

- Initial open-source package structure.
- Added B-roll design parsing.
- Added SRT and Jianying attachment subtitle parsing.
- Added subtitle matching and execution plan generation.
- Added draft JSON adapter notes and minimal writer.
