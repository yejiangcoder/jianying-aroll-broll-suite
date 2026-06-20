from __future__ import annotations

from dataclasses import dataclass, field

from aroll_v21.ir.models import Blocker, CanonicalSourceGraph, DecisionPlan


@dataclass
class UnitSplitMaterialization:
    units_by_id: dict[str, object]
    drop_unit_ids: set[str] = field(default_factory=set)
    dropped_word_ids: set[str] = field(default_factory=set)
    decision_ids_by_word: dict[str, list[str]] = field(default_factory=dict)
    blockers: list[Blocker] = field(default_factory=list)


def materialize_drop_and_split_decisions(
    source_graph: CanonicalSourceGraph,
    decision_plan: DecisionPlan,
) -> UnitSplitMaterialization:
    units_by_id = {unit.unit_id: unit for unit in source_graph.edit_units}
    result = UnitSplitMaterialization(units_by_id=units_by_id)
    for decision in decision_plan.decisions:
        for unit_id in decision.drop_unit_ids:
            unit = units_by_id.get(unit_id)
            if unit is None:
                result.blockers.append(
                    Blocker(
                        code="DECISION_DROP_UNIT_NOT_FOUND",
                        message="decision references a missing edit unit",
                        layer="compiler",
                        context={"decision_id": decision.decision_id, "unit_id": unit_id},
                    )
                )
                continue
            if unit.cut_policy == "unsafe":
                result.blockers.append(
                    Blocker(
                        code="UNSAFE_EDIT_UNIT_DROP_BLOCKED",
                        message="compiler refuses to drop an unsafe edit unit",
                        layer="compiler",
                        context={"decision_id": decision.decision_id, "unit_id": unit_id},
                    )
                )
                continue
            result.drop_unit_ids.add(unit_id)
            for word_id in unit.word_ids:
                result.decision_ids_by_word.setdefault(word_id, []).append(decision.decision_id)

    for split in decision_plan.split_decisions:
        unit = units_by_id.get(split.unit_id)
        if unit is None:
            result.blockers.append(
                Blocker(
                    code="UNIT_SPLIT_UNIT_NOT_FOUND",
                    message="split decision references a missing edit unit",
                    layer="compiler",
                    context={"split_id": split.split_id, "unit_id": split.unit_id},
                )
            )
            continue
        if split.requires_human_review:
            result.blockers.append(
                Blocker(
                    code="UNIT_SPLIT_REQUIRES_HUMAN_REVIEW",
                    message="split decision requires human review before compilation",
                    layer="compiler",
                    context={"split_id": split.split_id, "unit_id": split.unit_id},
                )
            )
            continue
        if unit.cut_policy == "unsafe":
            result.blockers.append(
                Blocker(
                    code="UNIT_SPLIT_UNSAFE_BOUNDARY",
                    message="compiler refuses to split an unsafe edit unit",
                    layer="compiler",
                    context={"split_id": split.split_id, "unit_id": split.unit_id},
                )
            )
            continue
        unit_word_ids = set(unit.word_ids)
        drop_ids = set(split.drop_word_ids)
        keep_ids = set(split.keep_word_ids)
        if not drop_ids or not drop_ids <= unit_word_ids:
            result.blockers.append(
                Blocker(
                    code="UNIT_SPLIT_UNKNOWN_WORD",
                    message="split decision references unknown drop word ids",
                    layer="compiler",
                    context={"split_id": split.split_id, "drop_word_ids": split.drop_word_ids},
                )
            )
            continue
        if not keep_ids or not keep_ids <= unit_word_ids or drop_ids & keep_ids:
            result.blockers.append(
                Blocker(
                    code="UNIT_SPLIT_INVALID_KEEP_WORDS",
                    message="split decision has invalid keep word ids",
                    layer="compiler",
                    context={"split_id": split.split_id, "keep_word_ids": split.keep_word_ids},
                )
            )
            continue
        result.dropped_word_ids.update(drop_ids)
        for word_id in drop_ids:
            result.decision_ids_by_word.setdefault(word_id, []).append(split.split_id)
        for word_id in keep_ids:
            result.decision_ids_by_word.setdefault(word_id, []).append(split.split_id)
    return result
