param(
  [string]$Phase4ADir = "D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4_diagnostics_20260614_171206",
  [string]$SubtitleTimeline = "D:\video tools\jianying-aroll-inspector\runtime\aroll_inspect_20260614_111146\subtitle_timeline.json",
  [string]$ScriptPath = "D:\idea-project\Jackson WorldViews\src\main\java\jackson\worldviews\content\shoortvideoScript\S16\S16正文脚本\S16-3-嘉豪.md"
)

$ErrorActionPreference = "Stop"

if (!(Test-Path -LiteralPath $Phase4ADir)) {
  throw "Phase4ADir 不存在：$Phase4ADir"
}
if (!(Test-Path -LiteralPath $SubtitleTimeline)) {
  throw "SubtitleTimeline 不存在：$SubtitleTimeline"
}
if (!(Test-Path -LiteralPath $ScriptPath)) {
  throw "ScriptPath 不存在：$ScriptPath"
}

Write-Host "CONFIRM_PHASE4A_DIR=$Phase4ADir"
Write-Host "CONFIRM_SUBTITLE_TIMELINE=$SubtitleTimeline"
Write-Host "CONFIRM_SCRIPT_PATH=$ScriptPath"
Write-Host "MODE=PHASE_4B_WORD_LEVEL_EDL_DRYRUN"
Write-Host "NO_DRAFT_WRITE=1"
Write-Host "NO_ENCRYPT=1"
Write-Host "NO_DEEPSEEK=1"
Write-Host "NO_TRACK_MODIFICATION=1"
Write-Host "NO_PROJECT_JSON_OR_TIMELINE_LAYOUT_CHANGE=1"

$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  throw "Codex Python 不存在：$Python"
}

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\aroll_phase4b_dryrun.py"),
  "--phase4a-dir", $Phase4ADir,
  "--subtitle-timeline", $SubtitleTimeline,
  "--script-path", $ScriptPath
)

& $Python @ArgsList
