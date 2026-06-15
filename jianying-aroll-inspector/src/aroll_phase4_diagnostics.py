from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from aroll_repeat_detector import detect_repeat_clusters, detector_tests
from aroll_text_normalize import normalize_text
from aroll_word_timeline import build_word_timeline
from jy_bridge import write_json


DEFAULT_SUBTITLES = Path(r"D:\video tools\jianying-aroll-inspector\runtime\aroll_inspect_20260614_111146\subtitle_timeline.json")
DEFAULT_SCRIPT = Path(r"D:\idea-project\Jackson WorldViews\src\main\java\jackson\worldviews\content\shoortvideoScript\S16\S16正文脚本\S16-3-嘉豪.md")
DEFAULT_RUNTIME = Path(r"D:\video tools\jianying-aroll-inspector\runtime")
THRESHOLDS = [80_000, 120_000, 200_000, 300_000, 500_000]


def threshold_bucket(duration_us: int) -> str:
    bucket = "80ms"
    for value in THRESHOLDS:
        if duration_us >= value:
            bucket = f"{value // 1000}ms"
    return bucket


def candidate_action(duration_us: int) -> str:
    if duration_us >= 300_000:
        return "cut_to_0"
    if duration_us >= 120_000:
        return "cut_to_30ms"
    return "keep_for_review"


def context_text(words: list[dict[str, Any]], index: int, radius: int = 4) -> str:
    start = max(0, index - radius)
    end = min(len(words), index + radius + 1)
    return "".join(str(item.get("word_text") or "") for item in words[start:end])


def build_word_gap_report(subtitles: list[dict[str, Any]], word_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_subtitle: dict[str, list[dict[str, Any]]] = {}
    for word in word_rows:
        by_subtitle.setdefault(str(word["subtitle_uid"]), []).append(word)
    for items in by_subtitle.values():
        items.sort(key=lambda item: (int(item["start_us"]), int(item["end_us"])))

    subtitle_by_uid = {str(row.get("subtitle_uid")): row for row in subtitles}
    gaps: list[dict[str, Any]] = []

    def add_gap(gap_type: str, prev_word: dict[str, Any] | None, next_word: dict[str, Any] | None, start_us: int, end_us: int, prev_uid: str, next_uid: str, left_context: str, right_context: str) -> None:
        duration = end_us - start_us
        if duration < 80_000:
            return
        gaps.append(
            {
                "gap_id": f"gap_{len(gaps) + 1:06d}",
                "gap_type": gap_type,
                "prev_subtitle_uid": prev_uid,
                "next_subtitle_uid": next_uid,
                "prev_word": str((prev_word or {}).get("word_text") or ""),
                "next_word": str((next_word or {}).get("word_text") or ""),
                "gap_start_us": start_us,
                "gap_end_us": end_us,
                "gap_duration_us": duration,
                "threshold_bucket": threshold_bucket(duration),
                "left_text_context": left_context,
                "right_text_context": right_context,
                "candidate_action": candidate_action(duration),
            }
        )

    for uid, words in by_subtitle.items():
        for idx, (prev_word, next_word) in enumerate(zip(words, words[1:])):
            add_gap(
                "within_subtitle",
                prev_word,
                next_word,
                int(prev_word["end_us"]),
                int(next_word["start_us"]),
                uid,
                uid,
                context_text(words, idx),
                context_text(words, idx + 1),
            )

    ordered_subs = sorted(subtitles, key=lambda row: int(row.get("subtitle_index") or 0))
    for prev_sub, next_sub in zip(ordered_subs, ordered_subs[1:]):
        prev_uid = str(prev_sub.get("subtitle_uid") or "")
        next_uid = str(next_sub.get("subtitle_uid") or "")
        prev_words = by_subtitle.get(prev_uid) or []
        next_words = by_subtitle.get(next_uid) or []
        if prev_words and next_words:
            add_gap(
                "between_subtitle",
                prev_words[-1],
                next_words[0],
                int(prev_words[-1]["end_us"]),
                int(next_words[0]["start_us"]),
                prev_uid,
                next_uid,
                str(prev_sub.get("subtitle_text") or ""),
                str(next_sub.get("subtitle_text") or ""),
            )
        add_gap(
            "subtitle_time_gap",
            None,
            None,
            int(prev_sub.get("end_us") or 0),
            int(next_sub.get("start_us") or 0),
            prev_uid,
            next_uid,
            str(prev_sub.get("subtitle_text") or ""),
            str(next_sub.get("subtitle_text") or ""),
        )

    counts: dict[str, dict[str, int]] = {}
    for gap in gaps:
        gap_type = str(gap["gap_type"])
        counts.setdefault(gap_type, {})
        for threshold in THRESHOLDS:
            if int(gap["gap_duration_us"]) >= threshold:
                key = f">{threshold // 1000}ms"
                counts[gap_type][key] = counts[gap_type].get(key, 0) + 1
    gaps.sort(key=lambda item: int(item["gap_duration_us"]), reverse=True)
    return {
        "thresholds_us": THRESHOLDS,
        "gap_count": len(gaps),
        "counts": counts,
        "gaps": gaps,
    }


def write_top_gaps_md(path: Path, gap_report: dict[str, Any]) -> None:
    lines = ["# Top 50 Longest Word Gaps", ""]
    for gap in (gap_report.get("gaps") or [])[:50]:
        lines.extend(
            [
                f"## {gap['gap_id']} | {gap['gap_type']} | {gap['gap_duration_us'] / 1000:.0f}ms",
                "",
                f"- Prev: `{gap['prev_word']}`",
                f"- Next: `{gap['next_word']}`",
                f"- Prev subtitle: `{gap['prev_subtitle_uid']}`",
                f"- Next subtitle: `{gap['next_subtitle_uid']}`",
                f"- Action: `{gap['candidate_action']}`",
                f"- Left: {gap['left_text_context']}",
                f"- Right: {gap['right_text_context']}",
                "",
            ]
        )
    path.write_text("\n".join(lines), "utf-8")


def cluster_counts(clusters: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in clusters:
        ctype = str(item.get("cluster_type") or "unknown")
        counts[ctype] = counts.get(ctype, 0) + 1
    return counts


def find_cluster(clusters: list[dict[str, Any]], predicate) -> dict[str, Any] | None:
    for item in clusters:
        if predicate(item):
            return item
    return None


def regression_results(clusters: list[dict[str, Any]]) -> dict[str, Any]:
    def cluster_text(item: dict[str, Any]) -> str:
        return "\n".join(str(row.get("text") or "") for row in item.get("items") or [])

    pronoun = find_cluster(clusters, lambda c: c.get("cluster_type") in {"pronoun_variant_duplicate", "near_duplicate"} and "你可以嘲笑" in cluster_text(c) and "虚伪" in cluster_text(c))
    pit = find_cluster(clusters, lambda c: "就看到有人想爬出粪坑" in cluster_text(c))
    young = find_cluster(clusters, lambda c: "年少的时候" in cluster_text(c) and "寻找优越感" in cluster_text(c))
    step = find_cluster(clusters, lambda c: "随意" in cluster_text(c) and "肆意" in cluster_text(c))
    same_phrase = [c for c in clusters if c.get("cluster_type") == "same_subtitle_repeated_phrase"]

    return {
        "pronoun_variant_duplicate": {
            "detected": pronoun is not None,
            "cluster_id": (pronoun or {}).get("cluster_id"),
            "suggested_action": (pronoun or {}).get("suggested_action"),
            "reason": (pronoun or {}).get("reason"),
        },
        "see_pit_prefix": {
            "detected": pit is not None,
            "cluster_id": (pit or {}).get("cluster_id"),
            "suggested_action": (pit or {}).get("suggested_action"),
            "reason": (pit or {}).get("reason"),
        },
        "young_youyuegan": {
            "detected": young is not None,
            "cluster_id": (young or {}).get("cluster_id"),
            "suggested_action": (young or {}).get("suggested_action"),
            "reason": (young or {}).get("reason"),
        },
        "suiyi_ruyi": {
            "detected": step is not None,
            "cluster_id": (step or {}).get("cluster_id"),
            "suggested_action": (step or {}).get("suggested_action"),
            "reason": (step or {}).get("reason"),
        },
        "same_subtitle_repeated_phrase": {
            "detected": bool(same_phrase),
            "count": len(same_phrase),
            "cluster_ids": [c.get("cluster_id") for c in same_phrase],
        },
    }


def write_residual_report(path: Path, regressions: dict[str, Any], clusters: list[dict[str, Any]], gap_report: dict[str, Any]) -> None:
    counts = cluster_counts(clusters)
    lines = [
        "# Phase 4A Residual Candidates",
        "",
        "## A. Regression Test Results",
        "",
    ]
    labels = [
        ("你可以嘲笑他们虚伪", "pronoun_variant_duplicate"),
        ("看 / 就看到有人想爬出粪坑", "see_pit_prefix"),
        ("人家年少的时候 / 寻找优越感", "young_youyuegan"),
        ("随意的 / 肆意的踩踏", "suiyi_ruyi"),
        ("同字幕重复 phrase", "same_subtitle_repeated_phrase"),
    ]
    for title, key in labels:
        row = regressions[key]
        lines.extend(
            [
                f"### {title}",
                f"- Detected: {'yes' if row.get('detected') else 'no'}",
                f"- Cluster: {row.get('cluster_id') or row.get('cluster_ids') or ''}",
                f"- Suggested action: {row.get('suggested_action') or ''}",
                f"- Reason: {row.get('reason') or ''}",
                "",
            ]
        )

    lines.extend(["## B. Top Near Duplicate Clusters", ""])
    for item in [c for c in clusters if c.get("cluster_type") in {"near_duplicate", "pronoun_variant_duplicate", "exact_duplicate"}][:20]:
        lines.append(f"- `{item['cluster_id']}` {item['cluster_type']} {item['window_indices']} action={item['suggested_action']} reason={item['reason']}")
    lines.extend(["", "## C. Prefix Fragment Candidates", ""])
    for item in [c for c in clusters if "prefix" in str(c.get("cluster_type"))][:20]:
        lines.append(f"- `{item['cluster_id']}` {item['cluster_type']} {item['window_indices']} action={item['suggested_action']} reason={item['reason']}")
    lines.extend(["", "## D. Same-subtitle Repeated Phrase Candidates", ""])
    for item in [c for c in clusters if c.get("cluster_type") == "same_subtitle_repeated_phrase"][:20]:
        lines.append(f"- `{item['cluster_id']}` {item['window_indices']} {item.get('reason')}")
    lines.extend(["", "## E. Top Word Gaps / Breath Gaps", ""])
    for gap in (gap_report.get("gaps") or [])[:20]:
        lines.append(f"- `{gap['gap_id']}` {gap['gap_type']} {gap['gap_duration_us'] / 1000:.0f}ms `{gap['prev_word']}` -> `{gap['next_word']}` action={gap['candidate_action']}")
    lines.extend(["", "## F. Risks / Unknowns", ""])
    lines.append(f"- cluster counts: {json.dumps(counts, ensure_ascii=False)}")
    lines.append("- Phase 4A is read-only. No EDL/write-back decision has been applied.")
    path.write_text("\n".join(lines) + "\n", "utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 4A read-only word-level and repeat diagnostics.")
    parser.add_argument("--subtitle-timeline", type=Path, default=DEFAULT_SUBTITLES)
    parser.add_argument("--script-path", type=Path, default=DEFAULT_SCRIPT)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    args = parser.parse_args()

    run_dir = args.runtime / f"aroll_phase4_diagnostics_{time.strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    subtitles = json.loads(args.subtitle_timeline.read_text("utf-8"))
    script_text = args.script_path.read_text("utf-8") if args.script_path.exists() else ""

    word_rows, schema_report = build_word_timeline(subtitles)
    gap_report = build_word_gap_report(subtitles, word_rows)
    clusters = detect_repeat_clusters(subtitles, window=4)
    regressions = regression_results(clusters)
    tests = detector_tests()
    counts = cluster_counts(clusters)

    write_json(run_dir / "word_schema_report.json", schema_report)
    write_json(run_dir / "word_timeline.json", word_rows)
    write_json(run_dir / "word_gap_report.json", gap_report)
    write_top_gaps_md(run_dir / "top_50_longest_word_gaps.md", gap_report)
    write_json(run_dir / "repeat_clusters.json", clusters)
    write_json(run_dir / "detector_tests.json", tests)
    write_residual_report(run_dir / "residual_candidates_report.md", regressions, clusters, gap_report)

    summary = {
        "subtitle_timeline": str(args.subtitle_timeline),
        "script_path": str(args.script_path),
        "script_char_count": len(script_text),
        "subtitle_count": len(subtitles),
        "word_schema_report": str(run_dir / "word_schema_report.json"),
        "word_timeline": str(run_dir / "word_timeline.json"),
        "word_gap_report": str(run_dir / "word_gap_report.json"),
        "repeat_clusters": str(run_dir / "repeat_clusters.json"),
        "residual_candidates_report": str(run_dir / "residual_candidates_report.md"),
        "detector_tests": str(run_dir / "detector_tests.json"),
        "word_timing": {
            "subtitle_with_word_timing": schema_report["subtitle_with_word_timing"],
            "word_count": schema_report["word_count"],
            "unit_stats": schema_report["unit_stats"],
            "fatal_reasons": schema_report["fatal_reasons"],
            "warnings": schema_report["warnings"],
            "sufficient_for_word_level_engine": schema_report["subtitle_with_word_timing"] >= int(len(subtitles) * 0.9) and schema_report["word_count"] > 0,
        },
        "word_gaps": {
            "gap_count": gap_report["gap_count"],
            "counts": gap_report["counts"],
            "top_10": (gap_report.get("gaps") or [])[:10],
        },
        "repeat_detector": {
            "cluster_total": len(clusters),
            "counts": counts,
        },
        "regression_results": regressions,
        "detector_tests_passed": tests["passed"],
        "phase4b_recommendation": {
            "recommend": schema_report["subtitle_with_word_timing"] >= int(len(subtitles) * 0.9) and tests["passed"],
            "reason": "word timing coverage is sufficient and regression detector tests passed" if tests["passed"] else "detector tests failed",
        },
        "safety": {
            "draft_written": False,
            "encrypt_called": False,
            "deepseek_called": False,
            "tracks_modified": False,
        },
    }
    write_json(run_dir / "phase4_diagnostics_summary.json", summary)

    print("status=ok")
    print(f"runtime={run_dir}")
    print(f"summary={run_dir / 'phase4_diagnostics_summary.json'}")
    print(f"subtitle_count={len(subtitles)}")
    print(f"word_count={schema_report['word_count']}")
    print(f"repeat_clusters={len(clusters)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
