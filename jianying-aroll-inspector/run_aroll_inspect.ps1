param(
  [string]$DraftDir,
  [string]$TimelineName = "",
  [int]$MainVideoTrackIndex = -1,
  [string]$MainMaterialPath = "",
  [double]$MaxAllowedSpeed = 1.25,
  [string]$InputJson = "D:\video tools\jianying-ai-image-aligner\agent_inputs.json"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($DraftDir)) {
  if (Test-Path -LiteralPath $InputJson) {
    $Config = Get-Content -LiteralPath $InputJson -Raw | ConvertFrom-Json
    if ($Config.draft_dir) {
      $DraftDir = [string]$Config.draft_dir
    }
    if ([string]::IsNullOrWhiteSpace($TimelineName)) {
      if ($Config.timeline_name) {
        $TimelineName = [string]$Config.timeline_name
      }
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
if (-not [string]::IsNullOrWhiteSpace($MainMaterialPath) -and !(Test-Path -LiteralPath $MainMaterialPath)) {
  throw "MainMaterialPath 不存在：$MainMaterialPath"
}

Write-Host "CONFIRM_DRAFT_DIR=$DraftDir"
Write-Host "CONFIRM_DRAFT_SCOPE_HINT=$TimelineName"
Write-Host "CONFIRM_MAIN_VIDEO_TRACK_INDEX=$MainVideoTrackIndex"
Write-Host "CONFIRM_MAIN_MATERIAL_PATH=$MainMaterialPath"
Write-Host "MODE=READ_ONLY_INSPECT"

$Python = "C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (!(Test-Path -LiteralPath $Python)) {
  $Python = "python"
}

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\aroll_inspect.py"),
  "--draft-dir", $DraftDir,
  "--timeline-name", $TimelineName,
  "--main-video-track-index", "$MainVideoTrackIndex",
  "--main-material-path", $MainMaterialPath,
  "--max-allowed-speed", "$MaxAllowedSpeed"
)

& $Python @ArgsList
