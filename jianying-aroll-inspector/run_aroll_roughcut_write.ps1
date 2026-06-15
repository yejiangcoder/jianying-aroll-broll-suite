param(
  [string]$DraftDir,
  [string]$TimelineName = "",
  [string]$InputJson = "D:\video tools\jianying-ai-image-aligner\agent_inputs.json"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($DraftDir)) {
  if (Test-Path -LiteralPath $InputJson) {
    $Config = Get-Content -LiteralPath $InputJson -Raw | ConvertFrom-Json
    if ($Config.draft_dir) {
      $DraftDir = [string]$Config.draft_dir
    }
    if ([string]::IsNullOrWhiteSpace($TimelineName) -and $Config.timeline_name) {
      $TimelineName = [string]$Config.timeline_name
    }
    Write-Host "USING_AGENT_INPUTS=$InputJson"
  }
}

if ([string]::IsNullOrWhiteSpace($DraftDir)) {
  throw "必须传入 -DraftDir；或在 InputJson 中提供 draft_dir。"
}
if (!(Test-Path -LiteralPath $DraftDir)) {
  throw "DraftDir 不存在：$DraftDir"
}

Write-Host "CONFIRM_DRAFT_DIR=$DraftDir"
Write-Host "CONFIRM_DRAFT_SCOPE_HINT=$TimelineName"
Write-Host "MODE=WRITE_AROLL_ROUGHCUT_POC"
Write-Host "WARNING=This command writes the sacrificial test draft after creating runtime backups."

$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  $Python = "python"
}

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\aroll_roughcut_writer.py"),
  "--draft-dir", $DraftDir,
  "--timeline-name", $TimelineName
)

& $Python @ArgsList
