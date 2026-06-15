param(
  [string]$DraftDir = "D:\JianyingPro Drafts\6月14日",
  [string]$SubtitleTimeline = "D:\video tools\jianying-aroll-inspector\runtime\aroll_inspect_20260614_111146\subtitle_timeline.json",
  [string]$ScriptPath = "D:\idea-project\Jackson WorldViews\src\main\java\jackson\worldviews\content\shoortvideoScript\S16\S16正文脚本\S16-3-嘉豪.md",
  [string]$DeepSeekRun = "D:\video tools\jianying-aroll-inspector\runtime\aroll_deepseek_decision_20260614_114516",
  [string]$DeepSeekConfig = "D:\idea-project\videoDataCatcher\src\main\resources\application.yaml",
  [string]$DeepSeekModel = "deepseek-chat",
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
if (!(Test-Path -LiteralPath $DeepSeekConfig)) {
  throw "DeepSeekConfig 不存在：$DeepSeekConfig"
}

Write-Host "CONFIRM_DRAFT_DIR=$DraftDir"
Write-Host "CONFIRM_SUBTITLE_TIMELINE=$SubtitleTimeline"
Write-Host "CONFIRM_SCRIPT_PATH=$ScriptPath"
Write-Host "CONFIRM_DEEPSEEK_RUN=$DeepSeekRun"
Write-Host "CONFIRM_DEEPSEEK_CONFIG=$DeepSeekConfig"
Write-Host "CONFIRM_DEEPSEEK_MODEL=$DeepSeekModel"
Write-Host "MODE=AROLL_CORRECTIVE_V5_PHASE_3F"
Write-Host "WILL_RESTORE_FULL_BACKUP=1"
Write-Host "WILL_WRITE_TEST_DRAFT=1"
Write-Host "NO_PROJECT_JSON_WRITE=1"
Write-Host "NO_TIMELINE_LAYOUT_WRITE=1"
Write-Host "NO_API_KEY_OUTPUT=1"

$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  throw "Codex Python 不存在：$Python"
}

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\aroll_corrective_v5_optimizer.py"),
  "--draft-dir", $DraftDir,
  "--subtitle-timeline", $SubtitleTimeline,
  "--script-path", $ScriptPath,
  "--deepseek-run", $DeepSeekRun,
  "--deepseek-config", $DeepSeekConfig,
  "--deepseek-model", $DeepSeekModel,
  "--max-iterations", "$MaxIterations"
)

& $Python @ArgsList
