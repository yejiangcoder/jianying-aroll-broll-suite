param(
  [string]$SubtitleTimeline = "D:\video tools\jianying-aroll-inspector\runtime\aroll_inspect_20260614_111146\subtitle_timeline.json",
  [string]$ScriptPath = "D:\idea-project\Jackson WorldViews\src\main\java\jackson\worldviews\content\shoortvideoScript\S16\S16正文脚本\S16-3-嘉豪.md"
)

$ErrorActionPreference = "Stop"

if (!(Test-Path -LiteralPath $SubtitleTimeline)) {
  throw "SubtitleTimeline 不存在：$SubtitleTimeline"
}
if (!(Test-Path -LiteralPath $ScriptPath)) {
  throw "ScriptPath 不存在：$ScriptPath"
}

Write-Host "CONFIRM_SUBTITLE_TIMELINE=$SubtitleTimeline"
Write-Host "CONFIRM_SCRIPT_PATH=$ScriptPath"
Write-Host "MODE=PHASE_4A_READ_ONLY_DIAGNOSTICS"
Write-Host "NO_DRAFT_WRITE=1"
Write-Host "NO_ENCRYPT=1"
Write-Host "NO_DEEPSEEK=1"
Write-Host "NO_TRACK_MODIFICATION=1"

$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  throw "Codex Python 不存在：$Python"
}

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\aroll_phase4_diagnostics.py"),
  "--subtitle-timeline", $SubtitleTimeline,
  "--script-path", $ScriptPath
)

& $Python @ArgsList
