from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = (
    "你是 A-Roll 口播剪辑语义仲裁器。你不负责剪辑时间轴，不写剪映草稿，"
    "不输出 EDL，不输出 material_id / source_timerange / target_timerange。"
    "你只判断 source candidate 是否可删、是否应保留、是否已被 final transcript 等价覆盖。"
    "原稿只是语义参考，不是逐字强约束。字幕来自剪映 ASR，可能错字、断句错误、口音误识别。"
    "完整有效观点不能丢；口吃、半句、重复 take、修正前废句可以删除或清理。"
    "不确定时判 codex_self_review_required，并把 approved_action 设为 self_review。只输出严格 JSON。"
)


def build_semantic_arbiter_messages(units: list[dict[str, Any]]) -> list[dict[str, str]]:
    payload = {
        "task": "aroll_candidate_semantic_arbitration",
        "output_schema": {
            "results": [
                {
                    "candidate_id": "cand_0001",
                    "classification": "approve_drop|approve_micro_cleanup|required_clean_unit_covered|semantic_containment_covered|dirty_stutter_unit|duplicate_take_covered|keep_both|micro_cleanup_covered|true_missing_required_unit|not_required_filler|codex_self_review_required",
                    "approved_action": "drop|trim|keep|drop_left|drop_right|keep_both|self_review",
                    "covered_by_final": True,
                    "final_equivalent_text": "",
                    "should_block_write": False,
                    "confidence": "high|medium|low",
                    "reason": "",
                }
            ]
        },
        "rules": [
            "不要逐字洁癖，判断语义等价。",
            "完整有效观点不能丢。",
            "口吃、重启、半句、重复 take 可以不保留。",
            "如果 proposed_action 是 drop，只有确信是口吃/半句/重复/已等价覆盖时才 approve_drop。",
            "如果 candidate_type 以 final_ 开头，这是成片后残留重复仲裁：只有 left_text 是废起头、重复 take、或完全被 right_text 覆盖时才能批准删除。",
            "final_ candidate 必须在 drop_left、drop_right、keep_both、self_review 中选择，不要只回 drop。",
            "如果 left_text 和 right_text 都有独立语义，即使相似，也必须 keep_both 或 self_review。",
            "如果 proposed_action 是 micro_cleanup，只有确信清理后语义不丢时才 approve_micro_cleanup。",
            "不确定时 codex_self_review_required + self_review。",
            "不要输出任何草稿字段、时间轴字段、material_id 或 timerange。",
        ],
        "candidates": units,
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
