param(
  [string]$DraftDir = "D:\JianyingPro Drafts\6月14日",
  [string]$BackupDir = "D:\video tools\jianying-aroll-inspector\runtime\aroll_roughcut_write_20260614_111435\backup",
  [string]$PreviousDir = "D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4c2_corrected_word_poc_20260614_180716",
  [string]$WordTimeline = "D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4_diagnostics_20260614_171206\word_timeline.json"
)

$ErrorActionPreference = "Stop"

foreach ($PathToCheck in @($DraftDir, $BackupDir, $PreviousDir, $WordTimeline)) {
  if (!(Test-Path -LiteralPath $PathToCheck)) {
    throw "路径不存在：$PathToCheck"
  }
}

Write-Host "CONFIRM_DRAFT_DIR=$DraftDir"
Write-Host "MODE=PHASE_4C3_SENTENCE_GAP_HIDDEN_REPEAT_POC"
Write-Host "RESTORE_ORIGINAL_FULL_DRAFT=1"
Write-Host "WRITE_SINGLE_TEST_DRAFT_ONLY=1"
Write-Host "NO_EXTRA_CANDIDATE_DRAFT_DIR=1"
Write-Host "NO_DEEPSEEK=1"
Write-Host "NO_AUDIO_FILTER_TRACK_MODIFICATION=1"
Write-Host "NO_PROJECT_JSON_OR_TIMELINE_LAYOUT_CHANGE=1"

$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  throw "Codex Python 不存在：$Python"
}

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\aroll_phase4c3_sentence_gap_poc.py"),
  "--draft-dir", $DraftDir,
  "--backup-dir", $BackupDir,
  "--previous-dir", $PreviousDir,
  "--word-timeline", $WordTimeline
)

& $Python @ArgsList
