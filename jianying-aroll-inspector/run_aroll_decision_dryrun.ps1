param(
  [string]$SubtitleTimeline = "D:\video tools\jianying-aroll-inspector\runtime\aroll_inspect_20260614_111146\subtitle_timeline.json"
)

$ErrorActionPreference = "Stop"

if (!(Test-Path -LiteralPath $SubtitleTimeline)) {
  throw "SubtitleTimeline 不存在：$SubtitleTimeline"
}

Write-Host "CONFIRM_SUBTITLE_TIMELINE=$SubtitleTimeline"
Write-Host "MODE=READ_ONLY_AROLL_DECISION_DRYRUN"
Write-Host "NO_DRAFT_WRITE=1"
Write-Host "NO_ENCRYPT=1"
Write-Host "NO_DEEPSEEK_API=1"

$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  $Python = "python"
}

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\aroll_decision_dryrun.py"),
  "--subtitle-timeline", $SubtitleTimeline
)

& $Python @ArgsList
