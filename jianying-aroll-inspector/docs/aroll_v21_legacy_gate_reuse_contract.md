# A-Roll V21 Legacy Gate Reuse Contract

V21 may temporarily reuse selected legacy detector/gate helpers only as read-only evidence or validation functions.

Allowed read-only helpers:

- `aroll_cjk_short_repeat_gate`
- `aroll_adjacent_modifier_semantic_redundancy_gate`
- `aroll_final_repeat_gate`
- `aroll_hidden_audio_repeat_gate`
- `aroll_safe_cut_boundary_gate`
- `aroll_subtitle_style_integrity_gate`

Allowed behavior:

- Read V21 source graph, captions, final timeline, material write plan, or report-shaped rows.
- Return evidence, candidates, metrics, reports, or blockers.
- Leave `final_timeline`, `captions`, and `material_write_plan` unchanged.

Forbidden behavior:

- Modify final timeline, captions, EDL, or material write plan.
- Generate or apply repair proposals.
- Invoke downstream repair, repair applier, safe-cut resolver, or `material_text_rows`.
- Add writer fallback or validator repair.

Current status:

- Legacy helpers are wrapped by V21 evidence/validator layers.
- `ReadOnlyValidators` deep-copies compiler/render/writer outputs before validation and reports `VALIDATOR_MUTATED_INPUTS` if any validator mutates them.
- Future cleanup should migrate these helpers behind V21-native facades, but the current reuse is architecture-safe because it is read-only.
