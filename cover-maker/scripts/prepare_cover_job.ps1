param(
  [Parameter(Mandatory=$true)][string]$ProjectId,
  [Parameter(Mandatory=$true)][ValidateSet("standard_pipeline", "old_video_recovery")][string]$WorkflowMode,
  [string]$DraftName = "",
  [string]$DraftDir = "",
  [string]$SourceBrollDesign = "",
  [Parameter(Mandatory=$true)][string]$SourceUserScript,
  [Parameter(Mandatory=$true)][string]$VideoTitle,
  [Parameter(Mandatory=$true)][string]$CoverTitle,
  [Parameter(Mandatory=$true)][string]$CoverTitleSourceLocation,
  [Parameter(Mandatory=$true)][string]$CoverTitleDesignReason,
  [ValidateSet("white_editorial", "dark_face")][string]$CoverType = "white_editorial",
  [Parameter(Mandatory=$true)][string[]]$TitleLine,
  [Parameter(Mandatory=$true)][string]$SubjectSource,
  [Parameter(Mandatory=$true)][string]$OutputRoot,
  [Parameter(Mandatory=$true)][switch]$CommanderConfirmedOutputDir,
  [string]$JobPath = "",
  [switch]$Force
)

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "prepare_cover_job.py"
$py = Get-Command py.exe -ErrorAction SilentlyContinue
$python = if ($py) { @($py.Source, "-3") } else { @((Get-Command python.exe -ErrorAction Stop).Source) }
$arguments = @(
  $scriptPath,
  "--project-id", $ProjectId,
  "--workflow-mode", $WorkflowMode,
  "--source-user-script", $SourceUserScript,
  "--video-title", $VideoTitle,
  "--cover-title", $CoverTitle,
  "--cover-title-source-location", $CoverTitleSourceLocation,
  "--cover-title-design-reason", $CoverTitleDesignReason,
  "--cover-type", $CoverType,
  "--subject-source", $SubjectSource,
  "--output-root", $OutputRoot,
  "--commander-confirmed-output-dir"
)
if ($DraftName) { $arguments += @("--draft-name", $DraftName) }
if ($DraftDir) { $arguments += @("--draft-dir", $DraftDir) }
if ($SourceBrollDesign) { $arguments += @("--source-broll-design", $SourceBrollDesign) }
if ($JobPath) { $arguments += @("--job-path", $JobPath) }
foreach ($line in $TitleLine) { $arguments += @("--title-line", $line) }
if ($Force) { $arguments += "--force" }

if ($python.Count -gt 1) {
  & $python[0] $python[1..($python.Count - 1)] $arguments
} else {
  & $python[0] $arguments
}
if ($LASTEXITCODE -ne 0) {
  throw "Cover job preparation failed with exit code $LASTEXITCODE."
}
