from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path

from align_ai_images import DEFAULT_OUTPUT_ROOT, parse_broll


DEFAULT_CONFIG = Path(r"D:\video tools\jianying-ai-image-aligner\agent_inputs.json")

# S16-1 current Jianying timeline rough dialogue anchors.
# These are not old CSV fallback positions. They are a fresh UI construction map:
# each image starts on the head of the closest current subtitle/dialogue idea,
# with a fixed 1.3s image duration supplied by Jianying's global still-image setting.
ANCHOR_STARTS_SEC = {
    "34": 3.10,   # 看混的人土味视频的人
    "02": 6.10,   # 想从精神小伙身上寻找优越感
    "04": 16.20,  # 格子间 / 笼中犬
    "06": 27.50,  # 掀桌子
    "38": 30.13,  # 工牌 / 公司规训
    "10": 31.20,  # 公司大群收到改三次
    "35": 33.00,  # 县城/村镇真实关系场
    "36": 44.10,  # 体面/做题家虚伪
    "46": 47.00,  # 被规训到失去欲望
    "13": 57.93,  # 低级黄毛和高级黄毛
    "49": 65.07,  # 高级黄毛松弛感 / 野劲
    "15": 72.27,  # 夏日奶茶店美女测试
    "50": 75.50,  # 土味该烧野劲保留
    "44": 79.97,  # 先上去再说 / 要微信
    "42": 83.17,  # 被拒后转头继续
    "25": 85.30,  # 做对题拿高分
    "37": 86.80,  # 等小红花
    "26": 88.20,  # 求外部认可
    "47": 89.60,  # 四重规训压力
    "18": 90.93,  # 余光偷瞄
    "40": 94.67,  # 脑内听证会
    "43": 96.20,  # 理性行动瘫痪
    "19": 99.40,  # 机会为零
    "48": 100.90, # 后退半步
    "20": 102.53, # 周末摇不出妹妹
    "45": 103.90, # 社交资产为零
    "41": 105.30, # 200块组局对照
    "22": 106.70, # 攻击性 / 性张力
    "27": 108.10, # 等待审判的犯人
    "30": 109.50, # 砸碎假体面
    "31": 110.90, # 健身房拉回血性
    "32": 112.30, # 抢回来
    "39": 113.70, # 廉价瓷器自尊
    "51": 115.10, # 扔掉假体面
    "52": 116.50, # 血性靠练
    "53": 117.90, # 别再当旁观者
}


def read_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def image_id(path: Path) -> str:
    match = re.search(r"_AI_(\d{2})_", path.name)
    return match.group(1) if match else ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build current S16-1 1.3s UI construction plan without old CSV fallback.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--duration-sec", type=float, default=1.3)
    args = parser.parse_args()

    cfg = read_config(args.config)
    broll_md = Path(cfg["broll_md"])
    ai_dir = Path(cfg["ai_image_dir"])
    items = parse_broll(broll_md, ai_dir)
    item_by_id = {f"{item.no:02d}": item for item in items}
    missing = sorted(set(ANCHOR_STARTS_SEC) - set(item_by_id))
    if missing:
        raise RuntimeError(f"B-ROLL/AI 图片目录缺少这些 AI 图：{', '.join(missing)}")

    rows = []
    for iid, start in sorted(ANCHOR_STARTS_SEC.items(), key=lambda row: (row[1], row[0])):
        item = item_by_id[iid]
        rows.append(
            {
                "image_id": iid,
                "image_path": str(item.image),
                "start_sec": f"{start:.3f}",
                "end_sec": f"{start + args.duration_sec:.3f}",
                "duration_sec": f"{args.duration_sec:.3f}",
                "matched_subtitle": item.quote,
                "broll_text": item.quote,
                "match_method": "current_script_dialogue_anchor+fixed_1.3s",
                "confidence": "0.750",
            }
        )

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = args.output_root / f"ui_plan_s16_1_current_1p3s_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "alignment_report_1p3s.csv"
    fields = [
        "image_id",
        "image_path",
        "start_sec",
        "end_sec",
        "duration_sec",
        "matched_subtitle",
        "broll_text",
        "match_method",
        "confidence",
    ]
    with report.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    manifest = out_dir / "alignment_manifest_1p3s.json"
    manifest.write_text(
        json.dumps(
            {
                "source": "current_script_dialogue_anchor",
                "config": str(args.config),
                "broll_md": str(broll_md),
                "ai_image_dir": str(ai_dir),
                "duration_sec": args.duration_sec,
                "plan_count": len(rows),
                "report": str(report),
                "rules": {
                    "no_old_alignment_csv": True,
                    "ai_only": True,
                    "duration": "Jianying global still image duration set to 1.3s before UI build",
                    "track": "subtitle first row, AI second row, filter below",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("OK_S16_1_CURRENT_PLAN")
    print(f"placements: {len(rows)}")
    print(f"report: {report}")
    print(f"manifest: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
