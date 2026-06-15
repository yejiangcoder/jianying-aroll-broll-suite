param(
  [Parameter(Mandatory = $true)]
  [string]$DraftDir,
  [string]$DeepSeekRun = "D:\video tools\jianying-aroll-inspector\runtime\aroll_deepseek_decision_20260614_114516",
  [string]$TimelineName = ""
)

$ErrorActionPreference = "Stop"

if (!(Test-Path -LiteralPath $DraftDir)) {
  throw "DraftDir 不存在：$DraftDir"
}
if (!(Test-Path -LiteralPath $DeepSeekRun)) {
  throw "DeepSeekRun 不存在：$DeepSeekRun"
}

Write-Host "CONFIRM_DRAFT_DIR=$DraftDir"
Write-Host "CONFIRM_DEEPSEEK_RUN=$DeepSeekRun"
Write-Host "MODE=CONSERVATIVE_DEEPSEEK_SMART_AROLL_WRITE"
Write-Host "WILL_WRITE_TEST_DRAFT=1"
Write-Host "NO_DEEPSEEK_API_CALL=1"

$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  $Python = "python"
}

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\aroll_smart_writer.py"),
  "--draft-dir", $DraftDir,
  "--deepseek-run", $DeepSeekRun
)
if ($TimelineName) {
  $ArgsList += @("--timeline-name", $TimelineName)
}

& $Python @ArgsList
