param(
  [string]$CurrentDraftPath = $(if ($env:AUTO_CLIP_RUNTIME_DIR) { Join-Path $env:AUTO_CLIP_RUNTIME_DIR "video_pipeline\current_draft.json" } else { Join-Path $HOME ".auto_clip_runtime\video_pipeline\current_draft.json" }),
  [switch]$AssertComplete,
  [switch]$RequireCoverFiles,
  [switch]$RequireFinalExport
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $CurrentDraftPath)) {
  throw "current_draft not found: $CurrentDraftPath"
}

$state = Get-Content -LiteralPath $CurrentDraftPath -Raw -Encoding UTF8 | ConvertFrom-Json
$coverQcPassed = [bool]$state.cover_qc_passed
$hasDeclaredComplete = $null -ne $state.PSObject.Properties["factory_chain_complete"]
if ($hasDeclaredComplete) {
  $declaredComplete = [bool]$state.factory_chain_complete

  if ($declaredComplete -ne $coverQcPassed) {
    throw "FACTORY_COMPLETION_CONTRACT_VIOLATION: factory_chain_complete must equal cover_qc_passed. cover_qc_passed=$coverQcPassed factory_chain_complete=$declaredComplete"
  }
}

if ($AssertComplete -and -not $coverQcPassed) {
  $stage = [string]$state.stage
  $deliveryStatus = [string]$state.delivery_status
  throw "FACTORY_CHAIN_NOT_COMPLETE: only cover_qc_passed=true completes the clipping factory. stage=$stage delivery_status=$deliveryStatus"
}

function Get-FirstExistingValue {
  param($Values)
  foreach ($value in $Values) {
    if ($value) {
      return [string]$value
    }
  }
  return ""
}

function Get-ValidatedImageInfo {
  param(
    [Parameter(Mandatory=$true)][string]$Path,
    [Parameter(Mandatory=$true)][string]$Label,
    [Parameter(Mandatory=$true)][double]$ExpectedAspect,
    [Parameter(Mandatory=$true)][int]$MinimumWidth,
    [Parameter(Mandatory=$true)][int]$MinimumHeight
  )
  Add-Type -AssemblyName System.Drawing
  try {
    $image = [System.Drawing.Image]::FromFile($Path)
  } catch {
    throw "FACTORY_COVER_FILE_INVALID: $Label is not a decodable image: $Path"
  }
  try {
    $width = [int]$image.Width
    $height = [int]$image.Height
    $aspect = $width / [double]$height
    if ($width -lt $MinimumWidth -or $height -lt $MinimumHeight) {
      throw "FACTORY_COVER_DIMENSIONS_INVALID: $Label is too small: ${width}x${height} minimum=${MinimumWidth}x${MinimumHeight} path=$Path"
    }
    if ([Math]::Abs($aspect - $ExpectedAspect) -gt 0.02) {
      throw "FACTORY_COVER_ASPECT_INVALID: $Label aspect=$aspect expected=$ExpectedAspect path=$Path"
    }
    return [PSCustomObject]@{ width = $width; height = $height; aspect = $aspect }
  } finally {
    $image.Dispose()
  }
}

$cover16Path = Get-FirstExistingValue @($state.cover_16x9_path, $state.cover.cover_16x9_path, $state.cover.project_cover_16x9_path)
$cover9Path = Get-FirstExistingValue @($state.cover_9x16_path, $state.cover.cover_9x16_path, $state.cover.project_cover_9x16_path)
$finalVideoPath = if ($state.final_export -and $state.final_export.video_path) { [string]$state.final_export.video_path } else { "" }

if ($AssertComplete -and $RequireCoverFiles) {
  if (-not $cover16Path -or -not (Test-Path -LiteralPath $cover16Path)) {
    throw "FACTORY_COVER_FILE_MISSING: official 16:9 cover path is missing or not found: $cover16Path"
  }
  if (-not $cover9Path -or -not (Test-Path -LiteralPath $cover9Path)) {
    throw "FACTORY_COVER_FILE_MISSING: official 9:16 cover path is missing or not found: $cover9Path"
  }
  $null = Get-ValidatedImageInfo -Path $cover16Path -Label "official 16:9 cover" -ExpectedAspect (16.0 / 9.0) -MinimumWidth 1280 -MinimumHeight 720
  $null = Get-ValidatedImageInfo -Path $cover9Path -Label "official 9:16 cover" -ExpectedAspect (9.0 / 16.0) -MinimumWidth 720 -MinimumHeight 1280
}

if ($AssertComplete -and $RequireFinalExport) {
  if (-not $finalVideoPath -or -not (Test-Path -LiteralPath $finalVideoPath)) {
    throw "FACTORY_FINAL_EXPORT_MISSING: final export video path is missing or not found: $finalVideoPath"
  }
}

$status = if ($coverQcPassed) { "complete" } else { "not_complete" }
[PSCustomObject]@{
  status = $status
  factory_chain_complete = $coverQcPassed
  cover_qc_passed = $coverQcPassed
  stage = $state.stage
  delivery_status = $state.delivery_status
  next_stage = $state.next_stage
  cover_16x9_path = $cover16Path
  cover_9x16_path = $cover9Path
  final_export_video_path = $finalVideoPath
  rule = "cover_qc_passed=true is the only full-chain completion condition"
} | ConvertTo-Json -Depth 8
