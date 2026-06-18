# A-Roll V21 Round8 Write-Ready Follow-up

Status: IDEA-side code and offline regression only. No real UAT, write, commit, encrypt, or draft modification was performed.

## Boundary Prefix Containment

Round8 exposed final/hidden repeat validator blockers where adjacent units had this structure:

```text
left = X
right = X + suffix
```

V21 now handles safe cases before validation, in CandidateEvidence / DecisionPlan / FinalTimelineCompiler:

- evidence route: `boundary_prefix_containment`
- local decision: `drop_left_keep_right`
- compiler effect: drops the left whole edit unit and keeps the right complete unit

Unsafe cases, such as incompatible source segment boundaries, produce `BOUNDARY_PREFIX_CONTAINMENT_REQUIRES_HUMAN_REVIEW`.

Validators remain read-only and do not repair.

## Semantic Decisions JSON

V21 supports explicit semantic decision backfill with:

```text
--semantic-decisions-json <path>
```

PowerShell wrapper:

```text
-SemanticDecisionsJson "<path>"
```

Allowed decision values:

```text
keep_all
drop_left
drop_right
keep_right_drop_left
keep_left_drop_right
requires_human_review
```

Forbidden physical fields remain blocked:

```text
source_start_us
source_end_us
target_start_us
target_end_us
edl
final_edl
final_timeline
material_id
segment_id
draft_content
```

If all unresolved semantic clusters are covered and no decision requires human review, `semantic_unresolved_count` becomes `0`; write permission is still controlled by validators and postwrite gates.

## Native Monotonic Diagnostics

Native word source-time monotonic checks now reset at `source_segment_id` boundaries and emit specific diagnostics for same-segment regressions.
