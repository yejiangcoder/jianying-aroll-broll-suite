from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from aroll_word_edl_builder import (
    SOURCE_DURATION_US,
    build_word_level_edl,
    text_from_words,
    words_by_subtitle,
)
from aroll_word_subtitle_plan import summarize_subtitle_plan, validate_subtitle_plan


DEFAULT_PHASE4A_DIR = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4_diagnostics_20260614_171206")
DEFAULT_SUBTITLES = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_inspect_20260614_111146\subtitle_timeline.json")
DEFAULT_SCRIPT = Path(r"D:\idea-project\Jackson WorldViews\src\main\java\jackson\worldviews\content\shoortvideoScript\S16\S16正文脚本\S16-3-嘉豪.md")
DEFAULT_RUNTIME = Path(r"D:\video tools\jianying-aroll-inspector\runtime")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def sec(us: int | float) -> float:
    return round(float(us) / 1_000_000, 3)


def by_uid(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("subtitle_uid") or ""): row for row in rows}


def decision_summary(decision_rows: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in decision_rows:
        key = str(row.get("decision") or "unknown")
        out[key] = out.get(key, 0) + 1
    return out


def find_subtitle_by_text(subtitles: list[dict[str, Any]], needle: str) -> dict[str, Any] | None:
    for row in subtitles:
        if needle in str(row.get("subtitle_text") or ""):
            return row
    return None


def fragment_for_source(plan: list[dict[str, Any]], uid: str) -> list[dict[str, Any]]:
    return [row for row in plan if str(row.get("source_subtitle_uid") or "") == uid]


def regression_results(
    subtitles: list[dict[str, Any]],
    subtitle_plan: list[dict[str, Any]],
    decision_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    text_by_uid = {str(row.get("subtitle_uid") or ""): str(row.get("subtitle_text") or "") for row in subtitles}
    drop_uids = {
        str(uid)
        for row in decision_rows
        if row.get("decision") == "drop"
        for uid in (row.get("drop_uids") or [])
    }
    micro_by_uid = {
        str(row.get("subtitle_uid") or ""): str(row.get("keep_text") or "")
        for row in decision_rows
        if row.get("decision") == "micro_cleanup"
    }

    pronoun_left = find_subtitle_by_text(subtitles, "你可以嘲笑她们虚伪")
    pronoun_right = find_subtitle_by_text(subtitles, "你可以嘲笑他们虚伪")
    pit = find_subtitle_by_text(subtitles, "看就看到有人想爬出粪坑")
    young_bad = find_subtitle_by_text(subtitles, "人家年少的时候你就把他当成寻")
    young_restart = find_subtitle_by_text(subtitles, "人家人家年少的时候")
    young_full = find_subtitle_by_text(subtitles, "你就把他当成寻找优越感的弱智对象")
    step = find_subtitle_by_text(subtitles, "随意的肆意的踩踏")

    same_phrase_targets = [
        "你跪在地上你跪在地上叫大佬",
        "评论区评论区也全是哇塞",
        "给给老子从坟墓里面挖出来",
        "重新上重新上桌重新上桌",
    ]
    same_phrase_processed = 0
    same_phrase_details = []
    for text in same_phrase_targets:
        row = find_subtitle_by_text(subtitles, text)
        uid = str((row or {}).get("subtitle_uid") or "")
        keep = micro_by_uid.get(uid, "")
        if keep:
            same_phrase_processed += 1
        same_phrase_details.append({"source_text": text, "subtitle_uid": uid, "final_text": keep})

    return {
        "pronoun_tamen_xuwei": {
            "drop": text_by_uid.get(str((pronoun_left or {}).get("subtitle_uid") or ""), ""),
            "keep": text_by_uid.get(str((pronoun_right or {}).get("subtitle_uid") or ""), ""),
            "drop_uid": str((pronoun_left or {}).get("subtitle_uid") or ""),
            "keep_uid": str((pronoun_right or {}).get("subtitle_uid") or ""),
            "drop_applied": str((pronoun_left or {}).get("subtitle_uid") or "") in drop_uids,
        },
        "pit_prefix": {
            "source": str((pit or {}).get("subtitle_text") or ""),
            "final_text": micro_by_uid.get(str((pit or {}).get("subtitle_uid") or ""), ""),
        },
        "young_youyuegan": {
            "preserved": ["人家年少的时候", "寻找优越感", "弱智对象"],
            "removed_fragments": ["你就把他当成寻", "人家人家年少的时候"],
            "bad_uid": str((young_bad or {}).get("subtitle_uid") or ""),
            "restart_uid": str((young_restart or {}).get("subtitle_uid") or ""),
            "full_uid": str((young_full or {}).get("subtitle_uid") or ""),
            "bad_final_text": micro_by_uid.get(str((young_bad or {}).get("subtitle_uid") or ""), ""),
            "restart_dropped": str((young_restart or {}).get("subtitle_uid") or "") in drop_uids,
            "full_kept": bool(fragment_for_source(subtitle_plan, str((young_full or {}).get("subtitle_uid") or ""))),
        },
        "suiyi_zhaping": {
            "source": str((step or {}).get("subtitle_text") or ""),
            "final_text": micro_by_uid.get(str((step or {}).get("subtitle_uid") or ""), ""),
        },
        "same_subtitle_repeated_phrase": {
            "processed_count": same_phrase_processed,
            "details": same_phrase_details,
        },
    }


def top_gap_summary(gap_cut_plan: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    top = sorted(gap_cut_plan, key=lambda row: int(row.get("cut_duration_us") or 0), reverse=True)[:limit]
    return [
        {
            "gap_id": row.get("gap_id"),
            "gap_type": row.get("gap_type"),
            "gap_duration_s": sec(int(row.get("gap_duration_us") or 0)),
            "cut_duration_s": sec(int(row.get("cut_duration_us") or 0)),
            "kept_gap_s": sec(int(row.get("kept_gap_us") or 0)),
            "left_text": row.get("left_text"),
            "right_text": row.get("right_text"),
            "reason": row.get("reason"),
        }
        for row in top
    ]


def write_drop_review(path: Path, subtitles: list[dict[str, Any]], decision_rows: list[dict[str, Any]]) -> None:
    text_by_uid = {str(row.get("subtitle_uid") or ""): str(row.get("subtitle_text") or "") for row in subtitles}
    lines = ["# Word-level Drop / Micro Cleanup Review", ""]
    for row in decision_rows:
        decision = row.get("decision")
        lines.append(f"## {decision} | {row.get('source_cluster')}")
        if decision == "drop":
            for uid in row.get("drop_uids") or []:
                lines.append(f"- Drop `{uid}`: {text_by_uid.get(str(uid), '')}")
            keep_uid = str(row.get("keep_uid") or "")
            if keep_uid:
                lines.append(f"- Keep `{keep_uid}`: {text_by_uid.get(keep_uid, '')}")
        elif decision == "micro_cleanup":
            uid = str(row.get("subtitle_uid") or "")
            lines.append(f"- Source `{uid}`: {text_by_uid.get(uid, '')}")
            lines.append(f"- Final: {row.get('keep_text')}")
        else:
            uid = str(row.get("subtitle_uid") or "")
            lines.append(f"- Review `{uid}`: {text_by_uid.get(uid, '')}")
            lines.append(f"- Reason: {row.get('reason')}")
        lines.append(f"- Reason: {row.get('reason')}")
        lines.append("")
    path.write_text("\n".join(lines), "utf-8")


def write_gap_review(path: Path, gap_cut_plan: list[dict[str, Any]]) -> None:
    lines = ["# Word Gap Cut Review", ""]
    for row in sorted(gap_cut_plan, key=lambda item: int(item.get("cut_duration_us") or 0), reverse=True)[:80]:
        lines.extend(
            [
                f"## {row.get('gap_id')} | {row.get('gap_type')} | cut {sec(int(row.get('cut_duration_us') or 0))}s",
                "",
                f"- Gap: {sec(int(row.get('gap_duration_us') or 0))}s",
                f"- Kept gap: {sec(int(row.get('kept_gap_us') or 0))}s",
                f"- Left: {row.get('left_text')}",
                f"- Right: {row.get('right_text')}",
                f"- Reason: {row.get('reason')}",
                "",
            ]
        )
    path.write_text("\n".join(lines), "utf-8")


def write_human_focus(
    path: Path,
    regressions: dict[str, Any],
    gap_cut_plan: list[dict[str, Any]],
    decision_rows: list[dict[str, Any]],
) -> None:
    lines = [
        "# Word-level Human Review Focus",
        "",
        "## 1. 你可以嘲笑她们/他们虚伪",
        f"- Drop: {regressions['pronoun_tamen_xuwei']['drop']}",
        f"- Keep: {regressions['pronoun_tamen_xuwei']['keep']}",
        f"- Drop applied: {regressions['pronoun_tamen_xuwei']['drop_applied']}",
        "",
        "## 2. 看 / 就看到有人想爬出粪坑",
        f"- Final: {regressions['pit_prefix']['final_text']}",
        "",
        "## 3. 人家年少的时候 / 寻找优越感",
        f"- Preserved: {', '.join(regressions['young_youyuegan']['preserved'])}",
        f"- Removed fragments: {', '.join(regressions['young_youyuegan']['removed_fragments'])}",
        "",
        "## 4. 随意的 / 肆意的踩踏",
        f"- Final: {regressions['suiyi_zhaping']['final_text']}",
        "",
        "## 5. 你跪在地上叫大佬",
        "- Expected final: 你跪在地上叫大佬",
        "",
        "## 6. 最大 20 个 word gap cuts",
        "",
    ]
    for row in top_gap_summary(gap_cut_plan, 20):
        lines.append(f"- `{row['gap_id']}` {row['gap_type']} cut={row['cut_duration_s']}s | {row['left_text']} -> {row['right_text']}")
    lines.extend(["", "## 7. 语义风险最高的 10 个 drop/micro cleanup", ""])
    risk_rows = [
        row
        for row in decision_rows
        if row.get("decision") in {"drop", "micro_cleanup", "manual_review"}
    ][:10]
    for row in risk_rows:
        lines.append(f"- `{row.get('source_cluster')}` {row.get('decision')} {row.get('subtitle_uid') or row.get('drop_uids')} reason={row.get('reason')}")
    path.write_text("\n".join(lines), "utf-8")


def build_report(
    run_dir: Path,
    inputs: dict[str, str],
    subtitles: list[dict[str, Any]],
    words: list[dict[str, Any]],
    edl: list[dict[str, Any]],
    subtitle_plan: list[dict[str, Any]],
    gap_cut_plan: list[dict[str, Any]],
    guard_report: dict[str, Any],
    decision_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    estimated_final = sum(int(row.get("target_duration_us") or 0) for row in edl)
    gap_cut_total = sum(int(row.get("cut_duration_us") or 0) for row in gap_cut_plan)
    warnings = validate_subtitle_plan(subtitle_plan)
    warnings.extend(
        warning
        for clip in edl
        for warning in (clip.get("warnings") or [])
    )
    regressions = regression_results(subtitles, subtitle_plan, decision_rows)
    subtitle_summary = summarize_subtitle_plan(subtitle_plan)
    report = {
        "inputs": inputs,
        "source_duration_us": SOURCE_DURATION_US,
        "estimated_final_duration_us": estimated_final,
        "estimated_removed_duration_us": max(0, SOURCE_DURATION_US - estimated_final),
        "word_clip_count": len(edl),
        "subtitle_fragment_count": len(subtitle_plan),
        "drop_decision_count": sum(1 for row in decision_rows if row.get("decision") == "drop"),
        "micro_cleanup_count": sum(1 for row in decision_rows if row.get("decision") == "micro_cleanup"),
        "manual_review_count": sum(1 for row in decision_rows if row.get("decision") == "manual_review"),
        "word_gap_cut_count": len(gap_cut_plan),
        "estimated_removed_word_gap_us": gap_cut_total,
        "subtitle_plan_summary": subtitle_summary,
        "regression_results": regressions,
        "word_gap_results": {
            "gt_100ms_word_gaps": len(gap_cut_plan),
            "planned_gap_cut_count": len(gap_cut_plan),
            "estimated_removed_word_gap_us": gap_cut_total,
            "top_10": top_gap_summary(gap_cut_plan, 10),
        },
        "semantic_guard": {
            "blocked_full_drops_count": len(guard_report.get("blocked_full_drops") or []),
            "converted_to_micro_cleanup_count": len(guard_report.get("converted_to_micro_cleanup") or []),
            "force_keep_count": len(guard_report.get("force_keep") or []),
            "manual_review_count": len(guard_report.get("manual_review") or []),
        },
        "decision_summary": decision_summary(decision_rows),
        "word_count": len(words),
        "subtitle_count": len(subtitles),
        "fatal_reasons": [],
        "warnings": warnings,
        "outputs": {
            "word_level_aroll_edl": str(run_dir / "word_level_aroll_edl.json"),
            "word_level_subtitle_plan": str(run_dir / "word_level_subtitle_plan.json"),
            "word_gap_cut_plan": str(run_dir / "word_gap_cut_plan.json"),
            "semantic_guard_dryrun_report": str(run_dir / "semantic_guard_dryrun_report.json"),
            "word_level_drop_review": str(run_dir / "word_level_drop_review.md"),
            "word_level_gap_cut_review": str(run_dir / "word_level_gap_cut_review.md"),
            "word_level_human_review_focus": str(run_dir / "word_level_human_review_focus.md"),
            "phase4b_dryrun_report": str(run_dir / "phase4b_dryrun_report.json"),
        },
        "safety": {
            "draft_written": False,
            "encrypt_called": False,
            "deepseek_called": False,
            "tracks_modified": False,
            "project_json_modified": False,
            "timeline_layout_modified": False,
        },
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4B word-level A-Roll EDL dry-run.")
    parser.add_argument("--phase4a-dir", type=Path, default=DEFAULT_PHASE4A_DIR)
    parser.add_argument("--subtitle-timeline", type=Path, default=DEFAULT_SUBTITLES)
    parser.add_argument("--script-path", type=Path, default=DEFAULT_SCRIPT)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    args = parser.parse_args()

    word_timeline = args.phase4a_dir / "word_timeline.json"
    word_gap_report = args.phase4a_dir / "word_gap_report.json"
    repeat_clusters = args.phase4a_dir / "repeat_clusters.json"
    residual_report = args.phase4a_dir / "residual_candidates_report.md"
    required = [word_timeline, word_gap_report, repeat_clusters, residual_report, args.subtitle_timeline]
    for path in required:
        if not path.exists():
            raise FileNotFoundError(path)

    run_dir = args.runtime / f"aroll_phase4b_word_edl_dryrun_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    subtitles = read_json(args.subtitle_timeline)
    words = read_json(word_timeline)
    gaps_payload = read_json(word_gap_report)
    clusters = read_json(repeat_clusters)
    gaps = gaps_payload.get("gaps") or []
    edl, subtitle_plan, gap_cut_plan, guard_report, decision = build_word_level_edl(subtitles, words, gaps, clusters)

    inputs = {
        "word_timeline": str(word_timeline),
        "word_gap_report": str(word_gap_report),
        "repeat_clusters": str(repeat_clusters),
        "residual_candidates_report": str(residual_report),
        "subtitle_timeline": str(args.subtitle_timeline),
        "script_path": str(args.script_path),
    }
    report = build_report(run_dir, inputs, subtitles, words, edl, subtitle_plan, gap_cut_plan, guard_report, decision.decision_rows)

    write_json(run_dir / "word_level_aroll_edl.json", edl)
    write_json(run_dir / "word_level_subtitle_plan.json", subtitle_plan)
    write_json(run_dir / "word_gap_cut_plan.json", gap_cut_plan)
    write_json(run_dir / "semantic_guard_dryrun_report.json", guard_report)
    write_drop_review(run_dir / "word_level_drop_review.md", subtitles, decision.decision_rows)
    write_gap_review(run_dir / "word_level_gap_cut_review.md", gap_cut_plan)
    write_human_focus(run_dir / "word_level_human_review_focus.md", report["regression_results"], gap_cut_plan, decision.decision_rows)
    write_json(run_dir / "phase4b_dryrun_report.json", report)

    print("status=ok")
    print(f"runtime={run_dir}")
    print(f"report={run_dir / 'phase4b_dryrun_report.json'}")
    print(f"estimated_final_duration_s={sec(report['estimated_final_duration_us'])}")
    print(f"word_clip_count={len(edl)}")
    print(f"subtitle_fragment_count={len(subtitle_plan)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

