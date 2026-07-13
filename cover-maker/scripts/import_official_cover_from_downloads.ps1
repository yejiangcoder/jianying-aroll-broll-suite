param(
  [Parameter(Mandatory=$true)]
  [string]$EpisodeDir,

  [string]$SourceDir = (Join-Path $env:USERPROFILE "Downloads"),
  [string]$Source16x9 = "",
  [string]$Source9x16 = "",
  [string]$OutputDir = "",
  [string]$CurrentDraftPath = $(if ($env:AUTO_CLIP_RUNTIME_DIR) { Join-Path $env:AUTO_CLIP_RUNTIME_DIR "video_pipeline\current_draft.json" } else { Join-Path $HOME ".auto_clip_runtime\video_pipeline\current_draft.json" }),
  [string]$ExpectedDraftName = "",
  [string]$ProjectId = "",
  [switch]$Move,
  [switch]$UpdateCurrentDraft,
  [switch]$CommanderQcPassed,
  [switch]$AllowOutsideEpisodeDir,
  [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

function Set-JsonProperty {
  param(
    [Parameter(Mandatory=$true)]$Object,
    [Parameter(Mandatory=$true)][string]$Name,
    $Value
  )
  if ($Object.PSObject.Properties.Name -contains $Name) {
    $Object.$Name = $Value
  } else {
    $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
  }
}

function Get-ImageInfo {
  param([Parameter(Mandatory=$true)][string]$Path)
  Add-Type -AssemblyName System.Drawing
  $img = [System.Drawing.Image]::FromFile($Path)
  try {
    return [PSCustomObject]@{
      path = [System.IO.Path]::GetFullPath($Path)
      width = $img.Width
      height = $img.Height
      aspect = [Math]::Round($img.Width / [double]$img.Height, 4)
      last_write_ticks = (Get-Item -LiteralPath $Path).LastWriteTimeUtc.Ticks
    }
  } finally {
    $img.Dispose()
  }
}

function Copy-Or-MoveFile {
  param(
    [string]$Source,
    [string]$Target,
    [switch]$Move
  )
  if (Test-Path -LiteralPath $Target) {
    $backup = "$Target.previous_$(Get-Date -Format 'yyyyMMdd_HHmmss').bak"
    Move-Item -LiteralPath $Target -Destination $backup
  }
  if ($Move) {
    Move-Item -LiteralPath $Source -Destination $Target
  } else {
    Copy-Item -LiteralPath $Source -Destination $Target
  }
}

function New-ContactSheet {
  param(
    [string]$LandscapePath,
    [string]$PortraitPath,
    [string]$TargetPath
  )
  Add-Type -AssemblyName System.Drawing
  $canvas = New-Object System.Drawing.Bitmap 1600, 900
  $g = [System.Drawing.Graphics]::FromImage($canvas)
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
  $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g.Clear([System.Drawing.Color]::FromArgb(246, 246, 244))
  $font = New-Object System.Drawing.Font "Microsoft YaHei", 30, ([System.Drawing.FontStyle]::Bold)
  $brush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(22, 22, 22))
  $g.DrawString("Official cover import preview", $font, $brush, 48, 38)

  $landscape = [System.Drawing.Image]::FromFile($LandscapePath)
  $portrait = [System.Drawing.Image]::FromFile($PortraitPath)
  try {
    $g.DrawImage($landscape, 60, 130, 940, 529)
    $g.DrawImage($portrait, 1110, 130, 360, 640)
    $smallFont = New-Object System.Drawing.Font "Microsoft YaHei", 18, ([System.Drawing.FontStyle]::Regular)
    $g.DrawString("16:9 official", $smallFont, $brush, 60, 690)
    $g.DrawString("9:16 official", $smallFont, $brush, 1110, 800)
  } finally {
    $landscape.Dispose()
    $portrait.Dispose()
    $g.Dispose()
    $canvas.Save($TargetPath, [System.Drawing.Imaging.ImageFormat]::Jpeg)
    $canvas.Dispose()
  }
}

if (-not (Test-Path -LiteralPath $EpisodeDir)) {
  throw "EpisodeDir not found: $EpisodeDir"
}
if (-not (Test-Path -LiteralPath $SourceDir)) {
  throw "SourceDir not found: $SourceDir"
}
if ($UpdateCurrentDraft -and -not $CommanderQcPassed) {
  throw "Use -CommanderQcPassed with -UpdateCurrentDraft. Imported covers must be commander-approved before current_draft cover_qc_passed is set."
}
if ($UpdateCurrentDraft -and -not $ExpectedDraftName) {
  throw "ExpectedDraftName is required with -UpdateCurrentDraft to prevent cross-project cover writes."
}

$state = $null
if ($UpdateCurrentDraft) {
  if (-not (Test-Path -LiteralPath $CurrentDraftPath)) {
    throw "CurrentDraftPath not found: $CurrentDraftPath"
  }
  $state = Get-Content -LiteralPath $CurrentDraftPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ([string]$state.draft_name -ne $ExpectedDraftName) {
    throw "Current draft mismatch: expected=$ExpectedDraftName actual=$($state.draft_name)"
  }
  if (-not [bool]$state.aroll_qc_passed) {
    throw "Current draft is not eligible for cover import: aroll_qc_passed is not true."
  }
  if (-not $state.broll_write -or [string]$state.broll_write.status -ne "passed" -or -not $state.broll_write.commander_qc_passed_at) {
    throw "Current draft is not eligible for cover import: B-Roll write/QC has not passed."
  }
  $enhancementStatus = [string]$state.enhancement_decision_status
  if ($enhancementStatus -notmatch "resolved|passed|skipped") {
    throw "Current draft is not eligible for cover import: enhancement decision is unresolved."
  }
}

$resolvedEpisodeDir = [System.IO.Path]::GetFullPath($EpisodeDir)
if (-not $OutputDir) {
  $coverFolderName = -join ([char]0x5c01, [char]0x9762)
  $OutputDir = Join-Path (Join-Path $resolvedEpisodeDir "resource") $coverFolderName
}
$resolvedOutputDir = [System.IO.Path]::GetFullPath($OutputDir)
if (-not $AllowOutsideEpisodeDir -and -not $resolvedOutputDir.StartsWith($resolvedEpisodeDir, [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "OutputDir must be inside EpisodeDir unless -AllowOutsideEpisodeDir is used. OutputDir=$resolvedOutputDir EpisodeDir=$resolvedEpisodeDir"
}

$extensions = @(".png", ".jpg", ".jpeg", ".webp")
$imageInfos = @()
if (-not $Source16x9 -or -not $Source9x16) {
  $images = Get-ChildItem -LiteralPath $SourceDir -File |
    Where-Object { $extensions -contains $_.Extension.ToLowerInvariant() } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 30
  foreach ($image in $images) {
    try {
      $imageInfos += Get-ImageInfo -Path $image.FullName
    } catch {
      Write-Warning "Skip unreadable image: $($image.FullName)"
    }
  }
}

if (-not $Source16x9) {
  $Source16x9 = @($imageInfos | Where-Object { [Math]::Abs($_.aspect - (16.0 / 9.0)) -le 0.02 } | Sort-Object last_write_ticks -Descending)[0].path
}
if (-not $Source9x16) {
  $Source9x16 = @($imageInfos | Where-Object { [Math]::Abs($_.aspect - (9.0 / 16.0)) -le 0.02 } | Sort-Object last_write_ticks -Descending)[0].path
}
if (-not $Source16x9 -or -not (Test-Path -LiteralPath $Source16x9)) {
  throw "Could not resolve 16:9 source cover. Pass -Source16x9 explicitly."
}
if (-not $Source9x16 -or -not (Test-Path -LiteralPath $Source9x16)) {
  throw "Could not resolve 9:16 source cover. Pass -Source9x16 explicitly."
}

$info16 = Get-ImageInfo -Path $Source16x9
$info9 = Get-ImageInfo -Path $Source9x16
if ($info16.path -eq $info9.path) {
  throw "16:9 and 9:16 sources resolved to the same file: $($info16.path)"
}
if ([Math]::Abs($info16.aspect - (16.0 / 9.0)) -gt 0.02) {
  throw "Source16x9 must be 16:9 within tolerance: $($info16.path) aspect=$($info16.aspect)"
}
if ([Math]::Abs($info9.aspect - (9.0 / 16.0)) -gt 0.02) {
  throw "Source9x16 must be 9:16 within tolerance: $($info9.path) aspect=$($info9.aspect)"
}
if ($info16.width -lt 1280 -or $info16.height -lt 720) {
  throw "Source16x9 is too small: $($info16.path) size=$($info16.width)x$($info16.height)"
}
if ($info9.width -lt 720 -or $info9.height -lt 1280) {
  throw "Source9x16 is too small: $($info9.path) size=$($info9.width)x$($info9.height)"
}

$episodeName = Split-Path -Leaf $resolvedEpisodeDir
$safeEpisodeName = ($episodeName -replace '[\\/:*?"<>|]', '_')
$target16 = Join-Path $resolvedOutputDir ("{0}_cover_16x9_official{1}" -f $safeEpisodeName, ([System.IO.Path]::GetExtension($info16.path).ToLowerInvariant()))
$target9 = Join-Path $resolvedOutputDir ("{0}_cover_9x16_official{1}" -f $safeEpisodeName, ([System.IO.Path]::GetExtension($info9.path).ToLowerInvariant()))
$manifestPath = Join-Path $resolvedOutputDir ("{0}_official_cover_manifest.json" -f $safeEpisodeName)
$contactSheetPath = Join-Path $resolvedOutputDir ("{0}_official_cover_contact_sheet.jpg" -f $safeEpisodeName)

if (-not $ValidateOnly) {
  New-Item -ItemType Directory -Path $resolvedOutputDir -Force | Out-Null
  Copy-Or-MoveFile -Source $info16.path -Target $target16 -Move:$Move
  Copy-Or-MoveFile -Source $info9.path -Target $target9 -Move:$Move
  New-ContactSheet -LandscapePath $target16 -PortraitPath $target9 -TargetPath $contactSheetPath
}

$manifest = [PSCustomObject]@{
  schema_version = "official_cover_import.v1"
  created_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz")
  status = if ($CommanderQcPassed) { "commander_qc_passed" } else { "imported_pending_commander_qc" }
  generation_mode = "commander_web_llm_external_import"
  project_id = $ProjectId
  expected_draft_name = $ExpectedDraftName
  episode_dir = $resolvedEpisodeDir
  output_dir = $resolvedOutputDir
  source_16x9_path = $info16.path
  source_9x16_path = $info9.path
  cover_16x9_path = $target16
  cover_9x16_path = $target9
  contact_sheet_path = $contactSheetPath
  source_16x9_width = $info16.width
  source_16x9_height = $info16.height
  source_9x16_width = $info9.width
  source_9x16_height = $info9.height
  file_operation = if ($Move) { "move" } else { "copy" }
}

if (-not $ValidateOnly) {
  $manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

  if ($UpdateCurrentDraft) {
    $cover = [PSCustomObject]@{
      status = "commander_qc_passed"
      generation_mode = "commander_web_llm_external_import"
      imported_at = $manifest.created_at
      output_dir = $resolvedOutputDir
      generation_manifest_path = $manifestPath
      cover_16x9_path = $target16
      cover_9x16_path = $target9
      project_cover_16x9_path = $target16
      project_cover_9x16_path = $target9
      manual_qc_status = "commander_qc_passed"
      commander_qc_passed_at = $manifest.created_at
      project_id = $ProjectId
    }
    Set-JsonProperty -Object $state -Name "cover" -Value $cover
    Set-JsonProperty -Object $state -Name "cover_generation_mode" -Value "commander_web_llm_external_import"
    Set-JsonProperty -Object $state -Name "cover_project_id" -Value $ProjectId
    Set-JsonProperty -Object $state -Name "cover_generation_manifest_path" -Value $manifestPath
    Set-JsonProperty -Object $state -Name "cover_16x9_path" -Value $target16
    Set-JsonProperty -Object $state -Name "cover_9x16_path" -Value $target9
    Set-JsonProperty -Object $state -Name "cover_qc_passed" -Value $true
    Set-JsonProperty -Object $state -Name "factory_chain_complete" -Value $true
    Set-JsonProperty -Object $state -Name "stage" -Value "cover_qc_passed"
    Set-JsonProperty -Object $state -Name "delivery_status" -Value "cover_qc_passed"
    Set-JsonProperty -Object $state -Name "next_stage" -Value "delivery_closeout"
    Set-JsonProperty -Object $state -Name "updated_at" -Value $manifest.created_at
    $state | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath $CurrentDraftPath -Encoding UTF8
  }
}

[PSCustomObject]@{
  status = if ($ValidateOnly) { "validated_only" } elseif ($CommanderQcPassed) { "official_cover_imported_qc_passed" } else { "official_cover_imported_pending_qc" }
  manifest_path = if ($ValidateOnly) { "" } else { $manifestPath }
  contact_sheet_path = if ($ValidateOnly) { "" } else { $contactSheetPath }
  current_draft_updated = [bool]($UpdateCurrentDraft -and -not $ValidateOnly)
  cover_16x9_path = $target16
  cover_9x16_path = $target9
} | ConvertTo-Json -Depth 12
