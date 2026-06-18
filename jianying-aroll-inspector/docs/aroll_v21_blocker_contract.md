# A-Roll V21 Blocker Contract

Every failure must be represented as:

```json
{
  "code": "BLOCKER_CODE",
  "message": "reader-facing explanation",
  "layer": "ingest | decision | compiler | writer | validate | postwrite",
  "severity": "fatal",
  "context": {}
}
```

No V21 layer may silently fallback.

## Core Blockers

- `SOURCE_WORD_TIME_UNBOUND`
- `SOURCE_WORD_MATERIAL_UNBOUND`
- `EDIT_UNIT_WORD_BINDING_MISSING`
- `DEEPSEEK_SEMANTIC_PLANNER_NOT_CONFIGURED`
- `DEEPSEEK_DECISION_HAS_PHYSICAL_FIELDS`
- `DEEPSEEK_DECISION_UNKNOWN_UNIT`
- `UNSAFE_EDIT_UNIT_DROP_BLOCKED`
- `FINAL_TIMELINE_EMPTY`
- `CAPTION_TEMPLATE_NOT_FOUND`
- `CAPTION_TEMPLATE_NOT_UNIQUE`
- `FINAL_REPEAT_VALIDATOR_FAILED`
- `HIDDEN_AUDIO_REPEAT_VALIDATOR_FAILED`
- `SAFE_CUT_VALIDATOR_FAILED`
- `SUBTITLE_COVERAGE_VALIDATOR_FAILED`
- `SUBTITLE_STYLE_VALIDATOR_FAILED`
- `POSTWRITE_MATERIAL_VALIDATOR_FAILED`
- `SEMANTIC_FINAL_REVIEW_VALIDATOR_FAILED`

Validators are read-only. A failed validator can only block and report; it cannot repair timeline, captions, or materials.
