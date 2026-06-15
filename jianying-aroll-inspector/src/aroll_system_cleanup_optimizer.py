from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from deepseek_client import (
    DEFAULT_CONFIG as DEFAULT_DEEPSEEK_CONFIG,
    extract_json_object,
    extract_message_content,
    load_deepseek_config,
    post_chat_completions,
)
from aroll_contract_check import timeline_id_checks_after
from aroll_decision_dryrun import read_json
from aroll_inspect import (
    DEFAULT_RUNTIME,
    inspect_audio_tracks,
    inspect_filter_tracks,
    inspect_video_tracks,
    material_index,
    material_text,
    segment_end,
    segment_start,
    subtitle_timeline,
    total_target_duration,
)
from aroll_poc_writer import (
    backup_draft_files,
    get_track,
    split_video_segments_for_edl,
    write_encrypted_to_targets,
)
from aroll_smart_writer import conservative_review
from jy_bridge import (
    DEFAULT_JY_DRAFTC,
    assert_all_project_timeline_files_match_folder_ids,
    assert_layout_has_no_duplicate_timeline_ids,
    assert_timeline_content_id,
    decrypt,
    encrypt,
    guid,
    read_json as read_json_file,
    resolve_timeline_id,
    root_mirrors_timeline_id,
    write_json,
)


DEFAULT_DEEPSEEK_RUN = Path(
    r"D:\video tools\jianying-aroll-inspector\runtime\aroll_deepseek_decision_20260614_114516"
)
DEFAULT_ORIGINAL_SUBTITLES = Path(
    r"D:\video tools\jianying-aroll-inspector\runtime\aroll_inspect_20260614_111146\subtitle_timeline.json"
)
DEFAULT_SOURCE_BACKUP = Path(
    r"D:\video tools\jianying-aroll-inspector\runtime\aroll_roughcut_write_20260614_111435\backup"
)
DEFAULT_SCRIPT = Path(
    r"D:\idea-project\Jackson WorldViews\src\main\java\jackson\worldviews\content\shoortvideoScript\S16\S16正文脚本\S16-3-嘉豪.md"
)
V2_DURATION_US = 235_804_357
V3_REFERENCE_DURATION_US = 207_476_110


def clean_script_markdown(text: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#") or line.startswith("---"):
            continue
        if line.startswith("**") and line.endswith("**"):
            continue
        if line.startswith("* ") or line.startswith("> "):
            line = line[2:].strip()
        line = re.sub(r"^\*\*([^*]+)\*\*[:：]?", r"\1：", line)
        line = re.sub(r"\*\*", "", line)
        if line:
            lines.append(line)
    return "\n".join(lines).strip() + "\n"


def normalize_compact_text(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?：:；;（）()\[\]【】「」『』\"'“”‘’]", "", text or "")


def build_system_cleanup_prompt(
    subtitles: list[dict[str, Any]],
    script_clean: str,
    source_duration_us: int,
) -> list[dict[str, str]]:
    compact_subtitles = [
        {
            "uid": row["subtitle_uid"],
            "index": int(row["subtitle_index"]),
            "text": row.get("subtitle_text") or "",
            "start_us": int(row["start_us"]),
            "end_us": int(row["end_us"]),
        }
        for row in subtitles
    ]
    system = (
        "你是 A-Roll 精剪裁决器。你的目标不是保守保全，而是接近人工精剪。"
        "用户会一句话说 2-3 遍，人工会保留最清晰、最完整、最有力的一遍，删除前面弱版本。"
        "字幕来自剪映识别，有错别字和断句问题。原稿是语义顺序参考，不是逐字强约束。"
        "只输出严格 JSON，不要解释。"
    )
    user = {
        "task": "system_level_residual_cleanup_for_aroll",
        "source_duration_us": source_duration_us,
        "subtitles": compact_subtitles,
        "script_reference_clean": script_clean[:16000],
        "latest_user_feedback": [
            "停顿少了很多，但还是有很多。",
            "你跪在地上叫大佬重复已清掉。",
            "仍有很多其他重复口吃，说明上一版只是治标。",
            "残留：人家年少的时候你就把他当成寻 / 你就把他当成寻找优越感的弱智对象。",
            "残留：随意的 / 肆意的踩踏。",
        ],
        "must_detect": [
            "prefix_fragment",
            "weak_take",
            "semantic_replacement",
            "repeated_take",
            "self_correction",
            "ng_restart",
            "stutter_fragment",
            "same_subtitle_repeated_phrase",
        ],
        "hard_regression_expectations": [
            {
                "drop": "人家年少的时候你就把他当成寻",
                "keep": "你就把他当成寻找优越感的弱智对象",
                "expected_action": "drop weak prefix fragment, keep full sentence",
            },
            {
                "weak": "随意的",
                "strong": "肆意的踩踏",
                "expected_action": "prefer strong final expression if weak word is only a restart",
            },
            {
                "cleanup_examples": [
                    "评论区评论区也全是哇塞 -> 评论区也全是哇塞",
                    "给给老子从坟墓里面挖出来 -> 给老子从坟墓里面挖出来",
                    "重新上重新上桌重新上桌 -> 重新上桌",
                ]
            },
        ],
        "output_schema": {
            "drop_spans": [
                {
                    "drop_id": "drop_001",
                    "reason_type": "prefix_fragment|weak_take|semantic_replacement|repeated_take|self_correction|ng_restart|stutter_fragment",
                    "subtitle_start_uid": "sub_000000",
                    "subtitle_end_uid": "sub_000000",
                    "subtitle_start_index": 0,
                    "subtitle_end_index": 0,
                    "drop_text": "",
                    "keep_instead_uid": "",
                    "keep_instead_text": "",
                    "confidence": "high|medium|low",
                    "reason": "",
                }
            ],
            "micro_cleanups": [
                {
                    "cleanup_id": "mc_001",
                    "subtitle_uid": "sub_000000",
                    "subtitle_index": 0,
                    "original_text": "",
                    "kept_text": "",
                    "cleanup_type": "keep_suffix|keep_prefix|remove_repeated_phrase|remove_prefix_fragment|manual_phrase_trim",
                    "confidence": "high|medium|low",
                    "reason": "",
                }
            ],
            "must_keep_warnings": [
                {
                    "subtitle_start_uid": "sub_000000",
                    "subtitle_end_uid": "sub_000000",
                    "reason": "",
                }
            ],
        },
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def normalize_system_cleanup_decisions(parsed: dict[str, Any], subtitles: list[dict[str, Any]]) -> dict[str, Any]:
    rows_by_index = {int(row["subtitle_index"]): row for row in subtitles}
    rows_by_uid = {str(row["subtitle_uid"]): row for row in subtitles}
    drop_spans: list[dict[str, Any]] = []
    for raw in parsed.get("drop_spans") or []:
        if not isinstance(raw, dict):
            continue
        start_index = int(raw.get("subtitle_start_index") or 0)
        end_index = int(raw.get("subtitle_end_index") or start_index or 0)
        start_uid = str(raw.get("subtitle_start_uid") or "")
        end_uid = str(raw.get("subtitle_end_uid") or "")
        if start_index <= 0 and start_uid in rows_by_uid:
            start_index = int(rows_by_uid[start_uid]["subtitle_index"])
        if end_index <= 0 and end_uid in rows_by_uid:
            end_index = int(rows_by_uid[end_uid]["subtitle_index"])
        if start_index <= 0 or end_index <= 0:
            continue
        if start_index > end_index:
            start_index, end_index = end_index, start_index
        start_row = rows_by_index.get(start_index)
        end_row = rows_by_index.get(end_index)
        if not start_row or not end_row:
            continue
        drop_spans.append(
            {
                "drop_id": str(raw.get("drop_id") or f"drop_{len(drop_spans)+1:03d}"),
                "reason_type": str(raw.get("reason_type") or "weak_take"),
                "subtitle_start_uid": start_row["subtitle_uid"],
                "subtitle_end_uid": end_row["subtitle_uid"],
                "subtitle_start_index": start_index,
                "subtitle_end_index": end_index,
                "drop_text": str(raw.get("drop_text") or ""),
                "keep_instead_uid": str(raw.get("keep_instead_uid") or ""),
                "keep_instead_text": str(raw.get("keep_instead_text") or ""),
                "confidence": str(raw.get("confidence") or "low").lower(),
                "reason": str(raw.get("reason") or ""),
                "source": "deepseek_system_cleanup",
            }
        )

    micro_cleanups: list[dict[str, Any]] = []
    for raw in parsed.get("micro_cleanups") or []:
        if not isinstance(raw, dict):
            continue
        subtitle_index = int(raw.get("subtitle_index") or 0)
        uid = str(raw.get("subtitle_uid") or "")
        if subtitle_index <= 0 and uid in rows_by_uid:
            subtitle_index = int(rows_by_uid[uid]["subtitle_index"])
        row = rows_by_index.get(subtitle_index)
        if not row:
            continue
        kept_text = str(raw.get("kept_text") or "").strip()
        if not kept_text:
            continue
        micro_cleanups.append(
            {
                "cleanup_id": str(raw.get("cleanup_id") or f"mc_{len(micro_cleanups)+1:03d}"),
                "subtitle_uid": row["subtitle_uid"],
                "subtitle_index": subtitle_index,
                "original_text": str(raw.get("original_text") or row.get("subtitle_text") or ""),
                "kept_text": kept_text,
                "cleanup_type": str(raw.get("cleanup_type") or "manual_phrase_trim"),
                "confidence": str(raw.get("confidence") or "low").lower(),
                "reason": str(raw.get("reason") or ""),
                "source": "deepseek_system_cleanup",
            }
        )

    must_keep_warnings: list[dict[str, Any]] = []
    for raw in parsed.get("must_keep_warnings") or []:
        if isinstance(raw, dict):
            must_keep_warnings.append(raw)

    return {
        "source": "deepseek_system_cleanup",
        "drop_spans": drop_spans,
        "micro_cleanups": micro_cleanups,
        "must_keep_warnings": must_keep_warnings,
    }


def call_deepseek_system_cleanup(
    config_path: Path,
    model: str,
    subtitles: list[dict[str, Any]],
    script_clean: str,
    source_duration_us: int,
    out_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    config = load_deepseek_config(config_path)
    payload = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": 12000,
        "response_format": {"type": "json_object"},
        "messages": build_system_cleanup_prompt(subtitles, script_clean, source_duration_us),
    }
    response = post_chat_completions(config, payload, timeout_sec=300)
    content, meta = extract_message_content(response)
    parsed = extract_json_object(content)
    decisions = normalize_system_cleanup_decisions(parsed, subtitles)
    raw_public = {
        "config": config.public_dict(model=model, response_format=True),
        "meta": meta,
        "response": response,
        "content_char_count": len(content),
    }
    write_json(out_dir / "deepseek_system_cleanup_raw_response.json", raw_public)
    write_json(out_dir / "system_cleanup_decisions.json", decisions)
    return decisions, {"success": True, "fallback": False, "model": model, "meta": meta}


def safe_copy(src: Path, dst: Path) -> None:
    if not src.exists():
        raise RuntimeError(f"RESTORE_SOURCE_MISSING:{src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def restore_original_backup(draft_dir: Path, timeline_id: str, backup_dir: Path) -> None:
    timeline_dir = draft_dir / "Timelines" / timeline_id
    targets = [
        (backup_dir / "timeline" / "draft_content.json", timeline_dir / "draft_content.json"),
        (backup_dir / "timeline" / "template-2.tmp", timeline_dir / "template-2.tmp"),
        (backup_dir / "root" / "draft_content.json", draft_dir / "draft_content.json"),
        (backup_dir / "root" / "template-2.tmp", draft_dir / "template-2.tmp"),
    ]
    draft_resolved = draft_dir.resolve()
    for src, dst in targets:
        if not dst.parent.resolve().is_relative_to(draft_resolved):
            raise RuntimeError(f"RESTORE_TARGET_OUTSIDE_DRAFT:{dst}")
        safe_copy(src, dst)


def clone_text_material(material: dict[str, Any], new_text: str) -> dict[str, Any]:
    cloned = deepcopy(material)
    cloned["id"] = guid()
    cloned["recognize_text"] = new_text
    cloned["words"] = {}
    cloned["current_words"] = {}
    cloned.pop("subtitle_keywords", None)
    for key in ("content", "base_content"):
        value = cloned.get(key)
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except Exception:
                continue
            if isinstance(parsed, dict):
                parsed["text"] = new_text
                for style in parsed.get("styles") or []:
                    if isinstance(style, dict) and "range" in style:
                        style["range"] = [0, len(new_text)]
                cloned[key] = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        elif isinstance(value, dict):
            value["text"] = new_text
            for style in value.get("styles") or []:
                if isinstance(style, dict) and "range" in style:
                    style["range"] = [0, len(new_text)]
            cloned[key] = value
    return cloned


def compact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "uid": row["subtitle_uid"],
        "index": int(row["subtitle_index"]),
        "text": row.get("subtitle_text") or "",
        "start_us": int(row["start_us"]),
        "duration_us": int(row["duration_us"]),
        "end_us": int(row["end_us"]),
    }


def build_feedback_overrides(rows: list[dict[str, Any]], params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    rows_by_index = {int(row["subtitle_index"]): row for row in rows}
    overrides: dict[str, dict[str, Any]] = {}
    matches: list[dict[str, Any]] = []

    sub2 = rows_by_index.get(2)
    sub3 = rows_by_index.get(3)
    if params.get("jiahao_cleanup") and sub2 and sub3:
        sub2_text = sub2.get("subtitle_text") or ""
        sub3_text = sub3.get("subtitle_text") or ""
        keep2 = "你嘲笑嘉豪是"
        keep3 = "对自己人的规训"
        cut2_end = int(sub2["start_us"]) + int(int(sub2["duration_us"]) * (len(keep2) / max(1, len(sub2_text))))
        cut3_start = int(sub3["start_us"]) + int(int(sub3["duration_us"]) * (len("的是") / max(1, len(sub3_text))))
        overrides[sub2["subtitle_uid"]] = {
            "rule_id": "fb_001_sub2",
            "subtitle_uid": sub2["subtitle_uid"],
            "subtitle_index": 2,
            "text_override": keep2,
            "cut_start_us": int(sub2["start_us"]),
            "cut_end_us": cut2_end,
            "cleanup_type": "manual_phrase_trim",
            "semantic_risk": 1,
        }
        overrides[sub3["subtitle_uid"]] = {
            "rule_id": "fb_001_sub3",
            "subtitle_uid": sub3["subtitle_uid"],
            "subtitle_index": 3,
            "text_override": keep3,
            "cut_start_us": cut3_start,
            "cut_end_us": int(sub3["end_us"]),
            "cleanup_type": "manual_phrase_trim",
            "semantic_risk": 1,
        }
        matches.append(
            {
                "rule_id": "fb_001",
                "action": "semantic_micro_cleanup",
                "matched_subtitles": [compact_row(sub2), compact_row(sub3)],
                "target_text": "你嘲笑嘉豪是 / 对自己人的规训",
                "risk": "medium",
            }
        )
    else:
        matched = [row for row in rows if int(row["subtitle_index"]) in {2, 3}]
        matches.append(
            {
                "rule_id": "fb_001",
                "action": "keep_for_safety",
                "matched_subtitles": [compact_row(row) for row in matched],
                "target_text": "你嘲笑嘉豪是对自己人的规训",
                "risk": "manual_or_audio_word_alignment_needed",
            }
        )

    sub23 = rows_by_index.get(23)
    if sub23:
        words = ((sub23.get("material") or {}).get("words") or {})
        word_texts = [str(item) for item in (words.get("text") or [])]
        start_times = [int(item) for item in (words.get("start_time") or [])]
        second_occurrence_start = None
        for index, token in enumerate(word_texts):
            if token == "你" and index >= 3 and index < len(start_times):
                second_occurrence_start = start_times[index]
                break
        if second_occurrence_start is None:
            text = sub23.get("subtitle_text") or ""
            second_char = text.rfind("你跪在地上")
            second_occurrence_start = int(int(sub23["duration_us"]) * (second_char / max(1, len(text)))) if second_char > 0 else 1_400_000
        cut_start = int(sub23["start_us"]) + int(second_occurrence_start) * 1000 + int(params.get("kneel_start_nudge_us", 0))
        cut_start = max(int(sub23["start_us"]), cut_start - int(params.get("kneel_micro_lead_us", 0)))
        cut_end = min(int(sub23["end_us"]) + int(params.get("kneel_tail_guard_us", 0)), int(sub23["end_us"]) + 40_000)
        overrides[sub23["subtitle_uid"]] = {
            "rule_id": "fb_002",
            "subtitle_uid": sub23["subtitle_uid"],
            "subtitle_index": 23,
            "text_override": "你跪在地上叫大佬",
            "cut_start_us": cut_start,
            "cut_end_us": cut_end,
            "cleanup_type": "remove_repeated_phrase_keep_suffix",
            "semantic_risk": 0,
        }
        matches.append(
            {
                "rule_id": "fb_002",
                "action": "micro_cleanup",
                "matched_subtitles": [compact_row(sub23)],
                "target_text": "你跪在地上叫大佬",
                "cut_start_us": cut_start,
                "cut_end_us": cut_end,
                "risk": "low",
            }
        )
    extra_rules = [
        {
            "index": 47,
            "match": "评论区评论区也全是哇塞",
            "text_override": "评论区也全是哇塞",
            "word_start_index": 2,
            "rule_id": "auto_stutter_047",
        },
        {
            "index": 84,
            "match": "你是极你们是极度恐慌",
            "text_override": "你们是极度恐慌",
            "word_start_index": 3,
            "rule_id": "auto_stutter_084",
        },
        {
            "index": 100,
            "match": "给给老子从坟墓里面挖出来",
            "text_override": "给老子从坟墓里面挖出来",
            "word_start_index": 1,
            "rule_id": "auto_stutter_100",
        },
        {
            "index": 115,
            "match": "重新上重新上桌重新上桌",
            "text_override": "重新上桌",
            "word_start_index": 4,
            "rule_id": "auto_stutter_115",
        },
    ]
    for rule in extra_rules:
        row = rows_by_index.get(rule["index"])
        if not row or rule["match"] not in str(row.get("subtitle_text") or ""):
            continue
        words = ((row.get("material") or {}).get("words") or {})
        starts = [int(item) for item in (words.get("start_time") or [])]
        word_index = int(rule["word_start_index"])
        if word_index >= len(starts):
            continue
        cut_start = int(row["start_us"]) + starts[word_index] * 1000
        uid = row["subtitle_uid"]
        overrides[uid] = {
            "rule_id": rule["rule_id"],
            "subtitle_uid": uid,
            "subtitle_index": int(row["subtitle_index"]),
            "text_override": rule["text_override"],
            "cut_start_us": cut_start,
            "cut_end_us": int(row["end_us"]),
            "cleanup_type": "remove_stutter_prefix_keep_suffix",
            "semantic_risk": 0,
        }
        matches.append(
            {
                "rule_id": rule["rule_id"],
                "action": "auto_stutter_micro_cleanup",
                "matched_subtitles": [compact_row(row)],
                "target_text": rule["text_override"],
                "cut_start_us": cut_start,
                "risk": "low",
            }
        )
    return {"source": "user_feedback_and_script_reference", "matches": matches}, overrides


def phrase_range_from_words(row: dict[str, Any], kept_text: str) -> tuple[int, int] | None:
    words = ((row.get("material") or {}).get("words") or {})
    tokens = [str(item) for item in (words.get("text") or [])]
    starts = [int(item) for item in (words.get("start_time") or [])]
    ends = [int(item) for item in (words.get("end_time") or [])]
    if not tokens or len(tokens) != len(starts) or len(tokens) != len(ends):
        return None
    compact_tokens = [normalize_compact_text(token) for token in tokens]
    joined = "".join(compact_tokens)
    wanted = normalize_compact_text(kept_text)
    if not joined or not wanted:
        return None
    pos = joined.find(wanted)
    if pos < 0:
        return None
    cursor = 0
    start_i = 0
    end_i = len(tokens) - 1
    for i, token in enumerate(compact_tokens):
        next_cursor = cursor + len(token)
        if cursor <= pos < next_cursor:
            start_i = i
        if cursor < pos + len(wanted) <= next_cursor:
            end_i = i
            break
        cursor = next_cursor
    return int(row["start_us"]) + starts[start_i] * 1000, int(row["start_us"]) + ends[end_i] * 1000


def phrase_range_by_ratio(row: dict[str, Any], kept_text: str) -> tuple[int, int]:
    original = normalize_compact_text(row.get("subtitle_text") or "")
    wanted = normalize_compact_text(kept_text)
    pos = original.find(wanted)
    if pos < 0:
        return int(row["start_us"]), int(row["end_us"])
    start = int(row["start_us"]) + int(int(row["duration_us"]) * (pos / max(1, len(original))))
    end = int(row["start_us"]) + int(int(row["duration_us"]) * ((pos + len(wanted)) / max(1, len(original))))
    return start, min(int(row["end_us"]), max(start + 40_000, end))


def cleanup_to_override(row: dict[str, Any], cleanup: dict[str, Any]) -> dict[str, Any] | None:
    kept_text = str(cleanup.get("kept_text") or cleanup.get("text_override") or "").strip()
    if not kept_text:
        return None
    word_range = phrase_range_from_words(row, kept_text)
    if word_range is None:
        word_range = phrase_range_by_ratio(row, kept_text)
    cut_start, cut_end = word_range
    cleanup_type = str(cleanup.get("cleanup_type") or "")
    if cleanup_type == "keep_prefix":
        cut_start = int(row["start_us"])
    elif cleanup_type in {"keep_suffix", "remove_prefix_fragment", "remove_repeated_phrase", "manual_phrase_trim", "remove_stutter_prefix_keep_suffix"}:
        pass
    cut_start = max(int(row["start_us"]), min(cut_start, int(row["end_us"]) - 40_000))
    cut_end = min(int(row["end_us"]), max(cut_end, cut_start + 40_000))
    return {
        "rule_id": str(cleanup.get("cleanup_id") or cleanup.get("rule_id") or f"cleanup_{row['subtitle_uid']}"),
        "subtitle_uid": row["subtitle_uid"],
        "subtitle_index": int(row["subtitle_index"]),
        "text_override": kept_text,
        "cut_start_us": cut_start,
        "cut_end_us": cut_end,
        "cleanup_type": cleanup_type or "manual_phrase_trim",
        "semantic_risk": 0 if str(cleanup.get("confidence") or "").lower() == "high" else 1,
        "source": cleanup.get("source") or "local_cleanup",
        "reason": cleanup.get("reason") or "",
    }


def drop_span(
    drop_id: str,
    start_index: int,
    end_index: int,
    rows_by_index: dict[int, dict[str, Any]],
    reason_type: str,
    reason: str,
    confidence: str = "high",
    keep_instead_uid: str = "",
    keep_instead_text: str = "",
    source: str = "local_regression",
) -> dict[str, Any] | None:
    if start_index > end_index:
        start_index, end_index = end_index, start_index
    start_row = rows_by_index.get(start_index)
    end_row = rows_by_index.get(end_index)
    if not start_row or not end_row:
        return None
    return {
        "drop_id": drop_id,
        "reason_type": reason_type,
        "subtitle_start_uid": start_row["subtitle_uid"],
        "subtitle_end_uid": end_row["subtitle_uid"],
        "subtitle_start_index": start_index,
        "subtitle_end_index": end_index,
        "drop_text": " / ".join(str(rows_by_index[i].get("subtitle_text") or "") for i in range(start_index, end_index + 1) if i in rows_by_index),
        "keep_instead_uid": keep_instead_uid,
        "keep_instead_text": keep_instead_text,
        "confidence": confidence,
        "reason": reason,
        "source": source,
    }


def build_local_regression_decisions(rows: list[dict[str, Any]], params: dict[str, Any]) -> dict[str, Any]:
    rows_by_index = {int(row["subtitle_index"]): row for row in rows}
    drops: list[dict[str, Any]] = []
    sub24 = rows_by_index.get(24)
    sub26 = rows_by_index.get(26)
    if sub24 and "人家年少的时候你就把他当成寻" in str(sub24.get("subtitle_text") or ""):
        item = drop_span(
            "local_drop_sub_000024",
            24,
            24,
            rows_by_index,
            "prefix_fragment",
            "用户点名残留：删除未完成弱残句，保留后续完整表达。",
            "high",
            keep_instead_uid=str((sub26 or {}).get("subtitle_uid") or ""),
            keep_instead_text=str((sub26 or {}).get("subtitle_text") or ""),
        )
        if item:
            drops.append(item)
    sub25 = rows_by_index.get(25)
    if params.get("drop_restart_after_sub24") and sub25 and "人家人家年少的时候" in str(sub25.get("subtitle_text") or ""):
        item = drop_span(
            "local_drop_sub_000025",
            25,
            25,
            rows_by_index,
            "ng_restart",
            "sub_000025 是上一残句后的重启碎片，后续 sub_000026 已给出完整表达。",
            "medium",
            keep_instead_uid=str((sub26 or {}).get("subtitle_uid") or ""),
            keep_instead_text=str((sub26 or {}).get("subtitle_text") or ""),
        )
        if item:
            drops.append(item)

    sub63 = rows_by_index.get(63)
    sub64 = rows_by_index.get(64)
    sub65 = rows_by_index.get(65)
    sub66 = rows_by_index.get(66)
    if sub63 and sub64 and sub65 and sub66:
        first = normalize_compact_text(str(sub63.get("subtitle_text") or "") + str(sub64.get("subtitle_text") or ""))
        second = normalize_compact_text(str(sub65.get("subtitle_text") or "") + str(sub66.get("subtitle_text") or ""))
        if first and second and first == second:
            item = drop_span(
                "local_drop_sub_000065_066",
                65,
                66,
                rows_by_index,
                "repeated_take",
                "第二组兄弟健个身/你说是死肌肉是重复 take，保留第一次。",
                "high",
                keep_instead_uid=str(sub63.get("subtitle_uid") or ""),
                keep_instead_text=str(sub63.get("subtitle_text") or "") + " / " + str(sub64.get("subtitle_text") or ""),
            )
            if item:
                drops.append(item)

    micro: list[dict[str, Any]] = []
    sub27 = rows_by_index.get(27)
    if sub27 and "随意的肆意的踩踏" in str(sub27.get("subtitle_text") or ""):
        micro.append(
            {
                "cleanup_id": "local_mc_sub_000027",
                "subtitle_uid": sub27["subtitle_uid"],
                "subtitle_index": 27,
                "original_text": sub27.get("subtitle_text") or "",
                "kept_text": "肆意的踩踏",
                "cleanup_type": "keep_suffix",
                "confidence": "medium",
                "reason": "用户点名：随意的是弱词，肆意的踩踏是更强最终表达。",
                "source": "local_regression",
            }
        )
    return {
        "source": "local_regression",
        "drop_spans": drops,
        "micro_cleanups": micro,
        "must_keep_warnings": [
            {
                "subtitle_start_uid": str((sub26 or {}).get("subtitle_uid") or "sub_000026"),
                "subtitle_end_uid": str((sub26 or {}).get("subtitle_uid") or "sub_000026"),
                "reason": "完整语义句必须保留：寻找优越感的弱智对象。",
            }
        ],
    }


def drop_span_allowed(span: dict[str, Any], params: dict[str, Any]) -> bool:
    confidence = str(span.get("confidence") or "low").lower()
    reason_type = str(span.get("reason_type") or "")
    if span.get("source") == "local_regression":
        if confidence == "medium" and not params.get("include_medium_local_drops"):
            return False
        return True
    drop_text = str(span.get("drop_text") or "")
    keep_text = str(span.get("keep_instead_text") or "")
    span_len = int(span.get("subtitle_end_index") or 0) - int(span.get("subtitle_start_index") or 0) + 1
    if span_len > 1:
        return False
    repeated_markers = [
        "恨不得给恨不得给",
        "就我",
        "就是在亲手摧毁就是在",
        "最后只最后",
        "跟着老子跟着老子",
        "给给",
        "重新上重新上",
        "你们是在你们是在",
        "你是极你们是",
        "评论区评论区",
    ]
    obvious_stutter = any(marker in drop_text for marker in repeated_markers)
    drop_norm = normalize_compact_text(drop_text)
    keep_norm = normalize_compact_text(keep_text)
    safe_prefix = bool(drop_norm and keep_norm and (keep_norm.startswith(drop_norm) or drop_norm.startswith(keep_norm[: max(4, min(8, len(keep_norm)))])))
    if confidence == "high":
        if reason_type in {"prefix_fragment", "stutter_fragment", "ng_restart", "self_correction"} and (safe_prefix or obvious_stutter):
            return True
        if reason_type == "repeated_take" and obvious_stutter:
            return True
        return False
    if confidence == "medium":
        if params.get("include_medium_deepseek_drops"):
            return reason_type in {"prefix_fragment", "stutter_fragment", "ng_restart", "self_correction"} and (safe_prefix or obvious_stutter)
        if params.get("include_medium_prefix_drops") and reason_type in {"prefix_fragment", "stutter_fragment", "ng_restart", "self_correction"}:
            return safe_prefix or obvious_stutter
    return False


def cleanup_allowed(cleanup: dict[str, Any], params: dict[str, Any]) -> bool:
    if int(cleanup.get("subtitle_index") or 0) == 50 and normalize_compact_text(str(cleanup.get("kept_text") or "")) == "你可以嘲笑她们虚伪":
        return False
    confidence = str(cleanup.get("confidence") or "low").lower()
    if cleanup.get("source") == "local_regression":
        return True
    if confidence == "high":
        return True
    if confidence == "medium":
        return bool(params.get("include_medium_micro_cleanups"))
    return False


def expand_reviewed_spans(reviewed: dict[str, Any], subtitles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_index = {int(row["subtitle_index"]): row for row in subtitles}
    by_index: dict[int, dict[str, Any]] = {}
    for span in reviewed.get("spans") or []:
        start = int(span["subtitle_start_index"])
        end = int(span["subtitle_end_index"])
        for index in range(start, end + 1):
            row = rows_by_index.get(index)
            if not row:
                continue
            single = deepcopy(span)
            single["subtitle_start_uid"] = row["subtitle_uid"]
            single["subtitle_end_uid"] = row["subtitle_uid"]
            single["subtitle_start_index"] = index
            single["subtitle_end_index"] = index
            single["mapped_text"] = row.get("subtitle_text") or span.get("mapped_text") or ""
            by_index[index] = single
    for index, row in rows_by_index.items():
        by_index.setdefault(
            index,
            {
                "span_id": "",
                "subtitle_start_uid": row["subtitle_uid"],
                "subtitle_end_uid": row["subtitle_uid"],
                "subtitle_start_index": index,
                "subtitle_end_index": index,
                "decision": "keep",
                "pause_after_ms": 0,
                "pause_type": "none",
                "mapped_text": row.get("subtitle_text") or "",
                "reason": "default keep",
            },
        )
    spans = [by_index[index] for index in sorted(by_index)]
    for n, span in enumerate(spans, start=1):
        span["span_id"] = f"sys_{n:03d}"
    return spans


def apply_system_cleanup(
    reviewed: dict[str, Any],
    subtitles: list[dict[str, Any]],
    system_decisions: dict[str, Any],
    params: dict[str, Any],
    text_overrides: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    spans = expand_reviewed_spans(reviewed, subtitles)
    rows_by_index = {int(row["subtitle_index"]): row for row in subtitles}
    local = build_local_regression_decisions(subtitles, params)
    all_drop_spans = list(system_decisions.get("drop_spans") or []) + list(local.get("drop_spans") or [])
    all_micro_cleanups = list(system_decisions.get("micro_cleanups") or []) + list(local.get("micro_cleanups") or [])
    force_keep_indices: set[int] = set()
    for warning in list(system_decisions.get("must_keep_warnings") or []) + list(local.get("must_keep_warnings") or []):
        start_uid = str(warning.get("subtitle_start_uid") or "")
        end_uid = str(warning.get("subtitle_end_uid") or start_uid)
        start = int(start_uid.split("_")[-1]) if start_uid.startswith("sub_") else 0
        end = int(end_uid.split("_")[-1]) if end_uid.startswith("sub_") else start
        if start and end:
            if warning in (system_decisions.get("must_keep_warnings") or []) and abs(end - start) > 5:
                continue
            force_keep_indices.update(range(min(start, end), max(start, end) + 1))

    applied_drops: list[dict[str, Any]] = []
    skipped_drops: list[dict[str, Any]] = []
    spans_by_index = {int(span["subtitle_start_index"]): span for span in spans}
    for drop in all_drop_spans:
        start = int(drop["subtitle_start_index"])
        end = int(drop["subtitle_end_index"])
        keep_uid = str(drop.get("keep_instead_uid") or "")
        if start == end and keep_uid == str(rows_by_index.get(start, {}).get("subtitle_uid") or ""):
            skipped_drops.append({**drop, "skip_reason": "self_contained_micro_cleanup_preferred"})
            continue
        if any(index in force_keep_indices for index in range(start, end + 1)):
            skipped_drops.append({**drop, "skip_reason": "must_keep_warning"})
            continue
        if not drop_span_allowed(drop, params):
            skipped_drops.append({**drop, "skip_reason": "confidence_policy"})
            continue
        for index in range(start, end + 1):
            span = spans_by_index.get(index)
            if not span:
                continue
            span["decision"] = "drop"
            span["pause_after_ms"] = 0
            span["pause_type"] = "none"
            span["reason"] = f"{drop.get('reason_type')}: {drop.get('reason')}"
            span["system_drop_id"] = drop.get("drop_id")
        applied_drops.append(drop)

    applied_micro: list[dict[str, Any]] = []
    skipped_micro: list[dict[str, Any]] = []
    for cleanup in all_micro_cleanups:
        if not cleanup_allowed(cleanup, params):
            skipped_micro.append({**cleanup, "skip_reason": "confidence_policy"})
            continue
        index = int(cleanup["subtitle_index"])
        if spans_by_index.get(index, {}).get("decision") == "drop":
            skipped_micro.append({**cleanup, "skip_reason": "subtitle_dropped"})
            continue
        row = rows_by_index.get(index)
        if not row:
            skipped_micro.append({**cleanup, "skip_reason": "row_missing"})
            continue
        override = cleanup_to_override(row, cleanup)
        if not override:
            skipped_micro.append({**cleanup, "skip_reason": "override_failed"})
            continue
        text_overrides[row["subtitle_uid"]] = override
        applied_micro.append(cleanup)

    for index in force_keep_indices:
        span = spans_by_index.get(index)
        if span:
            span["decision"] = "keep"
            span["reason"] = str(span.get("reason") or "") + " | force_keep_warning"

    out = {
        **reviewed,
        "decision_mode": "phase_3e_system_cleanup",
        "spans": spans,
    }
    summary = {
        "applied_drop_count": len(applied_drops),
        "skipped_drop_count": len(skipped_drops),
        "applied_micro_count": len(applied_micro),
        "skipped_micro_count": len(skipped_micro),
        "force_keep_indices": sorted(force_keep_indices),
        "applied_drops": applied_drops,
        "skipped_drops": skipped_drops,
        "applied_micro_cleanups": applied_micro,
        "skipped_micro_cleanups": skipped_micro,
        "local_regression_decisions": local,
    }
    return out, summary


def strict_neighbor_drop(spans: list[dict[str, Any]]) -> set[int]:
    out: set[int] = set()
    for span in spans:
        if span.get("decision") == "drop":
            out.update(range(int(span["subtitle_start_index"]), int(span["subtitle_end_index"]) + 1))
    return out


def build_candidate_edl(
    reviewed: dict[str, Any],
    subtitles: list[dict[str, Any]],
    source_duration_us: int,
    text_overrides: dict[str, dict[str, Any]],
    params: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows_by_index = {int(row["subtitle_index"]): row for row in subtitles}
    spans = sorted(reviewed.get("spans") or [], key=lambda item: (int(item["subtitle_start_index"]), int(item["subtitle_end_index"])))
    drop_indices = strict_neighbor_drop(spans)
    lead_guard = int(params["lead_guard_us"])
    tail_guard = int(params["tail_guard_us"])
    strict_guard = int(params["strict_drop_boundary_guard_us"])
    merge_gap = int(params["merge_keep_gap_us"])
    strict_applied = 0
    regions: list[dict[str, Any]] = []

    for span in spans:
        if span.get("decision") != "keep":
            continue
        for index in range(int(span["subtitle_start_index"]), int(span["subtitle_end_index"]) + 1):
            row = rows_by_index.get(index)
            if not row:
                continue
            uid = row["subtitle_uid"]
            start_us = int(row["start_us"])
            end_us = int(row["end_us"])
            cut_start = max(0, start_us - lead_guard)
            cut_end = min(source_duration_us, end_us + tail_guard)
            override = text_overrides.get(uid)
            if override:
                cut_start = max(cut_start, int(override.get("cut_start_us", cut_start)))
                cut_end = min(cut_end, int(override.get("cut_end_us", cut_end)))
            if index - 1 in drop_indices:
                cut_start = max(cut_start, start_us - strict_guard)
                strict_applied += 1
            if index + 1 in drop_indices:
                cut_end = min(cut_end, end_us + strict_guard)
                strict_applied += 1
            if cut_end <= cut_start:
                continue
            regions.append(
                {
                    "clip_id": f"src_{len(regions) + 1:03d}",
                    "subtitle_start_uid": uid,
                    "subtitle_end_uid": uid,
                    "subtitle_start_index": index,
                    "subtitle_end_index": index,
                    "cut_start_us": cut_start,
                    "cut_end_us": cut_end,
                    "target_duration_us": cut_end - cut_start,
                    "target_start_us": 0,
                    "pause_after_us": 0,
                    "source_span_ids": [span.get("span_id")],
                    "source_subtitle_count": 1,
                    "subtitle_texts": [row.get("subtitle_text") or ""],
                    "text_overrides": {uid: override} if override else {},
                    "partial_reason": "text_override" if override else "",
                    "drop_boundary_strict": (index - 1 in drop_indices) or (index + 1 in drop_indices),
                }
            )

    merged: list[dict[str, Any]] = []
    for region in regions:
        if not merged:
            merged.append(deepcopy(region))
            continue
        current = merged[-1]
        adjacent = int(region["subtitle_start_index"]) == int(current["subtitle_end_index"]) + 1
        gap = int(region["cut_start_us"]) - int(current["cut_end_us"])
        has_override_boundary = bool(region.get("text_overrides")) or bool(current.get("text_overrides"))
        if adjacent and gap <= merge_gap and not has_override_boundary:
            current["subtitle_end_uid"] = region["subtitle_end_uid"]
            current["subtitle_end_index"] = region["subtitle_end_index"]
            current["cut_end_us"] = max(int(current["cut_end_us"]), int(region["cut_end_us"]))
            current["target_duration_us"] = int(current["cut_end_us"]) - int(current["cut_start_us"])
            current["source_span_ids"].extend(region.get("source_span_ids") or [])
            current["source_subtitle_count"] += 1
            current["subtitle_texts"].extend(region.get("subtitle_texts") or [])
            current["drop_boundary_strict"] = bool(current.get("drop_boundary_strict")) or bool(region.get("drop_boundary_strict"))
        else:
            merged.append(deepcopy(region))

    edl: list[dict[str, Any]] = []
    target_start = 0
    for index, region in enumerate(merged, start=1):
        clip = deepcopy(region)
        clip["clip_id"] = f"auto_{index:03d}"
        clip["target_start_us"] = target_start
        clip["pause_after_us"] = 0
        clip["boundary_mode"] = "auto_optimizer_tight_overlap_aware"
        edl.append(clip)
        target_start += int(clip["target_duration_us"])
    metadata = {
        "strict_drop_boundary_applied_count": strict_applied,
        "merge_keep_gap_us": merge_gap,
        "lead_guard_us": lead_guard,
        "tail_guard_us": tail_guard,
    }
    return edl, metadata


def update_material_text(material: dict[str, Any], new_text: str) -> dict[str, Any]:
    cloned = deepcopy(material)
    cloned["id"] = guid()
    cloned["recognize_text"] = new_text
    cloned["words"] = {}
    cloned["current_words"] = {}
    cloned.pop("subtitle_keywords", None)
    for key in ("content", "base_content"):
        value = cloned.get(key)
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except Exception:
                continue
            if isinstance(parsed, dict):
                parsed["text"] = new_text
                for style in parsed.get("styles") or []:
                    if isinstance(style, dict) and "range" in style:
                        style["range"] = [0, len(new_text)]
                cloned[key] = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        elif isinstance(value, dict):
            value["text"] = new_text
            for style in value.get("styles") or []:
                if isinstance(style, dict) and "range" in style:
                    style["range"] = [0, len(new_text)]
            cloned[key] = value
    return cloned


def rewrite_text_segments_overlap_aware(
    data: dict[str, Any],
    old_text_segments: list[dict[str, Any]],
    subtitles: list[dict[str, Any]],
    edl: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    text_materials = (data.get("materials") or {}).setdefault("texts", [])
    text_by_id = {str(material.get("id") or ""): material for material in text_materials}
    segment_by_id = {str(segment.get("id") or ""): segment for segment in old_text_segments if segment.get("id")}
    rewritten: list[dict[str, Any]] = []
    report_rows: list[dict[str, Any]] = []
    partial_without_override = 0
    material_clones = 0

    for clip in edl:
        clip_start = int(clip["cut_start_us"])
        clip_end = int(clip["cut_end_us"])
        target_start = int(clip["target_start_us"])
        overrides = clip.get("text_overrides") or {}
        clip_subtitle_start = int(clip["subtitle_start_index"])
        clip_subtitle_end = int(clip["subtitle_end_index"])
        for row in subtitles:
            row_index = int(row["subtitle_index"])
            if row_index < clip_subtitle_start or row_index > clip_subtitle_end:
                continue
            source_start = int(row["start_us"])
            source_end = int(row["end_us"])
            overlap_start = max(source_start, clip_start)
            overlap_end = min(source_end, clip_end)
            if overlap_end <= overlap_start:
                continue
            source_segment = segment_by_id.get(str(row["text_segment_id"]))
            if not source_segment:
                continue
            new_segment = deepcopy(source_segment)
            new_segment["id"] = guid()
            new_start = target_start + (overlap_start - clip_start)
            new_duration = overlap_end - overlap_start
            target_timerange = deepcopy(new_segment.get("target_timerange") or {})
            target_timerange["start"] = new_start
            target_timerange["duration"] = new_duration
            new_segment["target_timerange"] = target_timerange
            new_text = None
            override = overrides.get(row["subtitle_uid"])
            partial = overlap_start > source_start or overlap_end < source_end
            if override and override.get("text_override"):
                new_text = str(override["text_override"])
            elif partial:
                partial_without_override += 1
            if new_text is not None:
                old_material = text_by_id.get(str(source_segment.get("material_id") or ""))
                if old_material:
                    cloned = update_material_text(old_material, new_text)
                    text_materials.append(cloned)
                    text_by_id[cloned["id"]] = cloned
                    new_segment["material_id"] = cloned["id"]
                    material_clones += 1
            rewritten.append(new_segment)
            report_rows.append(
                {
                    "clip_id": clip["clip_id"],
                    "subtitle_uid": row["subtitle_uid"],
                    "old_text": row.get("subtitle_text") or "",
                    "new_text": new_text or row.get("subtitle_text") or "",
                    "partial_subtitle_clip": partial,
                    "has_text_override": new_text is not None,
                    "old_start_us": source_start,
                    "old_end_us": source_end,
                    "overlap_start_us": overlap_start,
                    "overlap_end_us": overlap_end,
                    "new_start_us": new_start,
                    "new_duration_us": new_duration,
                }
            )
    rewritten.sort(key=segment_start)
    return rewritten, {
        "rows": report_rows,
        "partial_subtitle_without_override": partial_without_override,
        "material_clone_count": material_clones,
    }


def validate_subtitles_inside_clips(text_segments: list[dict[str, Any]], video_segments: list[dict[str, Any]]) -> int:
    video_ranges = [(segment_start(segment), segment_end(segment)) for segment in video_segments]
    outside = 0
    for segment in text_segments:
        start = segment_start(segment)
        end = segment_end(segment)
        if not any(start >= vs and end <= ve for vs, ve in video_ranges):
            outside += 1
    return outside


def scan_residual_texts(text_rows: list[dict[str, Any]], edl: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    texts = [str(row.get("new_text") or row.get("subtitle_text") or "") for row in text_rows]
    residuals: list[dict[str, Any]] = []
    repeat_patterns = [
        "人家年少的时候你就把他当成寻",
        "人家人家年少的时候",
        "随意的肆意的踩踏",
        "你跪在地上你跪在地上",
        "评论区评论区",
        "恨不得给恨不得给",
        "你是极你们是",
        "给给老子",
        "重新上重新上",
    ]
    for row, text in zip(text_rows, texts):
        for pattern in repeat_patterns:
            if pattern in text:
                residuals.append(
                    {
                        "type": "known_residual_pattern",
                        "pattern": pattern,
                        "text": text,
                        "subtitle_uid": row.get("subtitle_uid"),
                    }
                )
    for prev_row, curr_row in zip(text_rows, text_rows[1:]):
        prev = str(prev_row.get("new_text") or prev_row.get("subtitle_text") or "")
        curr = str(curr_row.get("new_text") or curr_row.get("subtitle_text") or "")
        if prev and curr and curr.startswith(prev) and len(prev) >= 4:
            residuals.append(
                {
                    "type": "adjacent_prefix_repeat",
                    "previous": prev,
                    "current": curr,
                    "previous_uid": prev_row.get("subtitle_uid"),
                    "current_uid": curr_row.get("subtitle_uid"),
                }
            )
        prev_norm = normalize_compact_text(prev)
        curr_norm = normalize_compact_text(curr)
        if prev_norm and curr_norm and curr_norm.startswith(prev_norm[: max(4, min(len(prev_norm), 8))]) and len(prev_norm) < len(curr_norm):
            residuals.append(
                {
                    "type": "adjacent_weak_prefix_candidate",
                    "previous": prev,
                    "current": curr,
                    "previous_uid": prev_row.get("subtitle_uid"),
                    "current_uid": curr_row.get("subtitle_uid"),
                }
            )
    gaps: list[int] = []
    if edl:
        for prev, curr in zip(edl, edl[1:]):
            gap = int(curr["target_start_us"]) - (int(prev["target_start_us"]) + int(prev["target_duration_us"]))
            if gap > 120_000:
                gaps.append(gap)
    subtitle_rows = sorted(
        text_rows,
        key=lambda row: int(row.get("new_start_us") or row.get("start_us") or 0),
    )
    subtitle_gaps: list[int] = []
    for prev, curr in zip(subtitle_rows, subtitle_rows[1:]):
        prev_end = int(prev.get("new_start_us") or prev.get("start_us") or 0) + int(prev.get("new_duration_us") or prev.get("duration_us") or 0)
        curr_start = int(curr.get("new_start_us") or curr.get("start_us") or 0)
        gap = curr_start - prev_end
        if gap > 120_000:
            subtitle_gaps.append(gap)
    feedback_keywords = {
        "weak_fragment_removed": not any("人家年少的时候你就把他当成寻" in text for text in texts),
        "full_youyuegan_present": any("寻找优越感的弱智对象" in text for text in texts),
        "suiyi_ruyi_fixed": any(text == "肆意的踩踏" for text in texts) and not any("随意的肆意的踩踏" in text for text in texts),
        "kneel_repeat_present": any("你跪在地上你跪在地上" in text for text in texts),
        "kneel_fixed_text_present": any(text == "你跪在地上叫大佬" for text in texts),
        "jiahao_split_fixed": any(text == "你嘲笑嘉豪是" for text in texts) and any(text == "对自己人的规训" for text in texts),
    }
    return {
        "residual_text_repeat_count": len(residuals),
        "residuals": residuals,
        "long_pause_count": len(gaps) + len(subtitle_gaps),
        "clip_gap_long_pause_count": len(gaps),
        "subtitle_gap_long_pause_count": len(subtitle_gaps),
        "max_pause_us": max(gaps + subtitle_gaps) if (gaps or subtitle_gaps) else 0,
        "feedback_keywords": feedback_keywords,
        "final_transcript": "\n".join(texts),
    }


def scan_residuals(edl: list[dict[str, Any]], subtitle_report: dict[str, Any]) -> dict[str, Any]:
    return scan_residual_texts(subtitle_report.get("rows") or [], edl)


def score_candidate(score_input: dict[str, Any]) -> dict[str, Any]:
    if score_input["fatal_reasons"]:
        score = 0
    else:
        score = 100
        score -= score_input["subtitle_outside_clip_count"] * 20
        score -= score_input["partial_subtitle_without_override"] * 8
        score -= score_input["residual_text_repeat_count"] * 10
        score -= score_input["long_pause_count"] * 5
        score -= score_input["semantic_risk_count"] * 3
        if not score_input["known_feedback_fixed"]["kneel_repeat_text_fixed"]:
            score -= 25
        if not score_input["known_feedback_fixed"]["jiahao_regulation_text_fixed"]:
            score -= 18
        if not score_input["known_feedback_fixed"].get("weak_fragment_removed"):
            score -= 35
        if not score_input["known_feedback_fixed"].get("full_youyuegan_present"):
            score -= 25
        if not score_input["known_feedback_fixed"].get("suiyi_ruyi_fixed"):
            score -= 18
        if score_input["final_duration_us"] > 210_000_000:
            score -= (score_input["final_duration_us"] - 210_000_000) // 10_000_000
        if score_input["final_duration_us"] < 170_000_000:
            score -= (170_000_000 - score_input["final_duration_us"]) // 5_000_000
        score = max(0, score)
    score_input["score"] = score
    return score_input


def candidate_params() -> list[dict[str, Any]]:
    base = {
        "lead_guard_us": 60_000,
        "tail_guard_us": 100_000,
        "strict_drop_boundary_guard_us": 0,
        "merge_keep_gap_us": 80_000,
        "kneel_micro_lead_us": 0,
        "kneel_tail_guard_us": 20_000,
        "include_medium_prefix_drops": False,
        "include_medium_deepseek_drops": False,
        "include_medium_micro_cleanups": False,
        "include_medium_local_drops": False,
    }
    return [
        {**base, "candidate": "candidate_01", "jiahao_cleanup": True, "kneel_start_nudge_us": 0},
        {**base, "candidate": "candidate_02", "jiahao_cleanup": True, "kneel_start_nudge_us": 60_000, "lead_guard_us": 40_000, "tail_guard_us": 80_000, "merge_keep_gap_us": 60_000, "include_medium_prefix_drops": True, "include_medium_local_drops": True, "drop_restart_after_sub24": True},
        {**base, "candidate": "candidate_03", "jiahao_cleanup": True, "kneel_start_nudge_us": 100_000, "lead_guard_us": 30_000, "tail_guard_us": 60_000, "merge_keep_gap_us": 40_000, "include_medium_prefix_drops": True, "include_medium_micro_cleanups": True, "include_medium_local_drops": True, "drop_restart_after_sub24": True},
        {**base, "candidate": "candidate_04", "jiahao_cleanup": True, "kneel_start_nudge_us": 140_000, "lead_guard_us": 20_000, "tail_guard_us": 45_000, "merge_keep_gap_us": 25_000, "include_medium_prefix_drops": True, "include_medium_deepseek_drops": True, "include_medium_micro_cleanups": True, "include_medium_local_drops": True, "drop_restart_after_sub24": True},
    ]


def run_candidate(
    args: argparse.Namespace,
    auto_dir: Path,
    timeline_id: str,
    params: dict[str, Any],
    script_clean: str,
    system_decisions: dict[str, Any],
) -> dict[str, Any]:
    candidate_dir = auto_dir / params["candidate"]
    candidate_dir.mkdir(parents=True, exist_ok=True)
    restore_original_backup(args.draft_dir, timeline_id, args.source_backup)

    timeline_dir = args.draft_dir / "Timelines" / timeline_id
    encrypted_path = timeline_dir / "draft_content.json"
    plain_before = candidate_dir / "draft_content.before.dec.json"
    plain_modified = candidate_dir / "draft_content.modified.dec.json"
    encrypted_out = candidate_dir / "draft_content.modified.enc.json"
    plain_after = candidate_dir / "draft_content.after.dec.json"

    decrypt(args.jy_draftc, encrypted_path, plain_before)
    data = read_json_file(plain_before)
    assert_timeline_content_id(data, timeline_id, encrypted_path)
    assert_layout_has_no_duplicate_timeline_ids(args.draft_dir)
    assert_all_project_timeline_files_match_folder_ids(args.draft_dir, args.jy_draftc, candidate_dir)
    root_required = root_mirrors_timeline_id(args.draft_dir, args.jy_draftc, candidate_dir, timeline_id)

    video_candidates, selected_main, video_fatals, video_warnings, main_speed_safe = inspect_video_tracks(data)
    subtitles, text_tracks, selected_text_track = subtitle_timeline(data)
    audio_tracks, has_independent_audio, has_complex_audio, audio_fatals = inspect_audio_tracks(data)
    main_total_duration_us = int((selected_main or {}).get("total_target_duration_us") or 0)
    filter_tracks, has_global_filter, has_complex_filter, filter_fatals = inspect_filter_tracks(data, main_total_duration_us)
    fatal_reasons = list(video_fatals)
    warnings = list(video_warnings)
    if not selected_main:
        fatal_reasons.append("MAIN_VIDEO_TRACK_NOT_FOUND")
    if not selected_text_track:
        fatal_reasons.append("TEXT_TRACK_NOT_FOUND")
    if len(subtitles) != 115:
        fatal_reasons.append(f"UNEXPECTED_SUBTITLE_COUNT:{len(subtitles)}")
    if main_total_duration_us < 300_000_000:
        fatal_reasons.append(f"RESTORE_NOT_FULL_SOURCE_DURATION:{main_total_duration_us}")
    if audio_tracks or has_independent_audio or has_complex_audio:
        fatal_reasons.append("AUDIO_TRACK_PRESENT_UNSUPPORTED")
        fatal_reasons.extend(audio_fatals)
    if filter_tracks or has_global_filter or has_complex_filter:
        fatal_reasons.append("FILTER_TRACK_PRESENT_UNSUPPORTED")
        fatal_reasons.extend(filter_fatals)
    if not main_speed_safe:
        fatal_reasons.append("MAIN_VIDEO_SPEED_UNSAFE")
    if fatal_reasons:
        raise RuntimeError(f"CANDIDATE_PREFLIGHT_BLOCKED:{params['candidate']}:{fatal_reasons}")

    (candidate_dir / "script_reference_clean.txt").write_text(script_clean, "utf-8")
    write_json(candidate_dir / "subtitle_timeline.before.json", subtitles)
    clusters = read_json(args.deepseek_run / "take_clusters.json")
    decisions = read_json(args.deepseek_run / "deepseek_aroll_decisions.json")
    review_text = (args.deepseek_run / "human_review_drops.md").read_text("utf-8")
    reviewed, conservative_summary = conservative_review(clusters, decisions, review_text)
    diagnosis, text_overrides = build_feedback_overrides(subtitles, params)
    residual_before = scan_residual_texts(subtitles, None)
    reviewed, system_apply_summary = apply_system_cleanup(reviewed, subtitles, system_decisions, params, text_overrides)
    write_json(candidate_dir / "residual_cleanup_diagnosis.json", diagnosis)
    write_json(candidate_dir / "system_cleanup_apply_summary.json", system_apply_summary)
    write_json(candidate_dir / "residual_scan_before.json", residual_before)
    write_json(candidate_dir / "candidate_decisions.json", reviewed)
    edl, edl_meta = build_candidate_edl(reviewed, subtitles, main_total_duration_us, text_overrides, params)
    write_json(candidate_dir / "candidate_edl.json", edl)

    backup_paths = backup_draft_files(args.draft_dir, timeline_id, candidate_dir, root_required)
    main_track = get_track(data, str(selected_main["track_id"]))
    text_track = get_track(data, str(selected_text_track["track_id"]))
    if main_track is None or text_track is None:
        raise RuntimeError("TRACK_NOT_FOUND_DURING_CANDIDATE_WRITE")
    old_video_segments = deepcopy(main_track.get("segments") or [])
    old_text_segments = deepcopy(text_track.get("segments") or [])
    new_video_segments, video_split_rows = split_video_segments_for_edl(old_video_segments, edl)
    new_text_segments, subtitle_rewrite_report = rewrite_text_segments_overlap_aware(data, old_text_segments, subtitles, edl)
    if not new_video_segments or not new_text_segments:
        raise RuntimeError("CANDIDATE_REWRITE_EMPTY")

    main_track["segments"] = new_video_segments
    text_track["segments"] = new_text_segments
    data["duration"] = total_target_duration(new_video_segments)

    write_json(candidate_dir / "subtitle_rewrite_report.json", subtitle_rewrite_report)
    write_json(plain_modified, data)
    encrypt(args.jy_draftc, plain_modified, encrypted_out)
    targets = [timeline_dir / "draft_content.json", timeline_dir / "template-2.tmp"]
    if root_required:
        targets.extend([args.draft_dir / "draft_content.json", args.draft_dir / "template-2.tmp"])
    target_writes = write_encrypted_to_targets(encrypted_out, targets)
    decrypt(args.jy_draftc, encrypted_path, plain_after)
    verify_data = read_json_file(plain_after)
    checks, check_fatals = timeline_id_checks_after(args.draft_dir, args.jy_draftc, candidate_dir, plain_after, encrypted_path, timeline_id)
    root_after = root_mirrors_timeline_id(args.draft_dir, args.jy_draftc, candidate_dir, timeline_id) if root_required else None
    verify_video = get_track(verify_data, str(selected_main["track_id"])) or {}
    verify_text = get_track(verify_data, str(selected_text_track["track_id"])) or {}
    after_video_segments = verify_video.get("segments") or []
    after_text_segments = verify_text.get("segments") or []

    outside = validate_subtitles_inside_clips(after_text_segments, after_video_segments)
    residual_scan = scan_residuals(edl, subtitle_rewrite_report)
    write_json(candidate_dir / "residual_scan_after.json", residual_scan)
    (candidate_dir / "final_transcript_after.txt").write_text(residual_scan.get("final_transcript") or "", "utf-8")
    post_summary = {
        "can_decrypt_after_write": True,
        "timeline_id_checks": checks,
        "root_mirror_matches_after": root_after,
        "video_segment_count": len(after_video_segments),
        "subtitle_segment_count": len(after_text_segments),
        "final_duration_us": total_target_duration(after_video_segments),
        "fatal_reasons": check_fatals,
        "warnings": warnings,
    }
    write_json(candidate_dir / "post_inspect_summary.json", post_summary)

    semantic_risk = sum(int(item.get("semantic_risk") or 0) for item in text_overrides.values())
    score = score_candidate(
        {
            "candidate": params["candidate"],
            "can_decrypt_after_write": True,
            "timeline_root_ok": all(checks.values()) and bool(root_after if root_required else True),
            "video_segment_count": len(after_video_segments),
            "subtitle_segment_count": len(after_text_segments),
            "final_duration_us": total_target_duration(after_video_segments),
            "deleted_subtitle_count": 115 - len({row["subtitle_uid"] for row in subtitle_rewrite_report["rows"]}),
            "micro_cut_count": len(text_overrides),
            "partial_subtitle_without_override": subtitle_rewrite_report["partial_subtitle_without_override"],
            "subtitle_outside_clip_count": outside,
            "known_feedback_fixed": {
                "kneel_repeat_audio_attempted": "sub_000023" in text_overrides,
                "kneel_repeat_text_fixed": residual_scan["feedback_keywords"]["kneel_fixed_text_present"],
                "jiahao_regulation_attempted": bool(params.get("jiahao_cleanup")),
                "jiahao_regulation_text_fixed": residual_scan["feedback_keywords"]["jiahao_split_fixed"],
                "weak_fragment_removed": residual_scan["feedback_keywords"]["weak_fragment_removed"],
                "full_youyuegan_present": residual_scan["feedback_keywords"]["full_youyuegan_present"],
                "suiyi_ruyi_fixed": residual_scan["feedback_keywords"]["suiyi_ruyi_fixed"],
            },
            "residual_text_repeat_count": residual_scan["residual_text_repeat_count"],
            "long_pause_count": residual_scan["long_pause_count"],
            "max_pause_us": residual_scan["max_pause_us"],
            "semantic_risk_count": semantic_risk,
            "fatal_reasons": check_fatals,
        }
    )
    write_json(candidate_dir / "candidate_score.json", score)
    report = {
        "candidate": params["candidate"],
        "params": params,
        "runtime_dir": str(candidate_dir),
        "backup_paths": backup_paths,
        "target_writes": target_writes,
        "conservative_review_summary": conservative_summary,
        "system_cleanup_apply_summary": system_apply_summary,
        "edl_metadata": edl_meta,
        "video_track_before": {
            "segment_count": len(old_video_segments),
            "total_duration_us": total_target_duration(old_video_segments),
        },
        "video_track_after": {
            "segment_count": len(after_video_segments),
            "total_duration_us": total_target_duration(after_video_segments),
        },
        "text_track_before": {"segment_count": len(old_text_segments)},
        "text_track_after": {"segment_count": len(after_text_segments)},
        "score": score,
        "residual_scan_before": str(candidate_dir / "residual_scan_before.json"),
        "residual_scan_after": str(candidate_dir / "residual_scan_after.json"),
        "candidate_edl": str(candidate_dir / "candidate_edl.json"),
        "encrypted_output": str(encrypted_out),
        "root_mirror_required": root_required,
        "root_mirror_matches_after": root_after,
        "timeline_layout_modified": False,
        "fatal_reasons": check_fatals,
        "warnings": warnings,
    }
    write_json(candidate_dir / "candidate_report.json", report)
    return report


def write_best_candidate_to_draft(best: dict[str, Any], draft_dir: Path, timeline_id: str) -> dict[str, Any]:
    encrypted = Path(best["encrypted_output"])
    timeline_dir = draft_dir / "Timelines" / timeline_id
    targets = [timeline_dir / "draft_content.json", timeline_dir / "template-2.tmp"]
    if best.get("root_mirror_required"):
        targets.extend([draft_dir / "draft_content.json", draft_dir / "template-2.tmp"])
    return write_encrypted_to_targets(encrypted, targets)


def make_dropped_transcript_review(best: dict[str, Any], auto_dir: Path) -> Path:
    candidate_dir = Path(best["runtime_dir"])
    decisions = read_json(candidate_dir / "candidate_decisions.json")
    lines = ["# Dropped Transcript Review", ""]
    count = 0
    for span in decisions.get("spans") or []:
        if span.get("decision") != "drop":
            continue
        count += 1
        lines.extend(
            [
                f"## Drop {count:03d}",
                "",
                f"- Drop subtitle: {span.get('subtitle_start_uid')} - {span.get('subtitle_end_uid')}",
                f"- Drop text: {span.get('mapped_text') or ''}",
                f"- Kept instead: {span.get('keep_instead_text') or ''}",
                f"- Reason: {span.get('reason') or ''}",
                f"- Confidence/source: {span.get('system_drop_id') or span.get('take_id') or ''}",
                "",
            ]
        )
    path = auto_dir / "dropped_transcript_review.md"
    path.write_text("\n".join(lines), "utf-8")
    return path


def make_human_review_focus(best: dict[str, Any], auto_dir: Path) -> Path:
    candidate_dir = Path(best["runtime_dir"])
    apply_summary = read_json(candidate_dir / "system_cleanup_apply_summary.json")
    applied_drops = apply_summary.get("applied_drops") or []
    high_drops = [item for item in applied_drops if str(item.get("confidence") or "").lower() == "high"][:5]
    medium_drops = [item for item in applied_drops if str(item.get("confidence") or "").lower() == "medium"][:5]
    path = auto_dir / "human_review_focus.md"
    lines = [
        "# Phase 3E System Cleanup Human Review Focus",
        "",
        f"- Best candidate: {best['candidate']}",
        f"- Final duration: {best['score']['final_duration_us'] / 1_000_000:.2f}s",
        f"- Residual repeat count: {best['score']['residual_text_repeat_count']}",
        f"- Long pause count: {best['score']['long_pause_count']}",
        "",
        "## 必看点",
        "",
        "1. 人家年少的时候 / 寻找优越感：弱残句是否删除，完整句是否保留。",
        "2. 随意的 / 肆意的踩踏：是否只剩更强表达，是否切字。",
        "3. 你跪在地上叫大佬：是否仍保持干净，不回到重复。",
        "4. 你嘲笑嘉豪 / 规训：是否仍顺，不误删语义。",
        "5. 停顿是否仍多，尤其字幕之间是否还有明显 0.3s+ 空气。",
        "6. 是否有切字 / 断尾音。",
        "7. 是否有误删语义。",
        "",
        "## 随机 high-confidence drop",
        "",
    ]
    for item in high_drops:
        lines.append(f"- {item.get('subtitle_start_uid')} {item.get('drop_text')} | {item.get('reason')}")
    lines.extend(["", "## 随机 medium-confidence drop", ""])
    for item in medium_drops:
        lines.append(f"- {item.get('subtitle_start_uid')} {item.get('drop_text')} | {item.get('reason')}")
    lines.extend(
        [
            "",
            "## 风险提示",
            "",
            "- 本轮仍基于字幕和剪映词级时间，不是完整音频 ASR 重新对齐。",
            "- candidate_04 可能更紧，但 medium drop 风险更高，最终选择已按风险扣分。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", "utf-8")
    return path


def run_auto_optimize(args: argparse.Namespace) -> tuple[Path, Path]:
    auto_dir = args.runtime / f"aroll_system_cleanup_{time.strftime('%Y%m%d_%H%M%S')}"
    auto_dir.mkdir(parents=True, exist_ok=True)
    timeline_id, timeline_name = resolve_timeline_id(args.draft_dir, args.timeline_name)
    script_text = args.script_path.read_text("utf-8")
    script_clean = clean_script_markdown(script_text)
    (auto_dir / "script_reference_clean.txt").write_text(script_clean, "utf-8")
    original_subtitles = read_json(args.subtitle_timeline)

    restore_original_backup(args.draft_dir, timeline_id, args.source_backup)
    timeline_dir = args.draft_dir / "Timelines" / timeline_id
    restore_check_dec = auto_dir / "restore_check.dec.json"
    decrypt(args.jy_draftc, timeline_dir / "draft_content.json", restore_check_dec)
    restore_data = read_json_file(restore_check_dec)
    restore_video_candidates, restore_selected_main, restore_video_fatals, restore_video_warnings, restore_speed_safe = inspect_video_tracks(restore_data)
    restore_subtitles, _, _ = subtitle_timeline(restore_data)
    restore_duration_us = int((restore_selected_main or {}).get("total_target_duration_us") or 0)
    restore_report = {
        "restored_from_backup": str(args.source_backup),
        "video_total_duration_us": restore_duration_us,
        "subtitle_count": len(restore_subtitles),
        "can_aroll_rewrite": bool(restore_selected_main and len(restore_subtitles) == 115 and restore_duration_us >= 300_000_000 and not restore_video_fatals and restore_speed_safe),
        "fatal_reasons": restore_video_fatals,
        "warnings": restore_video_warnings,
    }
    write_json(auto_dir / "restore_check_report.json", restore_report)
    if not restore_report["can_aroll_rewrite"]:
        raise RuntimeError(f"RESTORE_CHECK_FAILED:{restore_report}")

    deepseek_call_result: dict[str, Any]
    try:
        system_decisions, deepseek_call_result = call_deepseek_system_cleanup(
            config_path=args.deepseek_config,
            model=args.deepseek_model,
            subtitles=original_subtitles,
            script_clean=script_clean,
            source_duration_us=restore_duration_us,
            out_dir=auto_dir,
        )
    except Exception as exc:
        system_decisions = {"source": "deepseek_system_cleanup_failed", "drop_spans": [], "micro_cleanups": [], "must_keep_warnings": []}
        deepseek_call_result = {
            "success": False,
            "fallback": True,
            "model": args.deepseek_model,
            "error": str(exc),
        }
        write_json(auto_dir / "deepseek_system_cleanup_raw_response.json", deepseek_call_result)
        write_json(auto_dir / "system_cleanup_decisions.json", system_decisions)

    candidates: list[dict[str, Any]] = []
    for params in candidate_params()[: args.max_iterations]:
        report = run_candidate(args, auto_dir, timeline_id, params, script_clean, system_decisions)
        candidates.append(report)

    def rank_candidate(row: dict[str, Any]) -> tuple[int, int, int, int, int]:
        score = row["score"]
        try:
            candidate_order = int(str(row.get("candidate") or "candidate_99").split("_")[-1])
        except Exception:
            candidate_order = 99
        return (
            int(score.get("score") or 0),
            -int(score.get("long_pause_count") or 0),
            -int(score.get("residual_text_repeat_count") or 0),
            -int(score.get("semantic_risk_count") or 0),
            -candidate_order,
        )

    scored = sorted(candidates, key=rank_candidate, reverse=True)
    best = scored[0]
    final_writes = write_best_candidate_to_draft(best, args.draft_dir, timeline_id)
    focus_path = make_human_review_focus(best, auto_dir)
    dropped_review_path = make_dropped_transcript_review(best, auto_dir)
    summary = {
        "draft_dir": str(args.draft_dir),
        "timeline_id": timeline_id,
        "timeline_name": timeline_name,
        "script_path": str(args.script_path),
        "script_read_success": True,
        "script_clean_char_count": len(script_clean),
        "script_used_for_deepseek": True,
        "deepseek_called": True,
        "deepseek_call_count": 1,
        "deepseek_call_result": deepseek_call_result,
        "deepseek_drop_spans_count": len(system_decisions.get("drop_spans") or []),
        "deepseek_micro_cleanups_count": len(system_decisions.get("micro_cleanups") or []),
        "deepseek_must_keep_warnings_count": len(system_decisions.get("must_keep_warnings") or []),
        "restore_check_report": str(auto_dir / "restore_check_report.json"),
        "candidate_count": len(candidates),
        "candidates": [
            {
                "candidate": item["candidate"],
                "runtime_dir": item["runtime_dir"],
                "final_duration_us": item["score"]["final_duration_us"],
                "video_segments": item["score"]["video_segment_count"],
                "subtitle_segments": item["score"]["subtitle_segment_count"],
                "deleted_subtitles": item["score"]["deleted_subtitle_count"],
                "micro_cuts": item["score"]["micro_cut_count"],
                "residual_repeat_count": item["score"]["residual_text_repeat_count"],
                "long_pause_count": item["score"]["long_pause_count"],
                "semantic_risk_count": item["score"]["semantic_risk_count"],
                "partial_subtitle_without_override": item["score"]["partial_subtitle_without_override"],
                "score": item["score"]["score"],
                "fatal_reasons": item["score"]["fatal_reasons"],
            }
            for item in candidates
        ],
        "best_candidate": best["candidate"],
        "best_candidate_runtime": best["runtime_dir"],
        "best_candidate_report": str(Path(best["runtime_dir"]) / "candidate_report.json"),
        "final_writes": final_writes,
        "final_written_candidate": best["candidate"],
        "human_review_focus": str(focus_path),
        "dropped_transcript_review": str(dropped_review_path),
    }
    summary_path = auto_dir / "auto_optimize_summary.json"
    best_path = auto_dir / "best_candidate_report.json"
    final_txt = auto_dir / "final_written_candidate.txt"
    write_json(summary_path, summary)
    write_json(best_path, best)
    final_txt.write_text(best["candidate"] + "\n", "utf-8")
    return auto_dir, summary_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 3E system-level residual/stutter/pause cleanup for the 6月14日 sacrificial draft.")
    parser.add_argument("--draft-dir", type=Path, default=Path(r"D:\JianyingPro Drafts\6月14日"))
    parser.add_argument("--subtitle-timeline", type=Path, default=DEFAULT_ORIGINAL_SUBTITLES)
    parser.add_argument("--script-path", type=Path, default=DEFAULT_SCRIPT)
    parser.add_argument("--deepseek-run", type=Path, default=DEFAULT_DEEPSEEK_RUN)
    parser.add_argument("--deepseek-config", type=Path, default=DEFAULT_DEEPSEEK_CONFIG)
    parser.add_argument("--deepseek-model", default="deepseek-chat")
    parser.add_argument("--source-backup", type=Path, default=DEFAULT_SOURCE_BACKUP)
    parser.add_argument("--timeline-name", default="")
    parser.add_argument("--jy-draftc", type=Path, default=DEFAULT_JY_DRAFTC)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--max-iterations", type=int, default=4)
    args = parser.parse_args()

    auto_dir, summary_path = run_auto_optimize(args)
    summary = read_json(summary_path)
    print("status=ok")
    print(f"runtime={auto_dir}")
    print(f"summary={summary_path}")
    print(f"best_candidate={summary['best_candidate']}")
    print(f"best_candidate_report={summary['best_candidate_report']}")
    print(f"human_review_focus={summary['human_review_focus']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
