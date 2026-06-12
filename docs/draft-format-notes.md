# Draft Format Notes

This repository contains a minimal draft JSON adapter for readable Jianying / CapCut-like draft structures. It focuses on concepts that are stable across observed draft formats:

- a `materials` object with media lists such as `videos` and `speeds`;
- a `tracks` list;
- each track has `segments`;
- each segment references a material by `material_id`;
- each segment uses a `target_timerange` with microsecond `start` and `duration`;
- photo-like local files can be represented as video materials with `type = photo`.

## Encoded Drafts

Some editor versions store encoded or encrypted draft content. This repository does not include proprietary binaries or reverse-engineered decoder code. The `draft_reader.decode_draft_with_command` helper allows maintainers to integrate a local decoder command outside the package.

## Reference Notes

During development, existing open-source CapCut / Jianying draft tooling was used as high-level reference material for concepts such as timerange units, material references, and segment-track relationships. No third-party source code is copied into this repository.

Projects worth comparing when extending adapters:

- `capcut-cli`
- `pyCapCut`
- `capcut-mate`
- `capcut-srt-export`
- `jy-draftc`

Before copying any third-party implementation, check its license and retain attribution.

