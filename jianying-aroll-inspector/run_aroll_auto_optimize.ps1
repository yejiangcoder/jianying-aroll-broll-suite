param(
  [string]$DraftDir = "D:\JianyingPro Drafts\6月14日",
  [string]$SubtitleTimeline = "D:\video tools\jianying-aroll-inspector\runtime\aroll_inspect_20260614_111146\subtitle_timeline.json",
  [string]$ScriptPath = "D:\idea-project\Jackson WorldViews\src\main\java\jackson\worldviews\content\shoortvideoScript\S16\S16正文脚本\S16-3-嘉豪.md",
  [string]$DeepSeekRun = "D:\video tools\jianying-aroll-inspector\runtime\aroll_deepseek_decision_20260614_114516",
  [int]$MaxIterations = 4
)

$ErrorActionPreference = "Stop"

if (!(Test-Path -LiteralPath $DraftDir)) {
  throw "DraftDir 不存在：$DraftDir"
}
if (!(Test-Path -LiteralPath $SubtitleTimeline)) {
  throw "SubtitleTimeline 不存在：$SubtitleTimeline"
}
if (!(Test-Path -LiteralPath $ScriptPath)) {
  throw "ScriptPath 不存在：$ScriptPath"
}
if (!(Test-Path -LiteralPath $DeepSeekRun)) {
  throw "DeepSeekRun 不存在：$DeepSeekRun"
}

Write-Host "CONFIRM_DRAFT_DIR=$DraftDir"
Write-Host "CONFIRM_SUBTITLE_TIMELINE=$SubtitleTimeline"
Write-Host "CONFIRM_SCRIPT_PATH=$ScriptPath"
Write-Host "CONFIRM_DEEPSEEK_RUN=$DeepSeekRun"
Write-Host "MODE=AROLL_AUTO_OPTIMIZE_LONG_RUN"
Write-Host "WILL_WRITE_TEST_DRAFT=1"
Write-Host "NO_PROJECT_JSON_WRITE=1"
Write-Host "NO_TIMELINE_LAYOUT_WRITE=1"
Write-Host "NO_API_KEY_OUTPUT=1"

$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  $Python = "python"
}

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\aroll_auto_optimizer.py"),
  "--draft-dir", $DraftDir,
  "--subtitle-timeline", $SubtitleTimeline,
  "--script-path", $ScriptPath,
  "--deepseek-run", $DeepSeekRun,
  "--max-iterations", "$MaxIterations"
)

& $Python @ArgsList
