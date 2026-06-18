# A-Roll V21 Reuse Map

V21 reuses stable V20 components only as read-only helpers:

- Text normalization: `aroll_text_normalize.py`
- CJK repeat evidence: `aroll_cjk_short_repeat_gate.py`
- Adjacent modifier evidence: `aroll_adjacent_modifier_semantic_redundancy_gate.py`
- Style schema/safety checks: `aroll_subtitle_style_integrity_gate.py`
- Safe cut validation: `aroll_safe_cut_boundary_gate.py`
- Text material payload update primitive: `aroll_shared_edit_utils.py`

V21 does not reuse V20 downstream repair as a mutating stage. Repeat handling is represented as evidence, decisions, and a single compiler pass.

DeepSeek integration is constrained to semantic unit decisions:

```json
{
  "cluster_id": "repeat_000001",
  "keep_unit_id": "unit_keep",
  "drop_unit_ids": ["unit_drop"],
  "reason": "semantic reason",
  "confidence": 0.9,
  "requires_human_review": false
}
```

Fields such as `source_start_us`, `source_end_us`, `material_id`, `edl`, or `draft_content` are rejected.
