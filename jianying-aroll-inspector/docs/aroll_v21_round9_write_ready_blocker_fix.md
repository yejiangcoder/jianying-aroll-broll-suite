# A-Roll V21 Round9 Write-Ready Blocker Fix

Status: IDEA-side code and offline tests only. No real UAT, write, commit, encrypt, or draft modification was performed.

## Final Timeline Pre-Emit Prefix Normalization

Round9 showed that boundary prefix containment could still appear after earlier decisions changed final adjacency:

```text
left = X
right = X + suffix
```

V21 now has a compiler pre-emit normalization pass before:

```text
final_timeline.json
-> captions
-> material_write_plan
-> validators
```

Safe cases drop the left final segment and keep the right complete segment. Target time is repacked so there is no gap or overlap.

Unsafe cases produce:

```text
BOUNDARY_PREFIX_CONTAINMENT_REQUIRES_HUMAN_REVIEW
```

This is compile-time generation logic, not validator repair and not downstream repair.

## Write-Allowed Aggregation

The run summary now separates:

```text
semantic_write_allowed
validator_write_allowed
write_allowed
READY_FOR_DISPOSABLE_WRITE_PRE_AUDIT
```

Final write readiness requires:

```text
semantic_write_allowed
and validator_write_allowed
and writer_fallback_count == 0
and no fatal blockers
```

Semantic decisions clearing DeepSeek blockers cannot bypass validator failures.
