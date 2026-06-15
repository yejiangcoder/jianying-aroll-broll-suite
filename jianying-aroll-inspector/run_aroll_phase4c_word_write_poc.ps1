param(
  [string]$DraftDir = "D:\JianyingPro Drafts\6月14日",
  [string]$BackupDir = "D:\video tools\jianying-aroll-inspector\runtime\aroll_roughcut_write_20260614_111435\backup",
  [string]$Phase4BDir = "D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4b_word_edl_dryrun_20260614_172532",
  [string]$SubtitleTimeline = "D:\video tools\jianying-aroll-inspector\runtime\aroll_inspect_20260614_111146\subtitle_timeline.json"
)

$ErrorActionPreference = "Stop"

if (!(Test-Path -LiteralPath $DraftDir)) {
  throw "DraftDir 不存在：$DraftDir"
}
if (!(Test-Path -LiteralPath $BackupDir)) {
  throw "BackupDir 不存在：$BackupDir"
}
if (!(Test-Path -LiteralPath $Phase4BDir)) {
  throw "Phase4BDir 不存在：$Phase4BDir"
}
if (!(Test-Path -LiteralPath $SubtitleTimeline)) {
  throw "SubtitleTimeline 不存在：$SubtitleTimeline"
}

Write-Host "CONFIRM_DRAFT_DIR=$DraftDir"
Write-Host "CONFIRM_BACKUP_DIR=$BackupDir"
Write-Host "CONFIRM_PHASE4B_DIR=$Phase4BDir"
Write-Host "MODE=PHASE_4C_WORD_LEVEL_WRITE_POC"
Write-Host "RESTORE_ORIGINAL_FULL_DRAFT=1"
Write-Host "WRITE_CANDIDATE_DRAFTS_ONLY=1"
Write-Host "NO_FULL_EDL_WRITE=1"
Write-Host "NO_DEEPSEEK=1"
Write-Host "NO_AUDIO_FILTER_TRACK_MODIFICATION=1"
Write-Host "NO_PROJECT_JSON_OR_TIMELINE_LAYOUT_CHANGE=1"

$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  throw "Codex Python 不存在：$Python"
}

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\aroll_phase4c_word_write_poc.py"),
  "--draft-dir", $DraftDir,
  "--backup-dir", $BackupDir,
  "--phase4b-dir", $Phase4BDir,
  "--subtitle-timeline", $SubtitleTimeline
)

& $Python @ArgsList
