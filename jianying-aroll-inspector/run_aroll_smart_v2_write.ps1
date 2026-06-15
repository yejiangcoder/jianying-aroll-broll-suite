param(
  [Parameter(Mandatory = $true)]
  [string]$DraftDir,
  [string]$DeepSeekRun = "D:\video tools\jianying-aroll-inspector\runtime\aroll_deepseek_decision_20260614_114516",
  [string]$OriginalSubtitleTimeline = "D:\video tools\jianying-aroll-inspector\runtime\aroll_inspect_20260614_111146\subtitle_timeline.json",
  [string]$TimelineName = ""
)

$ErrorActionPreference = "Stop"

if (!(Test-Path -LiteralPath $DraftDir)) {
  throw "DraftDir 不存在：$DraftDir"
}
if (!(Test-Path -LiteralPath $DeepSeekRun)) {
  throw "DeepSeekRun 不存在：$DeepSeekRun"
}
if (!(Test-Path -LiteralPath $OriginalSubtitleTimeline)) {
  throw "OriginalSubtitleTimeline 不存在：$OriginalSubtitleTimeline"
}

Write-Host "CONFIRM_DRAFT_DIR=$DraftDir"
Write-Host "CONFIRM_DEEPSEEK_RUN=$DeepSeekRun"
Write-Host "CONFIRM_ORIGINAL_SUBTITLE_TIMELINE=$OriginalSubtitleTimeline"
Write-Host "MODE=SMART_AROLL_V2_RESIDUAL_CLEANUP_WRITE"
Write-Host "WILL_WRITE_TEST_DRAFT=1"
Write-Host "NO_DEEPSEEK_API_CALL=1"

$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  $Python = "python"
}

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\aroll_smart_v2_writer.py"),
  "--draft-dir", $DraftDir,
  "--deepseek-run", $DeepSeekRun,
  "--original-subtitle-timeline", $OriginalSubtitleTimeline
)
if ($TimelineName) {
  $ArgsList += @("--timeline-name", $TimelineName)
}

& $Python @ArgsList
