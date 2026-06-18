param(
  [string]$DraftDir,
  [string]$TimelineName = "",
  [int]$MainVideoTrackIndex = -1,
  [string]$MainMaterialPath = "",
  [double]$MaxAllowedSpeed = 1.25,
  [string]$Runtime = "",
  [string]$InputJson = ""
)

$ErrorActionPreference = "Stop"

function Resolve-Python {
  foreach ($Candidate in @($env:PYTHON, $env:PYTHON_EXE)) {
    if ([string]::IsNullOrWhiteSpace($Candidate)) { continue }
    if (Test-Path -LiteralPath $Candidate) { return $Candidate }
    $Command = Get-Command $Candidate -ErrorAction SilentlyContinue
    if ($Command) { return $Command.Source }
    throw "Python 解释器不存在：$Candidate"
  }
  $Command = Get-Command python -ErrorAction SilentlyContinue
  if ($Command) { return $Command.Source }
  throw "Python 不存在：请设置 PYTHON 或 PYTHON_EXE，或将 python 加入 PATH。"
}

if ([string]::IsNullOrWhiteSpace($DraftDir)) {
  $ResolvedInputJson = $InputJson
  if ([string]::IsNullOrWhiteSpace($ResolvedInputJson) -and -not [string]::IsNullOrWhiteSpace($env:JY_ALIGNER_ROOT)) {
    $ResolvedInputJson = Join-Path $env:JY_ALIGNER_ROOT "agent_inputs.json"
  }
  if (-not [string]::IsNullOrWhiteSpace($ResolvedInputJson) -and (Test-Path -LiteralPath $ResolvedInputJson)) {
    $Config = Get-Content -LiteralPath $ResolvedInputJson -Raw | ConvertFrom-Json
    if ($Config.draft_dir) {
      $DraftDir = [string]$Config.draft_dir
    }
    if ([string]::IsNullOrWhiteSpace($TimelineName)) {
      if ($Config.timeline_name) {
        $TimelineName = [string]$Config.timeline_name
      }
    }
    Write-Host "USING_AGENT_INPUTS=$ResolvedInputJson"
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

$Python = Resolve-Python

$ArgsList = @(
  (Join-Path $PSScriptRoot "src\aroll_inspect.py"),
  "--draft-dir", $DraftDir,
  "--timeline-name", $TimelineName,
  "--main-video-track-index", "$MainVideoTrackIndex",
  "--main-material-path", $MainMaterialPath,
  "--max-allowed-speed", "$MaxAllowedSpeed"
)
if (-not [string]::IsNullOrWhiteSpace($Runtime)) { $ArgsList += @("--runtime", $Runtime) }

& $Python @ArgsList
