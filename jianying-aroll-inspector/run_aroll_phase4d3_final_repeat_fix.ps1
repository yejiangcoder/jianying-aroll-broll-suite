param(
  [string]$DraftDir = "D:\JianyingPro Drafts\6月14日",
  [string]$BackupDir = "D:\video tools\jianying-aroll-inspector\runtime\aroll_roughcut_write_20260614_111435\backup",
  [string]$Phase4D2Dir = "D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4d2_75s_test_20260614_220351",
  [string]$WordTimeline = "D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4_diagnostics_20260614_171206\word_timeline.json"
)

$ErrorActionPreference = "Stop"

foreach ($PathToCheck in @($DraftDir, $BackupDir, $Phase4D2Dir, $WordTimeline)) {
  if (!(Test-Path -LiteralPath $PathToCheck)) {
    throw "路径不存在：$PathToCheck"
  }
}

Write-Host "CONFIRM_DRAFT_DIR=$DraftDir"
Write-Host "MODE=PHASE_4D3_FINAL_RESIDUAL_REPEAT_FIX"
Write-Host "RESTORE_ORIGINAL_FULL_DRAFT=1"
Write-Host "WRITE_SINGLE_TEST_DRAFT_ONLY=1"
Write-Host "NO_EXTRA_CANDIDATE_DRAFT_DIR=1"
Write-Host "NO_DEEPSEEK=1"
Write-Host "FINAL_TARGET_REPEAT_AUDIT=1"
Write-Host "TINY_SEGMENT_GUARD=1"
Write-Host "NO_AUDIO_FILTER_TRACK_MODIFICATION=1"
Write-Host "NO_PROJECT_JSON_OR_TIMELINE_LAYOUT_CHANGE=1"

$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  throw "Codex Python 不存在：$Python"
}

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\aroll_phase4d3_final_repeat_fix.py"),
  "--draft-dir", $DraftDir,
  "--backup-dir", $BackupDir,
  "--phase4d2-dir", $Phase4D2Dir,
  "--word-timeline", $WordTimeline
)

& $Python @ArgsList
