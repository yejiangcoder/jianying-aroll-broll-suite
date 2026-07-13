param(
  [Parameter(Mandatory=$true)][string]$CoverGenerationManifestPath,
  [string]$CurrentDraftPath = ""
)

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "validate_cover_package.py"
$py = Get-Command py.exe -ErrorAction SilentlyContinue
$python = if ($py) { @($py.Source, "-3") } else { @((Get-Command python.exe -ErrorAction Stop).Source) }
$arguments = @($scriptPath, "--manifest", $CoverGenerationManifestPath)
if ($CurrentDraftPath) { $arguments += @("--current-draft", $CurrentDraftPath) }

if ($python.Count -gt 1) {
  & $python[0] $python[1..($python.Count - 1)] $arguments
} else {
  & $python[0] $arguments
}
if ($LASTEXITCODE -ne 0) {
  throw "Cover package validation failed with exit code $LASTEXITCODE."
}
