param(
  [string]$DraftDir,
  [string]$BrollMd,
  [string]$ImageDir,
  [string]$ExcludeIds = "",
  [string]$TimelineName = "",
  [string]$InputJson = "D:\video tools\jianying-ai-image-aligner\agent_inputs.json",
  [switch]$ConfirmWrite
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($DraftDir) -and [string]::IsNullOrWhiteSpace($BrollMd) -and [string]::IsNullOrWhiteSpace($ImageDir)) {
  if (!(Test-Path -LiteralPath $InputJson)) {
    throw "未传入路径参数，且变量文件不存在：$InputJson"
  }
  $Config = Get-Content -LiteralPath $InputJson -Raw | ConvertFrom-Json
  $DraftDir = [string]$Config.draft_dir
  $BrollMd = [string]$Config.broll_md
  $ImageDir = [string]$Config.ai_image_dir
  if ($Config.timeline_name) {
    $TimelineName = [string]$Config.timeline_name
  }
  if ($Config.exclude_image_ids) {
    $ExcludeIds = ($Config.exclude_image_ids -join ",")
  }
  Write-Host "USING_AGENT_INPUTS=$InputJson"
}
if ([string]::IsNullOrWhiteSpace($DraftDir) -or [string]::IsNullOrWhiteSpace($BrollMd) -or [string]::IsNullOrWhiteSpace($ImageDir)) {
  throw "必须显式传入 -DraftDir、-BrollMd、-ImageDir；禁止使用旧项目默认值。"
}
foreach ($PathToCheck in @($DraftDir, $BrollMd, $ImageDir)) {
  if (!(Test-Path -LiteralPath $PathToCheck)) {
    throw "路径不存在：$PathToCheck"
  }
}
Write-Host "CONFIRM_DRAFT_DIR=$DraftDir"
Write-Host "CONFIRM_BROLL_MD=$BrollMd"
Write-Host "CONFIRM_IMAGE_DIR=$ImageDir"
Write-Host "CONFIRM_EXCLUDE_IDS=$ExcludeIds"
Write-Host "CONFIRM_DRAFT_SCOPE_HINT=$TimelineName"
Write-Host "CONFIRM_MODE=$(if ($ConfirmWrite) { 'WRITE_AFTER_PREFLIGHT' } else { 'PREFLIGHT_ONLY' })"
$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  $Python = "python"
}

$WriterArgs = @(
  "D:\video tools\jianying-ai-image-aligner\src\direct_draft_broll_writer.py",
  "--draft-dir", $DraftDir,
  "--broll", $BrollMd,
  "--image-dir", $ImageDir,
  "--exclude-ids", $ExcludeIds,
  "--timeline-name", $TimelineName
)

if ($ConfirmWrite) {
  & (Join-Path $PSScriptRoot "cleanup_runtime.ps1") -KeepLatest 5 -ConfirmDelete
  Get-Process JianyingPro -ErrorAction SilentlyContinue | Stop-Process -Force
  $WriterArgs += "--confirm-write"
} else {
  $WriterArgs += "--preflight-only"
}

& $Python @WriterArgs
