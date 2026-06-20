from __future__ import annotations

from typing import Any

from aroll_v21.ir.models import RepeatCluster


def decision_trace_row(
    cluster: RepeatCluster,
    *,
    route: str,
    output_decision: str = "",
    blocker: str = "",
    reason: str = "",
) -> dict[str, Any]:
    row = {
        "cluster_id": cluster.cluster_id,
        "repeat_type": cluster.repeat_type,
        "evidence_source": ",".join(sorted({evidence.evidence_type for evidence in cluster.evidence})),
        "route": route,
        "input_units": [unit.unit_id for unit in cluster.variants],
        "output_decision": output_decision,
        "blocker": blocker,
        "reason": reason,
    }
    if route == "boundary_prefix_containment" and len(cluster.variants) >= 2:
        row.update(
            {
                "left_text": cluster.variants[0].text,
                "right_text": cluster.variants[-1].text,
                "decision": "drop_left_keep_right",
                "source": "local_policy",
            }
        )
    if route == "self_repair_aborted_phrase" and len(cluster.variants) >= 2:
        row.update(
            {
                "left_text": cluster.variants[0].text,
                "right_text": cluster.variants[-1].text,
                "decision": "drop_left_keep_right",
                "source": "local_policy",
                "applied": True,
            }
        )
    return row
