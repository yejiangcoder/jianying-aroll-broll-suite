from __future__ import annotations

from typing import Any


def configure_engine_validation_dependencies(dependencies: dict[str, Any]) -> None:
    globals().update(dependencies)


def _semantic_payload_comparable_texts(self, payload: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for key in ("text", "raw_phrase", "phrase"):
        texts.append(str(payload.get(key) or ""))
    for variant in payload.get("variants") or []:
        if isinstance(variant, dict):
            texts.append(str(variant.get("text") or ""))
    for evidence in payload.get("local_evidence") or []:
        if not isinstance(evidence, dict):
            continue
        metadata = evidence.get("metadata") if isinstance(evidence.get("metadata"), dict) else {}
        candidate = metadata.get("candidate") if isinstance(metadata.get("candidate"), dict) else {}
        for key in ("raw_phrase", "phrase", "text"):
            texts.append(str(candidate.get(key) or ""))
    normalized: list[str] = []
    seen: set[str] = set()
    for text in texts:
        value = normalize_text(text)
        if len(value) < 2 or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _semantic_request_consistency_blockers(self, decision_plan, validator_report: dict[str, Any]) -> list[Blocker]:
    blockers: list[Blocker] = []
    payload_cluster_ids = {str(payload.get("cluster_id") or "") for payload in decision_plan.semantic_request_payloads}
    for blocker in decision_plan.blockers:
        if blocker.code == "SEMANTIC_DECISION_NOT_PROVIDED":
            cluster_id = str(blocker.context.get("cluster_id") or "")
            if cluster_id and cluster_id not in payload_cluster_ids:
                blockers.append(
                    Blocker(
                        code="INTERNAL_SEMANTIC_REQUEST_MISSING_FOR_DECISION_NOT_PROVIDED",
                        message="semantic decision missing blocker did not emit a matching semantic request payload",
                        layer="engine",
                        context={
                            "cluster_id": cluster_id,
                            "missing_request_for": "SEMANTIC_DECISION_NOT_PROVIDED",
                        },
                    )
                )
            continue
        if blocker.code == "UNIT_SPLIT_REQUIRES_HUMAN_REVIEW":
            cluster_id = str(blocker.context.get("cluster_id") or "")
            if cluster_id and cluster_id not in payload_cluster_ids:
                blockers.append(
                    Blocker(
                        code="INTERNAL_SEMANTIC_REQUEST_MISSING_FOR_UNIT_SPLIT",
                        message="unit split human review blocker did not emit a matching semantic request payload",
                        layer="engine",
                        context={
                            "cluster_id": cluster_id,
                            "missing_request_for": "UNIT_SPLIT_REQUIRES_HUMAN_REVIEW",
                        },
                    )
                )
    payload_texts = set()
    for payload in decision_plan.semantic_request_payloads:
        if str(payload.get("repeat_type") or "") != "modifier_redundancy":
            continue
        payload_texts.update(self._semantic_payload_comparable_texts(payload))
    for section_name in ("final_repeat_validator", "hidden_audio_repeat_validator"):
        section = validator_report.get(section_name) or {}
        for issue in section.get("blocking_issues") or []:
            if not isinstance(issue, dict):
                continue
            if str(issue.get("type") or issue.get("issue_type") or "") != "adjacent_modifier_semantic_redundancy":
                continue
            issue_texts = {
                normalize_text(str(issue.get("text") or "")),
                normalize_text(str(issue.get("phrase") or "")),
                normalize_text(str(issue.get("fragment_text") or "")),
            }
            issue_texts = {text for text in issue_texts if len(text) >= 2}
            if issue_texts and payload_texts & issue_texts:
                continue
            blockers.append(
                Blocker(
                    code="INTERNAL_SEMANTIC_REQUEST_MISSING_FOR_FATAL_REPEAT",
                    message="validator found semantic repeat fatal but no matching semantic request payload was emitted",
                    layer="engine",
                    context={
                        "validator_section": section_name,
                        "repeat_type": "modifier_redundancy",
                        "issue_type": "adjacent_modifier_semantic_redundancy",
                        "issue_text": str(issue.get("text") or issue.get("phrase") or ""),
                    },
                )
            )
    if not payload_cluster_ids:
        blockers.extend(self._final_repeat_validator_missing_request_blockers(validator_report))
    return blockers


def _final_repeat_validator_missing_request_blockers(self, validator_report: dict[str, Any]) -> list[Blocker]:
    blockers: list[Blocker] = []
    sections = (
        ("final_repeat_validator", "final_repeat_gate_passed"),
        ("hidden_audio_repeat_validator", "hidden_audio_repeat_gate_passed"),
    )
    for section_name, pass_key in sections:
        section = validator_report.get(section_name) or {}
        if section.get(pass_key, True):
            continue
        issues = [row for row in (section.get("blocking_issues") or []) if isinstance(row, dict)]
        candidates = [row for row in (section.get("final_target_repeat_candidates") or []) if isinstance(row, dict)]
        for issue in issues + candidates:
            issue_type = str(issue.get("type") or issue.get("issue_type") or issue.get("cluster_type") or "")
            if issue_type == "adjacent_modifier_semantic_redundancy":
                continue
            blockers.append(
                Blocker(
                    code="INTERNAL_SEMANTIC_REQUEST_MISSING_FOR_FINAL_REPEAT_VALIDATOR",
                    message="final repeat validator found a fatal repeat but no semantic request payload was emitted",
                    layer="engine",
                    context={
                        "validator_section": section_name,
                        "candidate_type": issue_type,
                        "left_text": str(issue.get("left_text") or issue.get("prev_text") or ""),
                        "right_text": str(issue.get("right_text") or issue.get("next_text") or ""),
                        "overlap": str(issue.get("overlap") or issue.get("phrase") or ""),
                        "repeated_phrase": str(issue.get("phrase") or issue.get("text") or ""),
                        "row_index": int(issue.get("row_index") or issue.get("left_index") or issue.get("subtitle_index") or 0),
                        "next_row_index": int(issue.get("next_row_index") or issue.get("right_index") or 0),
                        "severity": str(issue.get("severity") or issue.get("confidence") or ""),
                        "reason": str(issue.get("reason") or ""),
                    },
                )
            )
            break
    return blockers


def _blocked(
    self,
    *,
    source_graph=None,
    repeat_clusters=None,
    decision_plan=None,
    final_timeline=None,
    captions=None,
    material_write_plan=None,
    blockers: list[Blocker],
    summary: dict[str, Any],
) -> RunReport:
    return RunReport(
        status="blocked",
        source_graph=source_graph,
        repeat_clusters=repeat_clusters or [],
        decision_plan=decision_plan,
        final_timeline=final_timeline or [],
        captions=captions or [],
        material_write_plan=material_write_plan or {},
        validator_report={},
        postwrite_report={},
        blocker_report=BlockerReport(blocked=True, blockers=blockers, summary=summary),
        decision_trace=decision_plan.decision_trace if decision_plan else [],
    )


def _validator_blockers(self, report: dict[str, Any]) -> list[Blocker]:
    blockers: list[Blocker] = []
    emitted_codes: set[str] = set()
    mapping = {
        "final_repeat_validator": ("FINAL_REPEAT_VALIDATOR_FAILED", "final repeat validator failed"),
        "hidden_audio_repeat_validator": ("HIDDEN_AUDIO_REPEAT_VALIDATOR_FAILED", "hidden audio repeat validator failed"),
        "safe_cut_validator": ("SAFE_CUT_VALIDATOR_FAILED", "safe cut validator failed"),
        "subtitle_coverage_validator": ("SUBTITLE_COVERAGE_VALIDATOR_FAILED", "subtitle coverage validator failed"),
        "caption_alignment_gate": ("V21_CAPTION_SPOKEN_SPAN_ALIGNMENT_VALIDATOR", "caption spoken-span alignment validator failed"),
        "final_caption_visible_repeat_gate": ("V21_FINAL_CAPTION_VISIBLE_REPEAT_GATE_FAILED", "final visible caption repeat gate failed"),
        "subtitle_style_validator": ("SUBTITLE_STYLE_VALIDATOR_FAILED", "subtitle style validator failed"),
        "rough_cut_quality_validator": ("ROUGH_CUT_QUALITY_VALIDATOR_FAILED", "rough cut quality validator failed"),
        "postwrite_material_validator": ("POSTWRITE_MATERIAL_VALIDATOR_FAILED", "postwrite material validator failed"),
        "semantic_final_review_validator": ("SEMANTIC_FINAL_REVIEW_VALIDATOR_FAILED", "semantic final review validator failed"),
        "quality_gate_report": ("V21_QUALITY_GATE_FAILED", "quality gate failed"),
    }
    pass_keys = {
        "final_repeat_validator": "final_repeat_gate_passed",
        "hidden_audio_repeat_validator": "hidden_audio_repeat_gate_passed",
        "safe_cut_validator": "safe_cut_boundary_gate_passed",
        "subtitle_coverage_validator": "subtitle_coverage_gate_passed",
        "caption_alignment_gate": "gate_passed",
        "final_caption_visible_repeat_gate": "gate_passed",
        "subtitle_style_validator": "prewrite_style_gate_ok",
        "rough_cut_quality_validator": "rough_cut_quality_gate_passed",
        "postwrite_material_validator": "postwrite_material_gate_ok",
        "semantic_final_review_validator": "semantic_final_review_validator_passed",
        "quality_gate_report": "gate_passed",
    }
    for section, (code, message) in mapping.items():
        payload = report.get(section) or {}
        if not payload.get(pass_keys[section], False):
            blockers.append(Blocker(code=code, message=message, layer="validate", context={"section": section, "report": payload}))
            emitted_codes.add(code)
            for detail_code in payload.get("blocker_codes") or []:
                detail = str(detail_code or "")
                if not detail or detail in emitted_codes:
                    continue
                detail_context = {"section": section}
                unresolved_ids = [str(item) for item in payload.get("unresolved_issue_ids") or [] if str(item)]
                if not unresolved_ids:
                    semantic_payload = report.get("semantic_final_review_validator") or {}
                    unresolved_ids = [str(item) for item in semantic_payload.get("unresolved_issue_ids") or [] if str(item)]
                if unresolved_ids:
                    detail_context["cluster_id"] = unresolved_ids[0]
                blockers.append(
                    Blocker(
                        code=detail,
                        message="validator subgate failed",
                        layer="validate",
                        context=detail_context,
                    )
                )
                emitted_codes.add(detail)
    if not report.get("validators_read_only"):
        blockers.append(Blocker("VALIDATOR_MUTATED_INPUTS", "validator changed compiler/render/writer objects", "validate"))
    return blockers


def _attach_final_caption_visible_repeat_gate(
    self,
    validator_report: dict[str, Any],
    captions,
) -> dict[str, Any]:
    report = dict(validator_report)
    visible_repeat_gate = build_final_caption_visible_repeat_gate(list(captions))
    repair_report = report.get("final_visible_caption_repair_report")
    if isinstance(repair_report, dict) and bool(repair_report.get("final_visible_repair_attempted")):
        visible_repeat_gate = dict(visible_repeat_gate)
        visible_repeat_gate["final_visible_repair_success"] = bool(repair_report.get("final_visible_repair_success"))
        visible_repeat_gate["final_visible_repair_unresolved_count"] = len(list(repair_report.get("final_visible_repair_unresolved") or []))
        visible_repeat_gate["final_visible_repair_final_timeline_counts"] = dict(repair_report.get("final_visible_repair_final_timeline_counts") or {})
        visible_repeat_gate["final_visible_effective_caption_count"] = int(repair_report.get("final_visible_effective_caption_count") or 0)
        visible_repeat_gate["caption_only_materialized_merge_count"] = int(repair_report.get("caption_only_materialized_merge_count") or 0)
        visible_repeat_gate["caption_only_consumed_caption_ids"] = list(repair_report.get("caption_only_consumed_caption_ids") or [])
        visible_repeat_gate["caption_only_materialized_merges"] = list(repair_report.get("caption_only_materialized_merges") or [])
    if isinstance(repair_report, dict) and bool(repair_report.get("final_visible_repair_attempted")) and not bool(repair_report.get("final_visible_repair_success")):
        blocker_codes = list(visible_repeat_gate.get("blocker_codes") or [])
        for code in ("V21_FINAL_CAPTION_VISIBLE_REPEAT_GATE_FAILED", "V21_FINAL_VISIBLE_REPAIR_UNRESOLVED"):
            if code not in blocker_codes:
                blocker_codes.append(code)
        visible_repeat_gate["gate_passed"] = False
        visible_repeat_gate["blocker_codes"] = blocker_codes
    report["final_caption_visible_repeat_gate"] = visible_repeat_gate
    previous_quality = report.get("quality_gate_report")
    quality_ok = True
    if isinstance(previous_quality, dict):
        base_ok = bool(previous_quality.get("ready_for_user_manual_qc_preconditions_passed", report.get("validator_report_ok")))
        quality_gate = build_quality_gate_report(
            effective_speed_gate=_normalize_effective_speed_prewrite_placeholder(previous_quality.get("effective_speed_gate")),
            final_repeat_convergence_gate=report.get("final_repeat_convergence_gate"),
            final_caption_visible_repeat_gate=visible_repeat_gate,
            semantic_adjudication_gate=report.get("semantic_final_review_validator"),
            visual_pacing_gate=report.get("visual_pacing_gate"),
            caption_alignment_gate=report.get("caption_alignment_gate"),
            ready_for_user_manual_qc_preconditions_passed=base_ok and bool(visible_repeat_gate.get("gate_passed")),
        )
        report["quality_gate_report"] = quality_gate
        quality_ok = bool(quality_gate.get("gate_passed"))
    report["validator_report_ok"] = bool(report.get("validator_report_ok")) and bool(visible_repeat_gate.get("gate_passed")) and quality_ok
    return report
