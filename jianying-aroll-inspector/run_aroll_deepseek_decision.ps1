param(
  [string]$SubtitleTimeline = "D:\video tools\jianying-aroll-inspector\runtime\aroll_inspect_20260614_111146\subtitle_timeline.json",
  [string]$DeepSeekConfig = "D:\idea-project\videoDataCatcher\src\main\resources\application.yaml",
  [int]$TimeoutSec = 240
)

$ErrorActionPreference = "Stop"

if (!(Test-Path -LiteralPath $SubtitleTimeline)) {
  throw "SubtitleTimeline 不存在：$SubtitleTimeline"
}
if (!(Test-Path -LiteralPath $DeepSeekConfig)) {
  throw "DeepSeekConfig 不存在：$DeepSeekConfig"
}

Write-Host "CONFIRM_SUBTITLE_TIMELINE=$SubtitleTimeline"
Write-Host "CONFIRM_DEEPSEEK_CONFIG=$DeepSeekConfig"
Write-Host "MODE=REAL_DEEPSEEK_AROLL_DECISION_DRYRUN"
Write-Host "NO_DRAFT_WRITE=1"
Write-Host "NO_ENCRYPT=1"
Write-Host "API_KEY_OUTPUT=REDACTED"

$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  $Python = "python"
}

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\aroll_deepseek_decider.py"),
  "--subtitle-timeline", $SubtitleTimeline,
  "--deepseek-config", $DeepSeekConfig,
  "--timeout-sec", "$TimeoutSec"
)

& $Python @ArgsList
