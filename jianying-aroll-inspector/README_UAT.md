# A-Roll 工具使用方式

这个工具的生产入口是 Operator Mode。日常不需要手动拼复杂 PowerShell 参数，由 Codex 根据你的自然语言意图调用正确脚本。

## 日常用法

对 Codex 说：

```text
调用 A-ROLL 剪辑工具，开始工作。
```

Codex 会使用默认 profile，自动找到默认草稿，先预检，gate 通过后再写回。

生产入口只认 Operator Mode。`run_aroll_uat_full.ps1`、Phase 4/5 系列脚本属于底层调试入口，不作为日常执行入口。

## 指定草稿

对 Codex 说：

```text
用你的已准备草稿跑 A-Roll。
```

内部等价于：

```powershell
.\run_aroll_operator.ps1 -Intent RunFull -DraftName "YOUR_DRAFT_NAME"
```

## 只做预检

对 Codex 说：

```text
只做预检，先别写回。
```

内部等价于：

```powershell
.\run_aroll_operator.ps1 -Intent PreflightOnly -DraftName "YOUR_DRAFT_NAME"
```

## 清理垃圾

对 Codex 说：

```text
清理 A-Roll 工具垃圾。
```

内部等价于：

```powershell
.\run_aroll_operator.ps1 -Intent Cleanup
```

清理器只处理 `runtime` 临时文件，不删除剪映草稿目录。

## 剪映开着怎么办

默认规则：如果剪映主进程正在运行，工具拒绝写回，避免草稿被剪映覆盖。

你可以先在剪映里保存，然后关闭剪映。

如果你明确授权，可以对 Codex 说：

```text
帮我关闭剪映再跑。
```

内部等价于：

```powershell
.\run_aroll_operator.ps1 -Intent RunFull -DraftName "YOUR_DRAFT_NAME" -AutoCloseJianying
```

## 默认支持

- 1.0x 主视频
- 1.2x constant speed 主视频
- <= 1.25x constant speed 主视频
- 主视频 segment/material 上的音量、人声增强、降噪、figure / beauty refs 克隆保留
- 写后检查 speed refs、volume fields、audio enhancement、attached refs 是否保留
- Semantic gate 使用“本地候选发现 + DeepSeek 语义仲裁 + 保守 source keep 修复”。DeepSeek 只裁决语义，不生成 EDL，不写草稿。

## 当前不支持

- 曲线变速
- 倒放
- mixed speed
- 独立 audio track
- 全局 audio / filter track
- 无法识别或无法克隆的 attached refs

## 默认 profile

默认配置在：

```text
D:\video tools\jianying-aroll-inspector\aroll_operator_profile.json
```

公开 release 默认只提供：

```text
profiles\production.json
profiles\default_profile.json
```

这些文件里的 `EDIT_ME_DRAFT_ROOT` / `EDIT_ME_DRAFT_NAME` 是模板占位符。第一次使用必须编辑 profile，或显式传入 `-DraftDir` / `-DraftName`；否则工具会明确报 `PROFILE_NOT_CONFIGURED`。

核心默认值：

```text
default_draft_name = YOUR_DRAFT_NAME
allow_constant_speed = true
max_allowed_speed = 1.25
runtime_mode = production
run_cleanup_before = true
run_cleanup_after = true
keep_debug_dec_json = false
keep_audio_pcm = false
auto_close_jianying = false
```

## 你需要验收什么

工具完成后重点检查：

1. 是否有重复句
2. 是否切字 / 断尾音
3. 字幕是否不长、不碎、不飞轨
4. 1.2x 变速是否正常
5. 声音增强是否仍在
6. 气口是否可接受

重点报告：

```text
codex_self_review_report.md
uat_self_review_summary.md
write_report.json
gate_check.json
operator_summary.json
semantic_repair_loop_report.json
semantic_llm_arbiter_results.json
```

`human_review_focus.md` 仅作为旧脚本兼容文件保留，内容应只提示已废弃并指向 `codex_self_review_report.md`。

## Dev snapshot

给外部静态 review 使用：

```powershell
.\run_aroll_make_dev_snapshot.ps1
```

dev snapshot 不包含 `runtime/`、`release/`、解密草稿 JSON、临时音频或旧 PoC runtime。

## 附录：底层入口

正常生产不要直接用底层入口，除非调试。

```powershell
cd "D:\video tools\jianying-aroll-inspector"
.\run_aroll_uat_full.ps1 -DraftDir "EDIT_ME_DRAFT_DIR"
```

复杂参数仍然保留给工程调试，但不作为日常使用方式。
