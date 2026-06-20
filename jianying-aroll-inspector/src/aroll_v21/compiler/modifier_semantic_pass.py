from __future__ import annotations

from typing import Any


def configure_compiler_dependencies(dependencies: dict[str, Any]) -> None:
    globals().update(dependencies)


def _final_modifier_redundancy_semantic_pass(
    self,
    segments: list[FinalTimelineSegment],
    source_graph: CanonicalSourceGraph,
    decision_plan: DecisionPlan,
) -> tuple[list[FinalTimelineSegment], list[Blocker], bool]:
    if not segments:
        return segments, [], False
    word_lookup = {word.word_id: word for word in source_graph.words}
    current = list(segments)
    blockers: list[Blocker] = []
    unresolved_ids = set(decision_plan.modifier_redundancy_unresolved_cluster_ids)
    newly_unresolved_ids: set[str] = set()
    accepted_ids = set(decision_plan.modifier_redundancy_accepted_cluster_ids)
    changed = False
    candidates = self._final_modifier_candidates(current)
    for offset, candidate in enumerate(candidates):
        existing_payload_cluster_id = self._existing_modifier_payload_cluster_id(decision_plan, candidate)
        if existing_payload_cluster_id:
            unresolved_ids.add(existing_payload_cluster_id)
            continue
        cluster_id = self._modifier_cluster_id(decision_plan, offset)
        row = self._semantic_decision_row(decision_plan, cluster_id)
        if row is None:
            if cluster_id not in unresolved_ids:
                unresolved_ids.add(cluster_id)
                newly_unresolved_ids.add(cluster_id)
                self._append_modifier_semantic_request(decision_plan, cluster_id, candidate)
                decision_plan.blockers.append(
                    Blocker(
                        code="FINAL_MODIFIER_REDUNDANCY_SEMANTIC_DECISION_REQUIRED",
                        message="final modifier redundancy requires explicit semantic decision",
                        layer="decision",
                        severity="write_blocker",
                        context={
                            "cluster_id": cluster_id,
                            "repeat_type": "modifier_redundancy",
                            "type": "single_variant_modifier_redundancy",
                            "allows_dry_run_discovery": True,
                        },
                    )
                )
            continue
        forbidden = sorted(FORBIDDEN_DEEPSEEK_FIELDS & set(row.keys()))
        if forbidden:
            blockers.append(
                Blocker(
                    code="SEMANTIC_DECISION_HAS_PHYSICAL_FIELDS",
                    message="semantic decisions json contains forbidden physical timeline/material fields",
                    layer="compiler",
                    context={"cluster_id": cluster_id, "forbidden_fields": forbidden},
                )
            )
            continue
        decision = str(row.get("decision") or "").strip()
        if decision == "keep_all":
            if cluster_id not in unresolved_ids:
                unresolved_ids.add(cluster_id)
                newly_unresolved_ids.add(cluster_id)
                self._append_modifier_semantic_request(decision_plan, cluster_id, candidate)
            decision_plan.blockers.append(
                Blocker(
                    code="V21_FATAL_MODIFIER_REDUNDANCY_UNRESOLVED",
                    message="fatal modifier redundancy cannot be accepted with keep_all",
                    layer="decision",
                    severity="write_blocker",
                    context={"cluster_id": cluster_id, "repeat_type": "modifier_redundancy", "decision": "keep_all"},
                )
            )
            decision_plan.decision_trace.append(
                {
                    "route": "final_modifier_redundancy",
                    "cluster_id": cluster_id,
                    "decision": "keep_all_rejected",
                    "applied": False,
                    "source": "SemanticDecisionsJson",
                    "validator_effect": "fatal_modifier_redundancy_unresolved",
                }
            )
            continue
        if decision == "requires_human_review" or bool(row.get("requires_human_review")):
            if cluster_id not in unresolved_ids:
                unresolved_ids.add(cluster_id)
                newly_unresolved_ids.add(cluster_id)
                self._append_modifier_semantic_request(decision_plan, cluster_id, candidate)
                decision_plan.blockers.append(
                    Blocker(
                        code="FINAL_MODIFIER_REDUNDANCY_REQUIRES_HUMAN_REVIEW",
                        message="final modifier redundancy decision requires human review",
                        layer="decision",
                        severity="write_blocker",
                        context={"cluster_id": cluster_id},
                    )
                )
            continue
        if decision != "drop_redundant_modifier":
            blockers.append(
                Blocker(
                    code="SEMANTIC_DECISION_SCHEMA_INVALID",
                    message="semantic decisions json uses an unsupported modifier redundancy decision",
                    layer="compiler",
                    context={"cluster_id": cluster_id, "decision": decision},
                )
            )
            continue
        segment_index = int(candidate.get("segment_index") or 0) - 1
        if not (0 <= segment_index < len(current)):
            blockers.append(
                Blocker(
                    code="MODIFIER_REDUNDANCY_WORD_BINDING_MISSING",
                    message="modifier redundancy candidate does not map to a final segment",
                    layer="compiler",
                    context={"cluster_id": cluster_id},
                )
            )
            continue
        updated, binding_blocker = self._drop_redundant_modifier_from_segment(current[segment_index], candidate, word_lookup, cluster_id)
        if binding_blocker:
            blockers.append(binding_blocker)
            continue
        current[segment_index] = updated
        changed = True
        decision_plan.decision_trace.append(
            {
                "route": "final_modifier_redundancy",
                "stage": "final_timeline_pre_emit",
                "cluster_id": cluster_id,
                "decision": "drop_redundant_modifier",
                "applied": True,
                "source": "SemanticDecisionsJson",
                "reason": str(row.get("reason") or "drop redundant modifier before same head"),
            }
        )
    self._set_plan_list(decision_plan.modifier_redundancy_unresolved_cluster_ids, sorted(unresolved_ids))
    self._set_plan_list(decision_plan.modifier_redundancy_accepted_cluster_ids, sorted(accepted_ids))
    if unresolved_ids:
        object.__setattr__(decision_plan, "semantic_unresolved_count", int(decision_plan.semantic_unresolved_count) + len(newly_unresolved_ids))
        object.__setattr__(decision_plan, "requires_human_review", True)
        object.__setattr__(decision_plan, "write_allowed", False)
        object.__setattr__(decision_plan, "dry_run_continued_for_discovery", True)
    if changed:
        current = self._repack_target_timeline(current)
    return current, blockers, changed


def _existing_modifier_payload_cluster_id(self, decision_plan: DecisionPlan, candidate: dict[str, object]) -> str:
    candidate_texts = {
        normalize_text(str(candidate.get("text") or "")),
        normalize_text(str(candidate.get("phrase") or "")),
    }
    candidate_texts = {text for text in candidate_texts if text}
    if not candidate_texts:
        return ""
    for payload in decision_plan.semantic_request_payloads:
        if str(payload.get("repeat_type") or "") != "modifier_redundancy":
            continue
        payload_texts = {
            normalize_text(str(payload.get("text") or "")),
            normalize_text(str(payload.get("phrase") or "")),
        }
        for evidence in payload.get("local_evidence") or []:
            if not isinstance(evidence, dict):
                continue
            metadata = evidence.get("metadata") if isinstance(evidence.get("metadata"), dict) else {}
            payload_candidate = metadata.get("candidate") if isinstance(metadata.get("candidate"), dict) else {}
            payload_texts.add(normalize_text(str(payload_candidate.get("raw_phrase") or "")))
            payload_texts.add(normalize_text(str(payload_candidate.get("phrase") or "")))
        if candidate_texts & {text for text in payload_texts if text}:
            return str(payload.get("cluster_id") or "")
    return ""


def _final_modifier_candidates(self, segments: list[FinalTimelineSegment]) -> list[dict[str, object]]:
    rows = [
        {
            "fragment_id": segment.segment_id,
            "fragment_text": segment.text,
            "text": segment.text,
        }
        for segment in segments
    ]
    candidates = []
    for candidate in detect_adjacent_modifier_semantic_redundancy(rows):
        if str(candidate.get("severity") or "fatal") != "fatal":
            continue
        if str(candidate.get("scope") or "") != "intra_subtitle":
            continue
        row_index = int(candidate.get("row_index") or 0)
        if not (1 <= row_index <= len(segments)):
            continue
        row = dict(candidate)
        row["segment_index"] = row_index
        row["segment_id"] = segments[row_index - 1].segment_id
        row["word_ids"] = list(segments[row_index - 1].word_ids)
        row["source_start_us"] = int(segments[row_index - 1].source_start_us)
        row["source_end_us"] = int(segments[row_index - 1].source_end_us)
        row["target_start_us"] = int(segments[row_index - 1].target_start_us)
        row["target_end_us"] = int(segments[row_index - 1].target_end_us)
        candidates.append(row)
    return candidates


def _modifier_cluster_id(self, decision_plan: DecisionPlan, offset: int) -> str:
    expected = f"repeat_{2000 + offset:06d}"
    for row in decision_plan.semantic_decision_rows:
        if str(row.get("cluster_id") or "") == expected:
            return expected
    existing_ids = {
        str(row.get("cluster_id") or "")
        for row in decision_plan.semantic_request_payloads
    }
    existing_ids.update(decision_plan.modifier_redundancy_unresolved_cluster_ids)
    existing_ids.update(decision_plan.modifier_redundancy_accepted_cluster_ids)
    candidate = expected
    while candidate in existing_ids:
        offset += 1
        candidate = f"repeat_{2000 + offset:06d}"
    return candidate


def _semantic_decision_row(self, decision_plan: DecisionPlan, cluster_id: str) -> dict[str, object] | None:
    missing: dict[str, object] | None = None
    for row in decision_plan.semantic_decision_rows:
        if str(row.get("cluster_id") or "") == cluster_id:
            return row
    if self.baseline_policy.is_enabled(decision_plan):
        return self.baseline_policy.decision_for_missing_cluster(
            cluster_id,
            cluster_type="modifier_redundancy",
            context={
                "reason": "deterministic baseline refuses fatal modifier redundancy; semantic repair/drop required",
                "confidence": 0.65,
            },
        )
    return missing


def _deterministic_baseline_enabled(self, decision_plan: DecisionPlan) -> bool:
    return self.baseline_policy.is_enabled(decision_plan)


def _append_modifier_semantic_request(
    self,
    decision_plan: DecisionPlan,
    cluster_id: str,
    candidate: dict[str, object],
) -> None:
    existing = {str(row.get("cluster_id") or "") for row in decision_plan.semantic_request_payloads}
    if cluster_id in existing:
        return
    left_modifier = normalize_text(str(candidate.get("left_modifier") or ""))
    right_modifier = normalize_text(str(candidate.get("right_modifier") or ""))
    decision_plan.semantic_request_payloads.append(
        {
            "issue_id": cluster_id,
            "cluster_id": cluster_id,
            "issue_type": "modifier_redundancy",
            "severity": "fatal",
            "repeat_type": "modifier_redundancy",
            "type": "single_variant_modifier_redundancy",
            "text": str(candidate.get("text") or candidate.get("phrase") or ""),
            "text_before": str(candidate.get("text") or candidate.get("phrase") or ""),
            "text_after": "",
            "candidate_segment_ids": [str(candidate.get("segment_id") or "")],
            "candidate_caption_ids": [],
            "word_ids": [str(word_id) for word_id in candidate.get("word_ids") or [] if str(word_id)],
            "source_start_us": int(candidate.get("source_start_us") or 0),
            "source_end_us": int(candidate.get("source_end_us") or 0),
            "target_start_us": int(candidate.get("target_start_us") or 0),
            "target_end_us": int(candidate.get("target_end_us") or 0),
            "modifiers": [
                {"role": "redundant_modifier", "text": f"{left_modifier}的", "position": "left"},
                {"role": "kept_modifier", "text": f"{right_modifier}的", "position": "right"},
            ],
            "head": normalize_text(str(candidate.get("head_text") or "")),
            "allowed_decisions": [
                "drop_redundant_modifier",
                "requires_human_review",
                "no_decision",
            ],
            "recommended_action": "repair_text",
            "suggested_for_rough_cut": "drop_redundant_modifier",
            "why_local_policy_cannot_decide": "final timeline modifier redundancy requires explicit repair/drop; keep_all is forbidden",
            "local_context": {
                "candidate": dict(candidate),
                "final_segment_id": str(candidate.get("segment_id") or ""),
            },
            "local_evidence": [
                {
                    "evidence_type": "adjacent_modifier_semantic_redundancy",
                    "reason": str(candidate.get("reason") or ""),
                    "metadata": {
                        "candidate": {
                            "type": "single_variant_modifier_redundancy",
                            "raw_phrase": str(candidate.get("phrase") or ""),
                            "modifiers": [
                                {"role": "redundant_modifier", "text": f"{left_modifier}的", "position": "left"},
                                {"role": "kept_modifier", "text": f"{right_modifier}的", "position": "right"},
                            ],
                            "head": normalize_text(str(candidate.get("head_text") or "")),
                        }
                    },
                }
            ],
            "required_decision_schema": {
                "decision": "drop_redundant_modifier | requires_human_review | no_decision",
                "reason": "",
                "confidence": 0.0,
                "requires_human_review": False,
            },
            "fatal_modifier_redundancy_keep_all_allowed": False,
        }
    )
    decision_plan.decision_trace.append(
        {
            "route": "final_modifier_redundancy",
            "stage": "final_timeline_pre_emit",
            "cluster_id": cluster_id,
            "decision": "semantic_request_emitted",
            "applied": True,
            "reason": "final timeline contains single-variant modifier redundancy requiring explicit decision",
        }
    )


def _drop_redundant_modifier_from_segment(
    self,
    segment: FinalTimelineSegment,
    candidate: dict[str, object],
    word_lookup: dict[str, object],
    cluster_id: str,
) -> tuple[FinalTimelineSegment, Blocker | None]:
    left_modifier = normalize_text(str(candidate.get("left_modifier") or ""))
    redundant_text = f"{left_modifier}的" if left_modifier else ""
    segment_text = normalize_text(segment.text)
    start_char = segment_text.find(redundant_text)
    if not redundant_text or start_char < 0:
        return segment, Blocker(
            code="MODIFIER_REDUNDANCY_WORD_BINDING_MISSING",
            message="could not locate redundant modifier text inside final segment",
            layer="compiler",
            context={"cluster_id": cluster_id, "segment_id": segment.segment_id},
        )
    drop_word_ids = self._word_ids_for_char_span(segment, word_lookup, start_char, start_char + len(redundant_text))
    if not drop_word_ids:
        return segment, Blocker(
            code="MODIFIER_REDUNDANCY_WORD_BINDING_MISSING",
            message="could not bind redundant modifier to whole word ids",
            layer="compiler",
            context={"cluster_id": cluster_id, "segment_id": segment.segment_id},
        )
    drop_set = set(drop_word_ids)
    kept_words = [word_lookup[word_id] for word_id in segment.word_ids if word_id in word_lookup and word_id not in drop_set]
    if not kept_words:
        return segment, Blocker(
            code="MODIFIER_REDUNDANCY_WORD_BINDING_MISSING",
            message="modifier redundancy decision would drop the entire segment",
            layer="compiler",
            context={"cluster_id": cluster_id, "segment_id": segment.segment_id},
        )
    return replace(
        segment,
        source_start_us=int(getattr(kept_words[0], "source_start_us")),
        source_end_us=int(getattr(kept_words[-1], "source_end_us")),
        word_ids=[str(getattr(word, "word_id")) for word in kept_words],
        text="".join(str(getattr(word, "text")) for word in kept_words),
        decision_ids=sorted(set(segment.decision_ids + [cluster_id, "drop_redundant_modifier"])),
        spoken_source_start_us=None,
        spoken_source_end_us=None,
        clip_source_start_us=None,
        clip_source_end_us=None,
        lead_handle_us=0,
        tail_handle_us=0,
    ), None


def _word_ids_for_char_span(
    self,
    segment: FinalTimelineSegment,
    word_lookup: dict[str, object],
    start_char: int,
    end_char: int,
) -> list[str]:
    cursor = 0
    selected: list[str] = []
    for word_id in segment.word_ids:
        word = word_lookup.get(word_id)
        text = normalize_text(str(getattr(word, "text", "") or ""))
        if not text:
            continue
        word_start = cursor
        word_end = cursor + len(text)
        if start_char <= word_start and word_end <= end_char:
            selected.append(word_id)
        elif word_start < end_char and start_char < word_end:
            partial_overlap: list[str] = []
            return partial_overlap
        cursor = word_end
    return selected


def _set_plan_list(self, target: list[str], values: list[str]) -> None:
    target.clear()
    target.extend(values)
