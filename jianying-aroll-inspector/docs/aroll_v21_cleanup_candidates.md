# A-Roll V21 Cleanup Status

V20 production wrappers, Phase4/Phase4E debug scripts, downstream repair,
repair applier, old EDL builders, legacy capsule exporter, and legacy
production-parity tests have been removed from the active source tree.

Keep:

- V21-only entry: `run_aroll_v21_operator.ps1`
- Read-only helper/gate modules that V21 imports directly and tests as pure validators
- `docs/v21_v20_quality_algorithm_migration.md` as the migration record
- No-drift tests that assert legacy patch modules do not return

Cleanup rule: future changes must not reintroduce V20 orchestration, downstream
repair, old EDL mutation, or legacy script entrypoints into V21.

Current status remains `ARCHITECTURE CONDITIONAL PASS`: real draft decrypt/read
is connected, but production word-level source truth must come from legal
draft-native word/token data, external `word_timeline.json`, or a future ASR
provider. Subtitle text must not be treated as word timeline input.
