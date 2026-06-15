param(
  [string]$DraftDir = "D:\JianyingPro Drafts\6月14日",
  [string]$BackupDir = "D:\video tools\jianying-aroll-inspector\runtime\aroll_roughcut_write_20260614_111435\backup",
  [string]$V5Dir = "D:\video tools\jianying-aroll-inspector\runtime\aroll_corrective_v5_20260614_163617",
  [string]$RepeatClusters = "D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4_diagnostics_20260614_171206\repeat_clusters.json",
  [string]$WordTimeline = "D:\video tools\jianying-aroll-inspector\runtime\aroll_phase4_diagnostics_20260614_171206\word_timeline.json",
  [int]$TargetKeepPauseUs = 20000
)

$ErrorActionPreference = "Stop"

foreach ($PathToCheck in @($DraftDir, $BackupDir, $V5Dir, $RepeatClusters, $WordTimeline)) {
  if (!(Test-Path -LiteralPath $PathToCheck)) {
    throw "路径不存在：$PathToCheck"
  }
}

Write-Host "CONFIRM_DRAFT_DIR=$DraftDir"
Write-Host "MODE=PHASE_4D_75S_SEGMENT_TEST"
Write-Host "RESTORE_ORIGINAL_FULL_DRAFT=1"
Write-Host "WRITE_SINGLE_TEST_DRAFT_ONLY=1"
Write-Host "NO_EXTRA_CANDIDATE_DRAFT_DIR=1"
Write-Host "NO_DEEPSEEK=1"
Write-Host "NO_SUBTITLE_RESPLIT=1"
Write-Host "NO_AUDIO_FILTER_TRACK_MODIFICATION=1"
Write-Host "NO_PROJECT_JSON_OR_TIMELINE_LAYOUT_CHANGE=1"
Write-Host "TARGET_KEEP_PAUSE_US=$TargetKeepPauseUs"

$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  throw "Codex Python 不存在：$Python"
}

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\aroll_phase4d_long_segment_test.py"),
  "--draft-dir", $DraftDir,
  "--backup-dir", $BackupDir,
  "--v5-dir", $V5Dir,
  "--repeat-clusters", $RepeatClusters,
  "--word-timeline", $WordTimeline,
  "--target-keep-pause-us", $TargetKeepPauseUs
)

& $Python @ArgsList
